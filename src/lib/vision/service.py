"""Optional Cell Vision subsystem. Never controls recording or experiment state."""
from __future__ import annotations

import base64
import json
import threading
from concurrent.futures import ThreadPoolExecutor
import time
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

import cv2
import numpy as np

from .aruco import calibrate, detect_markers, grid_overlay, project_rectified, source_geometry
from .roi import compile_roi_maps, full_plane_geometry, remap_roi, remap_yuv420_roi
from .registry import VisionRegistry, _write
from lib.virtual_sensors.interface import COLOR_METHODS, DEFAULTS, config_signature, detect_interface, detection_roi, normalized_config
from .reference import resolve_vertical_reference


def _utc():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _jpeg_base64(image, quality=85):
    ok, buf = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, int(quality)])
    if not ok:
        raise RuntimeError("Could not encode camera image")
    return base64.b64encode(buf).decode("ascii")


def build_interface_diagnostic(image, reading, roi_cm, timestamp_ns):
    """Encode a single already-detected ROI, without calling the detector again."""
    source = reading.get("_diagnostics") or {}
    entropy = source.get("entropy_map")
    if entropy is None:
        return None
    entropy = np.asarray(entropy, np.float32)
    if entropy.shape != image.shape[:2]:
        raise ValueError("Entropy diagnostics must align with the rectified input image")
    if not np.isfinite(entropy).all():
        entropy = np.nan_to_num(entropy, nan=0., posinf=0., neginf=0.)
    lo, hi = float(entropy.min()), float(entropy.max())
    entropy_u8 = np.clip((entropy-lo)*255./(hi-lo),0,255).astype(np.uint8) if hi>lo else np.zeros_like(entropy,dtype=np.uint8)
    profiles = {}
    for key, values in (source.get("profiles") or {}).items():
        if values is None:
            continue
        series = np.asarray(values, dtype=np.float32).reshape(-1)
        if series.size != image.shape[0]:
            continue
        finite = np.isfinite(series)
        if not finite.any():
            continue
        mi, ma = float(np.min(series[finite])), float(np.max(series[finite]))
        normal = np.clip((np.nan_to_num(series, nan=mi, posinf=ma, neginf=mi)-mi) /
                         (ma-mi), 0., 1.) if ma>mi else np.zeros(series.size, dtype=np.float32)
        profiles[key] = {"values": np.round(normal, 4).tolist(), "min": mi, "max": ma}
    original = cv2.cvtColor(image,cv2.COLOR_GRAY2BGR) if image.ndim == 2 else image
    return {"image_jpeg_base64": _jpeg_base64(original, 72),
            "entropy_jpeg_base64": _jpeg_base64(entropy_u8, 72),
            "image_size": [int(image.shape[1]), int(image.shape[0])],
            "roi_cm": list(roi_cm), "method": source.get("method", reading.get("method")),
            "x_range_used": source.get("x_range_used", [0, image.shape[1]]),
            "profiles": profiles, "froth_row_px": reading.get("froth_surface_row_px"),
            "pulp_row_px": reading.get("pulp_froth_row_px"),
            "froth_surface_cm": reading.get("froth_surface_cm"),
            "pulp_froth_interface_cm": reading.get("pulp_froth_interface_cm"),
            "valid": bool(reading.get("valid")), "timestamp_ns": int(timestamp_ns or 0)}


def encode_monitor_frame(image, reading, timestamp_ns, requested_width=320):
    """Small JPEG from the exact frame the detector used (no second detector pass)."""
    height, width = image.shape[:2]
    output_width = min(width, max(1, int(requested_width)))
    if output_width != width:
        image = cv2.resize(image, (output_width, max(1, int(round(height*output_width/width)))),
                           interpolation=cv2.INTER_AREA)
    return {"jpeg_base64": _jpeg_base64(image, quality=65),
            "source_size": [width, height], "output_size": [image.shape[1], image.shape[0]],
            "froth_row_px": reading.get("froth_surface_row_px"),
            "pulp_row_px": reading.get("pulp_froth_row_px"),
            "valid": bool(reading.get("valid")), "timestamp_ns": int(timestamp_ns),
            "camera_id": reading.get("camera_id"), "cell_id": reading.get("cell_id")}



class VisionService:
    def __init__(self, digiflot, storage_root):
        self.digiflot = digiflot
        self.registry = VisionRegistry(storage_root)
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread = None
        self._pending = {}
        self._latest = {"state": "disabled", "updated_at": None}
        self._seen_runs = set()
        self._map_key = None
        self._roi_map = None
        self._virtual_test = None
        self._run_virtual = None
        self._last_virtual_measurement = None
        self._virtual_sample_count = 0
        self._benchmarking = False
        self._benchmark_series = []
        self._benchmark_diagnostic = None
        self._diagnostic_until = 0.0
        self._diagnostic_next_due = 0.0
        self._diagnostic_preview_camera_id = None
        self._diagnostic_revision = 0
        self._diagnostic_latest = None
        self._diagnostic_error = None
        self._diagnostic_future = None
        self._diagnostic_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="vision-diagnostic")
        self._monitor_until = 0.
        self._monitor_next_due = 0.
        self._monitor_width = 320
        self._monitor_revision = 0
        self._monitor_latest = None
        self._monitor_future = None
        self._monitor_error = None
        self._sync_camera_flags()

    def _sync_camera_flags(self):
        settings = self.registry.settings()
        selected = str(settings["camera_id"]) if settings["camera_id"] is not None else None
        for camera in self.digiflot.cameras.values():
            camera.analysis_enabled = bool(settings["enabled"] and str(camera.id) == selected)

    def start(self):
        if self._thread is None:
            self._thread = threading.Thread(target=self._loop, name="digiflot-vision", daemon=True)
            self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=3)
            self._thread = None
        self._diagnostic_executor.shutdown(wait=False, cancel_futures=True)

    def _compiled_roi(self, camera, cell_id, association, frame, config=None):
        roi = detection_roi(config, association)
        key = (str(camera.id), str(cell_id), association["calibration_id"],
               association["analysis_roi_revision"], tuple(roi),
               tuple(frame["size"]), tuple(frame["sensor_crop"]), (config or {}).get("resolution_px"))
        if key != self._map_key:
            # Preserve centimetres, but never upscale beyond the lores stream.
            from math import sqrt
            span_x, span_y = roi[2] - roi[0], roi[3] - roi[1]
            source_w, source_h = frame["size"]
            density = float(association["calibration"]["px_per_cm"])
            if config is not None:
                density = float(config["resolution_px"]) / span_x
            density = min(density, min(source_w, 1280) / span_x,
                          min(source_h, 960) / span_y, sqrt(1_000_000 / (span_x * span_y)))
            compiled = compile_roi_maps(association["calibration"],
                                        association["camera_profile"], frame, roi,
                                        px_per_cm=density, max_pixels=1_000_000)
            self._roi_map = compiled
            self._map_key = key
        return self._roi_map

    def _analysis_context(self):
        """Resolve the calibrated or frozen virtual sensor without starting video."""
        with self.digiflot.lock:
            run = self._run_virtual
            state = self.digiflot.state
            if run is not None and state in (self.digiflot.RUNNING, self.digiflot.PAUSED,
                                             self.digiflot.COMPLETED):
                camera_id = run.get("camera_id", self.digiflot.virtual_camera_id)
                camera = self.digiflot.cameras.get(int(camera_id)) if camera_id is not None else None
                if camera is None:
                    return None
                return {"camera": camera, "cell_id": run["cell_id"], "association": run["association"],
                        "config": run["config"],
                        "run": run if state in (self.digiflot.RUNNING, self.digiflot.PAUSED) else None}
            if state not in (self.digiflot.SENSOR_CALIBRATION, self.digiflot.READY):
                return None
            item = self.digiflot.sensor_calibration.get("froth_interface") or {}
            approved = item.get("status") == "passed" and self.virtual_test_passed()
            diagnosing = state == self.digiflot.SENSOR_CALIBRATION and time.monotonic() < self._diagnostic_until
            if not (approved or diagnosing):
                return None
            camera, cell_id, association, profile = self._virtual_context()
            return {"camera": camera, "cell_id": cell_id, "association": association,
                    "config": profile["config"], "run": None}

    def ensure_live_preview(self, context=None):
        """Open lores preview only when main recording is not active.

        Both preview startup and the transition into the main encoder are serialized
        on the DigiFlot lock. The recording controller owns preview shutdown.
        """
        with self.digiflot.lock:
            context = context or self._analysis_context()
            if context is None:
                return False
            camera = context["camera"]
            if self._benchmarking:
                return False
            if camera.state in (camera.PREVIEW, camera.RECORDING):
                return True
            if camera.state != camera.IDLE or self._benchmarking:
                return False
            if self.digiflot.recording:
                return False
            owner = self.digiflot.preview_camera_id
            if owner is not None and int(owner) != int(camera.id):
                return False
            camera.analysis_target_size = self._desired_lores_size(camera, context["association"], context["config"])
            camera.start_preview()
            self.digiflot.preview_camera_id = camera.id
            if self.digiflot.state == self.digiflot.SENSOR_CALIBRATION and not self.virtual_test_passed():
                self._diagnostic_preview_camera_id = camera.id
            return True

    def _loop(self):
        # One frame source; no unbounded queue. Preview and recording share ROI maps.
        next_due = time.monotonic()
        while not self._stop.is_set():
            try:
                context = self._analysis_context()
                settings = self.registry.settings() if context is None else None
                interval = (float(context["config"]["sampling_interval_s"]) if context else
                            float(settings["sampling_interval_s"]))
                interval = max(.2, interval)
            except Exception as error:
                self._latest = {"state": "error", "error": str(error), "updated_at": _utc()}
                context, settings, interval = None, None, 1.0
            if context is None and self._diagnostic_preview_camera_id is not None:
                with self.digiflot.lock:
                    if self.digiflot.preview_camera_id == self._diagnostic_preview_camera_id:
                        self.digiflot.stop_preview()
                    self._diagnostic_preview_camera_id = None
            if self._stop.wait(max(0, next_due - time.monotonic())):
                break
            next_due = max(next_due + interval, time.monotonic())
            if self._benchmarking:
                continue
            try:
                if context is not None:
                    if not self.ensure_live_preview(context):
                        self._latest = {"state": "waiting", "error": "Camera is busy or unavailable for lores",
                                        "updated_at": _utc()}
                        continue
                    camera, association = context["camera"], context["association"]
                    cell_id, config, active = context["cell_id"], context["config"], context["run"]
                elif settings and settings["enabled"] and settings["camera_id"] is not None:
                    camera = self.digiflot.cameras.get(int(settings["camera_id"]))
                    if camera is None or camera.state != camera.RECORDING:
                        continue
                    cell_id = settings.get("cell_id")
                    association = self.registry.association(camera.id, cell_id) if cell_id else None
                    config, active = None, None
                else:
                    continue
                started = time.perf_counter()
                roi = (detection_roi(config, association) if config and association else
                       (association or {}).get("analysis_roi_cm"))
                color = bool(config and config["method"] in COLOR_METHODS and roi)
                image, frame = camera.capture_analysis_frame(grayscale=not color, raw_yuv=color)
                status = {"state": "running", "mode": "experiment" if active else
                          ("live_preview" if config else "geometry"),
                          "camera_id": camera.id, "cell_id": cell_id,
                          "camera_state": camera.state,
                          "associated_calibration": (association or {}).get("calibration_id"),
                          "updated_at": _utc(), "error": None}
                if roi is not None:
                    compiled = self._compiled_roi(camera, cell_id, association, frame, config)
                    transformed = (remap_yuv420_roi(image, compiled, frame["size"]) if color
                                   else remap_roi(image, compiled))
                    status.update({"roi_processed": True, "roi_size": list(transformed.shape[1::-1]),
                                   "roi_coverage": compiled["coverage"], "markers_detected": None})
                    if config:
                        density = compiled["size"][0] / (roi[2] - roi[0])
                        want_diag = bool(time.monotonic() < self._diagnostic_until and
                            time.monotonic() >= self._diagnostic_next_due and
                            (self._diagnostic_future is None or self._diagnostic_future.done()))
                        try:
                            datum = (active.get("vertical_reference") if active else
                                     resolve_vertical_reference(config, association))
                            reading = detect_interface(transformed, config, roi, density,
                                                       diagnostics=want_diag, vertical_reference=datum)
                        except Exception as error:
                            reading = {"valid": False, "error": str(error),
                                       "froth_surface_cm": None, "pulp_froth_interface_cm": None,
                                       "froth_thickness_cm": None}
                        diagnostic = reading.pop("_diagnostics", None)
                        if diagnostic and want_diag:
                            self._diagnostic_next_due = time.monotonic() + 5.0
                            diagnostic_reading = {**reading, "_diagnostics": diagnostic}
                            self._diagnostic_future = self._diagnostic_executor.submit(
                                build_interface_diagnostic, transformed, diagnostic_reading,
                                list(roi), frame["captured_timestamp_ns"])
                            self._diagnostic_future.add_done_callback(self._store_diagnostic)
                        reading.update({"timestamp_ns": frame["captured_timestamp_ns"],
                                        "sensor_timestamp_ns": frame.get("sensor_timestamp_ns"),
                                        "camera_id": camera.id, "cell_id": cell_id,
                                        "calibration_id": association["calibration_id"]})
                        self._virtual_sample_count += 1
                        reading["sample_count"] = self._virtual_sample_count
                        self._last_virtual_measurement = reading
                        self._write_virtual_sample(active, reading, frame)
                        now_monitor = time.monotonic()
                        if (now_monitor < self._monitor_until and now_monitor >= self._monitor_next_due and
                            (self._monitor_future is None or self._monitor_future.done())):
                            self._monitor_next_due = now_monitor + 5.
                            # Copy one existing processed ROI at low frequency; never acquire again.
                            self._monitor_future = self._diagnostic_executor.submit(
                                encode_monitor_frame, transformed.copy(), dict(reading),
                                frame["captured_timestamp_ns"], self._monitor_width)
                            self._monitor_future.add_done_callback(self._store_monitor)
                        status["virtual_sensor"] = {"valid": reading["valid"],
                                                    "pulp_froth_interface_cm": reading.get("pulp_froth_interface_cm"),
                                                    "froth_surface_cm": reading.get("froth_surface_cm"),
                                                    "error": reading.get("error")}
                else:
                    layout = self.registry.get_cell(cell_id)["marker_layout"] if cell_id else None
                    detected = detect_markers(image, (layout or {}).get("dictionary", "DICT_4X4_50"),
                                              self.registry.camera_profile(camera.id)["invert"])
                    status.update({"roi_processed": False, "markers_detected": sorted(detected)})
                status["processing_ms"] = round((time.perf_counter() - started) * 1000, 2)
                status["deadline_met"] = status["processing_ms"] <= interval * 1000
                self._latest = status
                if active is not None and association is not None:
                    directory = self.digiflot.run_directory
                    if directory is not None and str(directory) not in self._seen_runs:
                        _write(Path(directory) / "vision_calibration_snapshot.json", association)
                        self._seen_runs.add(str(directory))
            except Exception as error:
                self._latest = {"state": "error", "error": str(error), "updated_at": _utc()}

    def _store_monitor(self, future):
        try:
            rendered = future.result()
            with self._lock:
                self._monitor_revision += 1
                self._monitor_latest = {**rendered, "revision": self._monitor_revision}
                self._monitor_error = None
        except Exception as error:
            with self._lock:
                self._monitor_error = str(error)

    def monitor_preview(self, requested_width=320, last_revision=0):
        """Renew a short-lived subscriber lease; return JPEG only for changed frames."""
        if self.digiflot.state not in (self.digiflot.READY, self.digiflot.RUNNING,
                                      self.digiflot.PAUSED, self.digiflot.COMPLETED):
            return {"enabled": False, "revision": self._monitor_revision}
        if self.digiflot.virtual_camera_id is None:
            return {"enabled": False, "revision": self._monitor_revision}
        width = max(96, min(512, int(requested_width)))
        bucket = next((size for size in (192, 256, 384, 512) if size >= width), 512)
        with self._lock:
            if bucket != self._monitor_width:
                self._monitor_width = bucket
                self._monitor_next_due = 0.
            self._monitor_until = time.monotonic() + 12.
            latest = self._monitor_latest
            if latest is not None and int(last_revision or 0) != self._monitor_revision:
                return {"enabled": True, "interval_s": 5,
                        "revision": self._monitor_revision, "frame": deepcopy(latest)}
            return {"enabled": True, "interval_s": 5, "revision": self._monitor_revision,
                    "error": self._monitor_error}

    def _store_diagnostic(self, future):
        try:
            result = future.result()
            if result is not None:
                with self._lock:
                    self._diagnostic_revision += 1
                    self._diagnostic_latest = {**result, "revision": self._diagnostic_revision}
                    self._diagnostic_error = None
        except Exception as error:
            # Optional UI rendering must never mark the real sensor as failed.
            with self._lock:
                self._diagnostic_error = str(error)

    def diagnostic_preview(self, enabled=True, last_revision=0, owner_id=None):
        """Renew a calibration lease without controlling another tab's camera."""
        if owner_id and self.digiflot.preview_owner_id and owner_id != self.digiflot.preview_owner_id:
            if time.monotonic() < self.digiflot.preview_owner_until:
                if enabled:
                    raise RuntimeError("Camera preview belongs to another browser tab; close it there before opening diagnostics.")
                return {"enabled": False, "revision": self._diagnostic_revision}
        if enabled and self.digiflot.state != self.digiflot.SENSOR_CALIBRATION:
            raise RuntimeError("Diagnostic preview is only available while calibrating sensors")
        if enabled:
            self._virtual_context()  # Reject an uncalibrated camera-cell association.
        with self._lock:
            self._diagnostic_until = time.monotonic() + 12.0 if enabled else 0.0
            if not enabled:
                return {"enabled": False, "revision": self._diagnostic_revision}
            snapshot = self._diagnostic_latest
            if snapshot is not None and int(last_revision or 0) != self._diagnostic_revision:
                return {"enabled": True, "interval_s": 5, "diagnostic": deepcopy(snapshot),
                        "revision": self._diagnostic_revision, "error": self._diagnostic_error}
            return {"enabled": True, "interval_s": 5, "revision": self._diagnostic_revision,
                    "error": self._diagnostic_error}

    def _virtual_context(self):
        camera_id = self.digiflot.virtual_camera_id
        cell_id = (self.digiflot.cell_profile or {}).get("physical_cell_id")
        if camera_id is None or not cell_id:
            raise ValueError("Select a physical cell and source camera first")
        camera = self.digiflot.get_camera(int(camera_id))
        association = self.registry.association(camera.id, cell_id)
        if association is not None and (association["cell_revision"] != self.registry.get_cell(cell_id)["revision"]
                or association["camera_revision"] != self.registry.camera_profile(camera.id)["revision"]):
            raise ValueError("Camera or cell geometry changed; recalibrate ArUco and select ROI again")
        if association is None:
            raise ValueError("Confirm ArUco geometry in Cells before setting a Detection ROI")
        profile = self.registry.virtual_profile(camera.id, cell_id)
        return camera, cell_id, association, profile

    def virtual_profile(self):
        camera, cell_id, assoc, profile = self._virtual_context()
        try:
            resolved = resolve_vertical_reference(profile["config"], assoc)
            error = None
        except ValueError as exc:
            resolved, error = None, str(exc)
        named = self.registry.reference_points(cell_id)
        ref_selected = profile["config"].get("reference_id") or named.get("default_reference_id")
        lines = []
        for point in named.get("points", []):
            try:
                datum = resolve_vertical_reference({"reference_id": point["id"]}, assoc)
                physical_y, warning = datum["y_cm"], None
            except (ValueError, KeyError, TypeError) as exc:
                physical_y, warning = None, str(exc)
            lines.append({"id": point["id"], "name": point["name"], "type": point["type"],
                          "y_cm": physical_y, "selected": point["id"] == ref_selected,
                          "error": warning})
        return {**profile, "cell_vertical_reference": self.registry.cell_vertical_reference(cell_id),
                "named_references": named, "reference_lines": lines,
                "reference_resolved": resolved, "reference_error": error,
                "geometry": {"calibration_id": assoc["calibration_id"],
                                        "analysis_roi_cm": assoc.get("analysis_roi_cm"),
                                        "analysis_roi_revision": assoc.get("analysis_roi_revision"),
                                        "detection_roi_cm": profile["config"].get("detection_roi_cm") or assoc.get("analysis_roi_cm")},
                "camera_name": camera.name, "test": self.virtual_test_result(include_series=True),
                "test_diagnostic": deepcopy(self._benchmark_diagnostic) if self.virtual_test_passed() else None}

    def save_virtual_profile(self, values):
        if self.digiflot.state != self.digiflot.SENSOR_CALIBRATION:
            raise RuntimeError("Configure the virtual sensor during the sensor calibration stage")
        camera, cell_id, association, _ = self._virtual_context()
        if camera.recording:
            raise RuntimeError("Stop recording before updating the virtual sensor")
        proposed = normalized_config(values)
        if proposed["vertical_reference_confirmed"]:
            resolve_vertical_reference(proposed, association)
        result = self.registry.save_virtual_profile(camera.id, cell_id, proposed)
        self.clear_virtual_test()
        with self.digiflot.lock:
            self.digiflot._mark_calibration_changed_unlocked("sensor", "froth_interface")
            item = self.digiflot.sensor_calibration.get("froth_interface")
            if item is not None:
                item["status"] = "pending"
                item["confirmed_at"] = None
                item.pop("benchmark", None)
                self.digiflot._touch_unlocked("VIRTUAL_SENSOR_PROFILE_UPDATED",
                                              {"sensor_id": "froth_interface", "revision": result["revision"]})
        return result

    def clear_virtual_test(self):
        self._virtual_test = None
        self._benchmark_series = []
        self._benchmark_diagnostic = None
        with self._lock:
            self._diagnostic_latest = None
            self._diagnostic_error = None
            self._diagnostic_next_due = 0.

    def _virtual_signature(self):
        camera, cell_id, assoc, profile = self._virtual_context()
        camera_geometry = {
            "frame_size": list(camera.frame_size), "crop_region": list(camera.crop_region or []),
            "format": camera.format, "fps": camera.frame_rate,
            "exposure_time_us": camera.exposure_time_us,
            "analogue_gain": camera.analogue_gain,
            "target_size": list(camera.analysis_target_size or []),
        }
        return config_signature(profile["config"], assoc, camera_geometry)

    def virtual_test_passed(self):
        try:
            result = self._virtual_test
            return bool(result and result.get("passed") and result["signature"] == self._virtual_signature())
        except (ValueError, KeyError, RuntimeError):
            return False

    def virtual_test_result(self, include_series=False):
        result = deepcopy(self._virtual_test) if self._virtual_test else None
        if result is not None:
            result.pop("signature", None)
            result["current"] = self.virtual_test_passed()
            if include_series and result["current"]:
                result["series"] = deepcopy(self._benchmark_series)
        return result

    def virtual_sensor_snapshot(self):
        camera_id = self.digiflot.virtual_camera_id
        cell_id = (self.digiflot.cell_profile or {}).get("physical_cell_id")
        camera = self.digiflot.cameras.get(int(camera_id)) if camera_id is not None else None
        reading = self._last_virtual_measurement or {}
        test = self.virtual_test_result()
        active_state = self.digiflot.state in (self.digiflot.SENSOR_CALIBRATION, self.digiflot.READY,
                                                self.digiflot.RUNNING, self.digiflot.PAUSED,
                                                self.digiflot.COMPLETED)
        timestamp = reading.get("timestamp_ns")
        age_s = (time.time_ns() - int(timestamp)) / 1e9 if timestamp else None
        current = bool(active_state and timestamp and str(reading.get("camera_id")) == str(camera_id)
                       and str(reading.get("cell_id")) == str(cell_id)
                       and age_s is not None and age_s < 10)
        valid = bool(reading.get("valid")) if current else None
        live_mode = ("experiment" if self.digiflot.state in (self.digiflot.RUNNING, self.digiflot.PAUSED)
                     else "preview")
        return {"id": "froth_interface", "name": "Froth Interface",
                "type": "virtual_froth_interface", "virtual": True,
                "source_camera_id": camera_id, "physical_cell_id": cell_id,
                "status": "connected" if camera else "offline",
                "value": reading.get("froth_thickness_cm") if valid else None,
                "unit": "cm", "decimals": 2,
                "channels": {key: reading.get(key) for key in
                             ("froth_surface_cm", "pulp_froth_interface_cm", "froth_thickness_cm")} if current else None,
                "reading_valid": valid,
                "measurement_mode": live_mode if current else "waiting",
                "timestamp_ms": int(timestamp / 1e6) if current else None,
                "sample_count": reading.get("sample_count", 0) if current else 0,
                "revision": reading.get("sample_count", 0) if current else 0,
                "benchmark": test,
                "error": (reading.get("error") or ("No valid interface detected" if valid is False else None))
                         if current else (None if camera else "Source camera is unavailable")}

    def _desired_lores_size(self, camera, association, config):
        roi = detection_roi(config, association)
        x0, y0, x1, y1 = roi
        corners = np.asarray([[x0,y0],[x1,y0],[x1,y1],[x0,y1]], np.float32)
        cal = association["calibration"]
        coords = (corners - np.asarray(cal["min_xy_cm"], np.float32)) * float(cal["px_per_cm"])
        native = source_geometry(camera.frame_size, camera.crop_region or camera.full_sensor_crop())
        mapped = project_rectified(coords, cal, association["camera_profile"], native)
        roi_width = float(np.max(mapped[:,0])-np.min(mapped[:,0]))
        fraction = max(.03, min(1., roi_width / native["size"][0]))
        target = max(64, int(config["resolution_px"]))
        full_width = max(2, int(camera.frame_size[0]))
        width = min(full_width, max(128, int(np.ceil(target / fraction))))
        width = width + width % 2
        width = min(full_width - full_width%2, width)
        height = max(2, int(round(width * camera.frame_size[1] / full_width / 2)) * 2)
        height = min(int(camera.frame_size[1])//2*2, height)
        return width, height

    def performance_workload(self):
        """Resolve the saved virtual sensor for the idle, two-camera hardware benchmark."""
        settings = self.registry.settings()
        camera_id, cell_id = settings.get("camera_id"), settings.get("cell_id")
        if camera_id is None or not cell_id:
            return None
        camera = self.digiflot.cameras.get(int(camera_id))
        if camera is None:
            raise ValueError("Saved virtual sensor camera is not connected")
        assoc = self.registry.association(camera.id, cell_id)
        if assoc is None:
            raise ValueError("No calibrated ArUco camera-cell association for the saved virtual sensor")
        if (assoc["cell_revision"] != self.registry.get_cell(cell_id)["revision"] or
                assoc["camera_revision"] != self.registry.camera_profile(camera.id)["revision"]):
            raise ValueError("Saved Froth Interface ArUco geometry is out of date")
        profile = self.registry.virtual_profile(camera.id, cell_id)
        config = normalized_config(profile["config"])
        if not config["vertical_reference_confirmed"]:
            raise ValueError("Froth Interface physical reference is not confirmed")
        datum = resolve_vertical_reference(config, assoc)
        roi = detection_roi(config, assoc)
        signature = config_signature(config, assoc)
        return {"camera_id": camera.id, "cell_id": cell_id, "camera": camera,
                "association": assoc, "config": config, "datum": datum, "roi": roi,
                "signature": signature, "lores_size": self._desired_lores_size(camera, assoc, config)}

    def performance_detection(self, workload):
        """One real sensor acquisition with the two encoders already recording."""
        camera, config = workload["camera"], workload["config"]
        color = config["method"] in COLOR_METHODS
        start = time.perf_counter()
        raw, frame = camera.capture_analysis_frame(grayscale=not color, raw_yuv=color)
        compiled = self._compiled_roi(camera, workload["cell_id"], workload["association"], frame, config)
        patch = remap_yuv420_roi(raw, compiled, frame["size"]) if color else remap_roi(raw, compiled)
        roi = workload["roi"]
        density = compiled["size"][0] / (roi[2] - roi[0])
        result = detect_interface(patch, config, roi, density, vertical_reference=workload["datum"])
        return {"valid": bool(result.get("valid")), "latency_ms": round((time.perf_counter()-start)*1000, 2),
                "captured_timestamp_ns": frame["captured_timestamp_ns"],
                "sensor_timestamp_ns": frame.get("sensor_timestamp_ns"),
                "error": result.get("error")}

    def benchmark_virtual_sensor(self, samples=20):
        if self.digiflot.state != self.digiflot.SENSOR_CALIBRATION:
            raise RuntimeError("Virtual sensor benchmark is only allowed during sensor calibration")
        camera, cell_id, association, profile = self._virtual_context()
        config = normalized_config(profile["config"])
        if not config["vertical_reference_confirmed"]:
            raise ValueError("Confirm the physical vertical reference before running the calibration test")
        datum = resolve_vertical_reference(config, association)
        if camera.recording:
            raise RuntimeError("Stop recording before testing this sensor")
        planned_size = self._desired_lores_size(camera, association, config)
        camera.analysis_target_size = planned_size
        # Reserve the camera before stopping preview to avoid the live worker
        # racing to restart Picamera2 while the main encoder is being prepared.
        self._benchmarking = True
        try:
            if self.digiflot.preview_camera_id is not None:
                self.digiflot.stop_preview()
            if camera.state != camera.IDLE:
                raise RuntimeError("Source camera must be idle for a representative recording benchmark")
        except Exception:
            self._benchmarking = False
            raise
        self._map_key, self._roi_map = None, None
        interval = float(config["sampling_interval_s"])
        self._benchmark_series, self._benchmark_diagnostic = [], None
        errors, timings, valid_count, sensor_times, test_series = [], [], 0, [], []
        last_reading, last_preview, last_diag, last_stamp = None, None, None, None
        count = max(12, min(60, int(samples)))
        with self.digiflot.lock:
            self.digiflot._mark_calibration_changed_unlocked("sensor", "froth_interface")
        warmup = 3
        original_enabled = camera.analysis_enabled
        camera.analysis_enabled = True
        recording_metrics = {}
        try:
            # Exercise the actual encoder together with lores. Keep the test
            # cadence equal to the user's target acquisition interval.
            with TemporaryDirectory(prefix="digiflot-virtual-benchmark-") as temp_dir:
                camera.start_recording(Path(temp_dir) / "benchmark")
                try:
                    next_sample = time.perf_counter()
                    for index in range(count + warmup):
                        delay = next_sample - time.perf_counter()
                        if delay > 0:
                            time.sleep(delay)
                        next_sample += interval
                        begin = time.perf_counter()
                        sample = None
                        try:
                            color = config["method"] in COLOR_METHODS
                            raw, frame = camera.capture_analysis_frame(grayscale=not color, raw_yuv=color)
                            maps = self._compiled_roi(camera, cell_id, association, frame, config)
                            patch = (remap_yuv420_roi(raw, maps, frame["size"]) if color else remap_roi(raw, maps))
                            roi = detection_roi(config, association)
                            density = maps["size"][0] / (roi[2] - roi[0])
                            is_final = index == count + warmup - 1
                            reading = detect_interface(patch, config, roi, density,
                                                       diagnostics=is_final, vertical_reference=datum)
                            diagnostic = reading.pop("_diagnostics", None)
                            if index >= warmup:
                                valid_count += int(reading["valid"])
                                last_reading, last_preview = dict(reading), patch
                                last_stamp = frame["captured_timestamp_ns"]
                                if diagnostic is not None:
                                    last_diag = diagnostic
                                sample = {"time_s": round((index-warmup)*interval, 3),
                                          "valid": bool(reading["valid"]),
                                          "froth_surface_cm": reading.get("froth_surface_cm"),
                                          "pulp_froth_interface_cm": reading.get("pulp_froth_interface_cm"),
                                          "froth_thickness_cm": reading.get("froth_thickness_cm")}
                                if frame.get("sensor_timestamp_ns") is not None:
                                    sensor_times.append(int(frame["sensor_timestamp_ns"]))
                        except Exception as error:
                            if index >= warmup:
                                errors.append(str(error))
                                sample = {"time_s": round((index-warmup)*interval, 3),
                                          "valid": False, "error": str(error),
                                          "froth_surface_cm": None, "pulp_froth_interface_cm": None,
                                          "froth_thickness_cm": None}
                        if index >= warmup:
                            elapsed_ms = (time.perf_counter()-begin)*1000
                            timings.append(elapsed_ms)
                            test_series.append({**sample, "latency_ms": round(elapsed_ms, 2)})
                    recording_metrics = camera.recording_metrics()
                finally:
                    camera.stop_recording()
        finally:
            camera.analysis_enabled = original_enabled
            self._benchmarking = False
        if not timings:
            raise RuntimeError("Unable to sample the detector")
        p95, p99 = np.percentile(timings, [95, 99])
        valid_fraction = valid_count / count
        unique_frames = len(set(sensor_times))
        unique_ok = not sensor_times or unique_frames == len(sensor_times)
        main_fps = float(recording_metrics.get("actual_fps") or 0)
        required_fps = .85 * float(camera.frame_rate)
        encoder_ok = main_fps >= required_fps
        passed = bool(valid_fraction >= .7 and p95 <= .70 * interval * 1000
                      and p99 < interval * 1000 and unique_ok and encoder_ok)
        result = {
            "passed": passed, "samples": count, "warmup_samples": warmup,
            "valid_fraction": round(valid_fraction, 3),
            "p95_ms": round(float(p95), 2), "p99_ms": round(float(p99), 2),
            "mean_ms": round(float(np.mean(timings)), 2), "max_ms": round(max(timings), 2),
            "deadline_ms": round(interval * 1000, 2),
            "lores_size": list(planned_size),
            "roi_resolution": list((self._roi_map or {"size": [0, 0]})["size"]),
            "roi_coverage": (self._roi_map or {"coverage": 0})["coverage"],
            "main_recording_fps": round(main_fps, 2),
            "min_recording_fps": round(required_fps, 2),
            "unique_sensor_frames": unique_frames if sensor_times else None,
            "frame_reuse_detected": not unique_ok,
            "method": config["method"], "errors": errors[:5], "tested_at": _utc(),
            "mode": "paced_main_encoder_and_lores",
        }
        result["signature"] = self._virtual_signature()
        self._benchmark_series = test_series
        result["series"] = deepcopy(test_series)
        if last_diag is not None and last_preview is not None and last_reading is not None:
            try:
                self._benchmark_diagnostic = build_interface_diagnostic(
                    last_preview, {**last_reading, "_diagnostics": last_diag},
                    detection_roi(config, association), last_stamp)
                result["diagnostic"] = self._benchmark_diagnostic
            except Exception as error:
                result["diagnostic_error"] = str(error)
        if last_preview is not None and last_reading:
            preview = (cv2.cvtColor(last_preview, cv2.COLOR_GRAY2BGR) if last_preview.ndim == 2
                       else last_preview.copy())
            for key, color in [("froth_surface_row_px", (220, 220, 30)),
                               ("pulp_froth_row_px", (10, 110, 255))]:
                y = last_reading.get(key)
                if y is not None:
                    cv2.line(preview, (0, int(y)), (preview.shape[1]-1, int(y)), color, 2)
            result["preview_jpeg_base64"] = _jpeg_base64(preview)
            result["last_reading"] = last_reading
        # Keep huge preview out of in-memory calibration state / runtime snapshots.
        self._virtual_test = {k:v for k,v in result.items()
                              if k not in {"preview_jpeg_base64","last_reading","series","diagnostic"}}
        return result

    def freeze_run_config(self, directory):
        """Write the validated sensor + geometry snapshot before acquisition."""
        if not self.virtual_test_passed():
            raise RuntimeError("Virtual sensor test expired; recalibrate before starting")
        camera, cell_id, association, profile = self._virtual_context()
        config = deepcopy(profile["config"])
        camera.analysis_target_size = self._desired_lores_size(camera, association, config)
        self.registry.save_settings({"camera_id": camera.id, "cell_id": cell_id,
                                     "enabled": True, "sampling_interval_s": config["sampling_interval_s"]})
        self._sync_camera_flags()
        datum = resolve_vertical_reference(config, association)
        snapshot = {"schema_version": 2, "sensor_id": "froth_interface",
                    "camera_id": camera.id, "cell_id": cell_id,
                    "vertical_reference": deepcopy(datum),
                    "association": deepcopy(association), "profile": deepcopy(profile),
                    "config": config, "benchmark": self.virtual_test_result(),
                    "lores_size": list(camera.analysis_target_size), "frozen_at": _utc()}
        directory = Path(directory)
        # Cell reference can be refined after the physical cell was selected.
        # Freeze its most recent definition alongside the exact sensor datum.
        _write(directory / "physical_cell_snapshot.json", self.registry.get_cell(cell_id))
        _write(directory / "virtual_sensors" / "froth_interface.json", snapshot)
        self._virtual_sample_count = 0
        self._last_virtual_measurement = None
        self._run_virtual = {"camera_id": camera.id, "config": config,
                             "vertical_reference": deepcopy(datum),
                             "association": deepcopy(association),
                             "cell_id": cell_id, "directory": str(directory)}
        return snapshot

    def restore_run_config(self, directory):
        """Restore the exact frozen virtual configuration after a run interruption.

        Do not consult or overwrite the newer camera-cell profile: the original
        experiment snapshot is authoritative for resumed and offline processing.
        """
        directory = Path(directory)
        path = directory / "virtual_sensors" / "froth_interface.json"
        if not path.is_file():
            self.disable_run_sensor()
            return False
        snapshot = json.loads(path.read_text(encoding="utf-8"))
        original = snapshot["config"]
        # Preserve the exact previous +offset convention for historical runs.
        if "vertical_reference_mode" not in original:
            original = {**original, "vertical_reference_mode": "historical_offset",
                        "vertical_reference_confirmed": True,
                        "height_reference_offset_cm": original.get("height_reference_offset_cm", 0.)}
        config = normalized_config(original)
        camera_id, cell_id = int(snapshot["camera_id"]), str(snapshot["cell_id"])
        camera = self.digiflot.cameras.get(camera_id)
        if camera is not None:
            camera.analysis_target_size = tuple(snapshot["lores_size"])
        self.registry.save_settings({"camera_id": camera_id, "cell_id": cell_id,
                                     "enabled": True, "sampling_interval_s": config["sampling_interval_s"]})
        self._sync_camera_flags()
        self._run_virtual = {"camera_id": camera_id, "config": config,
                             "vertical_reference": deepcopy(snapshot.get("vertical_reference") or
                                  resolve_vertical_reference(config, snapshot["association"])),
                             "association": deepcopy(snapshot["association"]),
                             "cell_id": cell_id, "directory": str(directory)}
        self._map_key, self._roi_map = None, None
        return True

    def disable_run_sensor(self):
        self._run_virtual = None
        self._virtual_sample_count = 0
        self._last_virtual_measurement = None
        with self._lock:
            self._monitor_until = 0.
            self._monitor_latest = None
            self._monitor_revision += 1
        settings = self.registry.settings()
        if settings["enabled"]:
            self.registry.save_settings({"enabled": False})
            self._sync_camera_flags()

    def _write_virtual_sample(self, active, reading, frame):
        if active is None or self.digiflot.state not in (self.digiflot.RUNNING, self.digiflot.PAUSED):
            return
        import csv
        directory = Path(active["directory"])
        if self.digiflot.run_directory is None or Path(self.digiflot.run_directory) != directory:
            return
        path = directory / "sensors" / "froth_interface.tsv"
        path.parent.mkdir(parents=True, exist_ok=True)
        header = ["timestamp_ns","sensor_timestamp_ns","run_elapsed_s","stage_id",
                  "stage_attempt","sensor","value","unit","valid","calibration_id"]
        elapsed = (frame["captured_monotonic_ns"]/1e9 - self.digiflot.run_started_monotonic
                   if self.digiflot.run_started_monotonic else "")
        stage = self.digiflot.current_stage
        shared = {"timestamp_ns": frame["captured_timestamp_ns"],
                  "sensor_timestamp_ns": frame.get("sensor_timestamp_ns") or "",
                  "run_elapsed_s": elapsed, "stage_id": (stage or {}).get("id",""),
                  "stage_attempt": self.digiflot.stage_attempt or "",
                  "unit": "cm", "valid": reading["valid"],
                  "calibration_id": reading["calibration_id"]}
        with path.open("a", encoding="utf-8", newline="") as output:
            writer = csv.DictWriter(output, fieldnames=header, delimiter="\t")
            if path.stat().st_size == 0:
                writer.writeheader()
            for key in ("froth_surface_cm","pulp_froth_interface_cm","froth_thickness_cm"):
                writer.writerow({**shared, "sensor": key,
                                 "value": reading.get(key) if reading.get(key) is not None else ""})

    def status(self):
        return {"settings": self.registry.settings(), "latest": deepcopy(self._latest),
                "cameras": self.digiflot.camera_summaries(), "cells": self.registry.list_cells()}

    def save_settings(self, values):
        with self._lock:
            if self.digiflot.execution_locked or self.digiflot.recording:
                raise RuntimeError("Vision configuration cannot change during an experiment")
            if any(c.state == c.RECORDING for c in self.digiflot.cameras.values()):
                raise RuntimeError("Stop recording before editing vision settings")
            if values.get("camera_id") is not None and int(values["camera_id"]) not in self.digiflot.cameras:
                raise ValueError("Camera is not configured")
            if values.get("cell_id") is not None:
                self.registry.get_cell(values["cell_id"])
            result = self.registry.save_settings(values)
            self._sync_camera_flags()
            return result

    def save_cell(self, values):
        if self.digiflot.execution_locked or self.digiflot.recording:
            raise RuntimeError("Cell definitions cannot change during an experiment")
        record = self.registry.save_cell(values)
        with self.digiflot.lock:
            if str((self.digiflot.cell_profile or {}).get("physical_cell_id")) == str(record["id"]):
                self.clear_virtual_test()
                self.digiflot._invalidate_virtual_calibration_unlocked("Physical cell definition updated")
        return record

    def save_cell_vertical_reference(self, cell_id, values):
        if self.digiflot.execution_locked or self.digiflot.recording:
            raise RuntimeError("Cell vertical reference cannot change during an active run")
        before = self.registry.cell_vertical_reference(cell_id)
        result = self.registry.save_cell_vertical_reference(cell_id, values)
        if result["revision"] != before["revision"]:
            self.clear_virtual_test()
            with self.digiflot.lock:
                if str((self.digiflot.cell_profile or {}).get("physical_cell_id")) == str(cell_id):
                    self.digiflot._invalidate_virtual_calibration_unlocked("Cell vertical reference updated")
        return result

    def save_reference_points(self, cell_id, values):
        """Edit physical named points while cameras are not recording."""
        if self.digiflot.execution_locked or self.digiflot.recording:
            raise RuntimeError("Reference points cannot change during a running experiment")
        before = self.registry.reference_points(cell_id)
        result = self.registry.save_reference_points(cell_id, values)
        if result.get("revision") != before.get("revision"):
            self.clear_virtual_test()
            with self.digiflot.lock:
                if str((self.digiflot.cell_profile or {}).get("physical_cell_id")) == str(cell_id):
                    self.digiflot._invalidate_virtual_calibration_unlocked("Named physical references updated")
        return result

    def camera_profile(self, camera_id):
        camera = self.digiflot.get_camera(int(camera_id))
        profile = self.registry.camera_profile(camera.id)
        profile["sensor_size"] = list(camera.picam2.sensor_resolution)
        return profile

    def save_camera_profile(self, camera_id, values):
        if self.digiflot.execution_locked or self.digiflot.recording:
            raise RuntimeError("Camera calibration cannot change during an experiment")
        camera = self.digiflot.get_camera(int(camera_id))
        values = dict(values or {})
        values["sensor_size"] = list(camera.picam2.sensor_resolution)
        before = self.registry.camera_profile(camera.id)
        result = self.registry.save_camera_profile(camera.id, values)
        if result["revision"] != before["revision"]:
            with self.digiflot.lock:
                self.digiflot._mark_calibration_changed_unlocked("camera", camera.id)
                if (str(self.digiflot.virtual_camera_id) == str(camera.id)
                        and (self.digiflot.cell_profile or {}).get("physical_cell_id")):
                    self.clear_virtual_test()
                    self.digiflot._invalidate_virtual_calibration_unlocked("Camera optical profile updated")
        return result

    def save_analysis_roi(self, camera_id, cell_id, values):
        if self.digiflot.execution_locked or self.digiflot.recording:
            raise RuntimeError("Analysis ROI cannot change during an experiment")
        if any(cam.state == cam.RECORDING for cam in self.digiflot.cameras.values()):
            raise RuntimeError("Stop recording before editing the analysis ROI")
        if not isinstance(values, dict) or "roi_cm" not in values:
            raise ValueError("Provide roi_cm (or null to clear the ROI)")
        before = self.registry.analysis_roi(camera_id, cell_id)
        result = self.registry.save_analysis_roi(camera_id, cell_id, values["roi_cm"])
        self._map_key, self._roi_map = None, None
        if result["revision"] != before["revision"]:
            with self.digiflot.lock:
                if (str(self.digiflot.virtual_camera_id) == str(camera_id)
                        and str((self.digiflot.cell_profile or {}).get("physical_cell_id")) == str(cell_id)):
                    self.clear_virtual_test()
                    self.digiflot._invalidate_virtual_calibration_unlocked("Cells analysis ROI updated")
        return result

    def _capture(self, camera_id):
        camera = self.digiflot.get_camera(int(camera_id))
        return camera.capture_analysis_frame()

    def snapshot(self, camera_id, cell_id=None, show_grid=True):
        image, meta = self._capture(camera_id)
        profile = self.camera_profile(camera_id)
        assoc = self.registry.association(camera_id, cell_id) if cell_id else None
        cal = (assoc or {}).get("calibration") if show_grid else None
        optics_profile = (assoc or {}).get("camera_profile", profile) if cal else profile
        annotated = grid_overlay(image, cal, optics_profile, meta, profile["roi_norm"])
        return {"jpeg_base64": _jpeg_base64(annotated), "size": meta["size"], "frame": meta,
                "calibration_id": (assoc or {}).get("calibration_id")}

    def detect(self, camera_id, cell_id):
        if self.digiflot.execution_locked or self.digiflot.recording:
            raise RuntimeError("Confirm a new calibration while the Edge is not recording")
        cell = self.registry.get_cell(cell_id)
        image, meta = self._capture(camera_id)
        profile = self.camera_profile(camera_id)
        markers = detect_markers(image, cell["marker_layout"]["dictionary"], profile["invert"])
        preview = grid_overlay(image, None, profile, meta, profile["roi_norm"])
        for mid, corners in markers.items():
            poly = np.round(corners).astype(np.int32)
            cv2.polylines(preview, [poly], True, (50, 210, 50), 2)
            cv2.putText(preview, str(mid), tuple(poly[0]), cv2.FONT_HERSHEY_SIMPLEX, .6, (50, 210, 50), 2)
        result = {"detected_ids": sorted(markers), "required_ids": cell["marker_layout"]["marker_ids"],
                  "frame": meta, "candidate_token": None, "candidate": None}
        try:
            candidate = calibrate(image, cell["marker_layout"], profile, meta)
            previous = self.registry.association(camera_id, cell_id)
            if previous is not None:
                result["previous_calibration_id"] = previous["calibration_id"]
            preview = grid_overlay(preview, candidate, profile, meta, profile["roi_norm"])
            token = uuid4().hex
            with self._lock:
                self._pending = {token: {"camera_id": str(camera_id), "cell_id": str(cell_id),
                                         "camera_revision": profile["revision"], "cell_revision": cell["revision"],
                                         "candidate": candidate, "created": time.monotonic()}}
            result["candidate_token"] = token
            result["candidate"] = {"rms_px": candidate["rms_px"], "max_err_px": candidate["max_err_px"],
                                   "size": candidate["size"], "px_per_cm": candidate["px_per_cm"]}
        except (ValueError, cv2.error) as error:
            result["error"] = str(error)
        result["jpeg_base64"] = _jpeg_base64(preview)
        return result

    def confirm(self, camera_id, cell_id, token):
        if self.digiflot.execution_locked or self.digiflot.recording:
            raise RuntimeError("Calibration cannot be confirmed during acquisition")
        with self._lock:
            pending = self._pending.get(token)
            if (pending is None or pending["camera_id"] != str(camera_id) or pending["cell_id"] != str(cell_id)
                    or time.monotonic() - pending["created"] > 300):
                raise ValueError("Calibration candidate expired; detect again")
            self._pending.pop(token, None)
        if (self.registry.camera_profile(camera_id)["revision"] != pending["camera_revision"]
                or self.registry.get_cell(cell_id)["revision"] != pending["cell_revision"]):
            raise ValueError("Camera or cell changed since detection; detect again")
        result = self.registry.save_association(camera_id, cell_id, pending["candidate"])
        with self.digiflot.lock:
            if (str(self.digiflot.virtual_camera_id) == str(camera_id)
                    and str((self.digiflot.cell_profile or {}).get("physical_cell_id")) == str(cell_id)):
                self.clear_virtual_test()
                self.digiflot._invalidate_virtual_calibration_unlocked("ArUco camera-cell association updated")
        return result

    def virtual_detection_roi_preview(self, owner_id=None):
        """One configuration snapshot of the entire calibrated camera plane.

        No detector pass, no full-frame rectification in the acquisition loop.
        Selection is saved to the virtual sensor profile, not to Cells.
        """
        if self.digiflot.state != self.digiflot.SENSOR_CALIBRATION:
            raise RuntimeError("Select the Detection ROI during sensor calibration")
        camera, cell_id, association, _ = self._virtual_context()
        with self.digiflot.lock:
            if self._benchmarking or camera.state == camera.RECORDING:
                raise RuntimeError("Camera is recording a benchmark; retry when the test has finished")
            if self.digiflot.preview_camera_id not in (None, camera.id):
                raise RuntimeError("Close the other camera preview before selecting the Detection ROI")
            # Claim the preview through the same tab lease as physical camera calibration.
            if camera.state in (camera.IDLE, camera.PREVIEW):
                self.digiflot.start_preview(camera.id, owner_id=owner_id)
            else:
                raise RuntimeError("Camera is unavailable for the planar preview")
            result = self.rectified_snapshot(camera.id, cell_id)
        config = self.registry.virtual_profile(camera.id, cell_id)["config"]
        result["detection_roi_cm"] = config.get("detection_roi_cm")
        return result

    def rectified_snapshot(self, camera_id, cell_id):
        association = self.registry.association(camera_id, cell_id)
        if association is None:
            raise ValueError("Calibrate the camera-cell association first")
        image, frame = self._capture(camera_id)
        profile = self.camera_profile(camera_id)
        cal = association["calibration"]
        optics = association.get("camera_profile", profile)
        plane = full_plane_geometry(cal, optics, frame)
        bounds = [*plane["min_xy_cm"], *plane["max_xy_cm"]]
        maps = compile_roi_maps(cal, optics, frame, bounds,
                                px_per_cm=plane["px_per_cm"], output_size=plane["size"],
                                max_pixels=2_000_000)
        rectified = remap_roi(image, maps)
        return {"jpeg_base64": _jpeg_base64(rectified), "size": [rectified.shape[1], rectified.shape[0]],
                "plane": plane, "analysis_roi_cm": association.get("analysis_roi_cm"),
                "calibration_id": association["calibration_id"]}
