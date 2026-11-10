"""Optional Cell Vision subsystem. Never controls recording or experiment state."""
from __future__ import annotations

import base64
import json
import threading
import time
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import cv2
import numpy as np

from .aruco import calibrate, detect_markers, grid_overlay, project_rectified, source_geometry
from .roi import compile_roi_maps, full_plane_geometry, remap_roi, remap_yuv420_roi
from .registry import VisionRegistry, _write
from lib.virtual_sensors.interface import COLOR_METHODS, DEFAULTS, config_signature, detect_interface, normalized_config


def _utc():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _jpeg_base64(image):
    ok, buf = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 85])
    if not ok:
        raise RuntimeError("Could not encode camera image")
    return base64.b64encode(buf).decode("ascii")


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

    def _compiled_roi(self, camera, cell_id, association, frame, config=None):
        roi = association["analysis_roi_cm"]
        key = (str(camera.id), str(cell_id), association["calibration_id"],
               association["analysis_roi_revision"], tuple(frame["size"]), tuple(frame["sensor_crop"]),
               (config or {}).get("resolution_px"))
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

    def _loop(self):
        # No queued frames; acquisition and recording always take priority.
        while not self._stop.wait(max(.2, float((self._run_virtual or {}).get("config", {}).get(
                "sampling_interval_s", self.registry.settings()["sampling_interval_s"])))):
            settings = self.registry.settings()
            active = self._run_virtual
            if not settings["enabled"] or settings["camera_id"] is None:
                continue
            camera = self.digiflot.cameras.get(int(settings["camera_id"]))
            if camera is None or camera.state != camera.RECORDING:
                continue
            try:
                started = time.perf_counter()
                association = (active or {}).get("association")
                cell_id = (active or {}).get("cell_id") or settings.get("cell_id")
                if association is None and cell_id:
                    association = self.registry.association(camera.id, cell_id)
                roi = (association or {}).get("analysis_roi_cm")
                config = (active or {}).get("config")
                color = bool(config and config["method"] in COLOR_METHODS and roi)
                image, frame = camera.capture_analysis_frame(grayscale=not color, raw_yuv=color)
                status = {"state": "running", "camera_id": camera.id, "cell_id": cell_id,
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
                        try:
                            reading = detect_interface(transformed, config, roi, density)
                        except Exception as error:
                            reading = {"valid": False, "error": str(error),
                                       "froth_surface_cm": None, "pulp_froth_interface_cm": None,
                                       "froth_thickness_cm": None}
                        reading.update({"timestamp_ns": frame["captured_timestamp_ns"],
                                        "sensor_timestamp_ns": frame.get("sensor_timestamp_ns"),
                                        "camera_id": camera.id, "cell_id": cell_id,
                                        "calibration_id": association["calibration_id"]})
                        self._last_virtual_measurement = reading
                        self._write_virtual_sample(active, reading, frame)
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
                self._latest = status
                directory = self.digiflot.run_directory
                if directory is not None and association is not None and str(directory) not in self._seen_runs:
                    _write(Path(directory) / "vision_calibration_snapshot.json", association)
                    self._seen_runs.add(str(directory))
            except Exception as error:
                self._latest = {"state": "error", "error": str(error), "updated_at": _utc()}

    def _virtual_context(self):
        camera_id = self.digiflot.virtual_camera_id
        cell_id = (self.digiflot.cell_profile or {}).get("physical_cell_id")
        if camera_id is None or not cell_id:
            raise ValueError("Select a physical cell and source camera first")
        camera = self.digiflot.get_camera(int(camera_id))
        association = self.registry.association(camera.id, cell_id)
        if association is None or not association.get("analysis_roi_cm"):
            raise ValueError("Confirm ArUco geometry and the physical ROI in Cells before testing")
        profile = self.registry.virtual_profile(camera.id, cell_id)
        return camera, cell_id, association, profile

    def virtual_profile(self):
        camera, cell_id, assoc, profile = self._virtual_context()
        return {**profile, "geometry": {"calibration_id": assoc["calibration_id"],
                                        "analysis_roi_cm": assoc["analysis_roi_cm"],
                                        "analysis_roi_revision": assoc["analysis_roi_revision"]},
                "camera_name": camera.name, "test": self.virtual_test_result()}

    def save_virtual_profile(self, values):
        if self.digiflot.state != self.digiflot.SENSOR_CALIBRATION:
            raise RuntimeError("Configure the virtual sensor during the sensor calibration stage")
        camera, cell_id, _, _ = self._virtual_context()
        if camera.recording:
            raise RuntimeError("Stop recording before updating the virtual sensor")
        result = self.registry.save_virtual_profile(camera.id, cell_id, values)
        self.clear_virtual_test()
        return result

    def clear_virtual_test(self):
        self._virtual_test = None

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

    def virtual_test_result(self):
        result = deepcopy(self._virtual_test) if self._virtual_test else None
        if result is not None:
            result.pop("signature", None)
            result["current"] = self.virtual_test_passed()
        return result

    def virtual_sensor_snapshot(self):
        camera_id = self.digiflot.virtual_camera_id
        cell_id = (self.digiflot.cell_profile or {}).get("physical_cell_id")
        camera = self.digiflot.cameras.get(int(camera_id)) if camera_id is not None else None
        reading = self._last_virtual_measurement or {}
        return {"id": "froth_interface", "name": "Froth Interface",
                "type": "virtual_froth_interface", "virtual": True,
                "source_camera_id": camera_id, "physical_cell_id": cell_id,
                "status": "connected" if camera else "offline",
                "value": reading.get("pulp_froth_interface_cm"), "unit": "cm",
                "timestamp_ms": int(reading["timestamp_ns"]/1e6) if reading.get("timestamp_ns") else None,
                "sample_count": reading.get("sample_count", 0), "benchmark": self.virtual_test_result(),
                "error": reading.get("error") if reading else (None if camera else "Source camera is unavailable")}

    def _desired_lores_size(self, camera, association, config):
        roi = association["analysis_roi_cm"]
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

    def benchmark_virtual_sensor(self, samples=20):
        if self.digiflot.state != self.digiflot.SENSOR_CALIBRATION:
            raise RuntimeError("Virtual sensor benchmark is only allowed during sensor calibration")
        camera, cell_id, association, profile = self._virtual_context()
        config = normalized_config(profile["config"])
        if camera.recording:
            raise RuntimeError("Stop recording before testing this sensor")
        planned_size = self._desired_lores_size(camera, association, config)
        camera.analysis_target_size = planned_size
        if self.digiflot.preview_camera_id is not None:
            self.digiflot.stop_preview()
        self.digiflot.start_preview(camera.id)
        if camera.state != camera.PREVIEW:
            raise RuntimeError("Source camera preview is not running")
        self._map_key, self._roi_map = None, None
        interval = float(config["sampling_interval_s"])
        errors, timings, valid_count = [], [], 0
        last_reading, last_preview = None, None
        count = max(12, min(60, int(samples)))
        for index in range(count+3):
            begin = time.perf_counter()
            try:
                color = config["method"] in COLOR_METHODS
                raw, frame = camera.capture_analysis_frame(grayscale=not color, raw_yuv=color)
                maps = self._compiled_roi(camera, cell_id, association, frame, config)
                patch = (remap_yuv420_roi(raw, maps, frame["size"]) if color else remap_roi(raw, maps))
                density = maps["size"][0] / (association["analysis_roi_cm"][2] - association["analysis_roi_cm"][0])
                reading = detect_interface(patch, config, association["analysis_roi_cm"], density)
                if index >= 3:
                    valid_count += int(reading["valid"])
                    last_reading, last_preview = reading, patch
            except Exception as error:
                if index >= 3:
                    errors.append(str(error))
            elapsed_ms = (time.perf_counter() - begin)*1000
            if index >= 3:
                timings.append(elapsed_ms)
            if index < count+2:
                time.sleep(min(.10, interval / 4))
        if not timings:
            raise RuntimeError("Unable to sample the detector")
        p95, p99 = np.percentile(timings, [95, 99])
        valid_fraction = valid_count / count
        passed = bool(valid_fraction >= .7 and p95 <= .70 * interval*1000 and p99 < interval*1000)
        result = {
            "passed": passed, "samples": count, "valid_fraction": round(valid_fraction, 3),
            "p95_ms": round(float(p95), 2), "p99_ms": round(float(p99), 2),
            "mean_ms": round(float(np.mean(timings)), 2), "max_ms": round(max(timings), 2),
            "deadline_ms": round(interval * 1000, 2),
            "lores_size": list(planned_size), "roi_resolution": list(self._roi_map["size"]),
            "roi_coverage": self._roi_map["coverage"], "method": config["method"],
            "errors": errors[:5], "tested_at": _utc(),
            "mode": "preview_pipeline_not_main_encoder_load",
        }
        result["signature"] = self._virtual_signature()
        self._virtual_test = result
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
        self._virtual_test = {k:v for k,v in result.items() if k not in {"preview_jpeg_base64","last_reading"}}
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
        snapshot = {"schema_version": 1, "sensor_id": "froth_interface",
                    "camera_id": camera.id, "cell_id": cell_id,
                    "association": deepcopy(association), "profile": deepcopy(profile),
                    "config": config, "benchmark": self.virtual_test_result(),
                    "lores_size": list(camera.analysis_target_size), "frozen_at": _utc()}
        directory = Path(directory)
        _write(directory / "virtual_sensors" / "froth_interface.json", snapshot)
        self._run_virtual = {"config": config, "association": deepcopy(association),
                             "cell_id": cell_id, "directory": str(directory)}
        return snapshot

    def disable_run_sensor(self):
        self._run_virtual = None
        settings = self.registry.settings()
        if settings["enabled"]:
            self.registry.save_settings({"enabled": False})
            self._sync_camera_flags()

    def _write_virtual_sample(self, active, reading, frame):
        if active is None:
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
            writer = csv.DictWriter(output, fieldnames=header, delimiter="\\t")
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
        return self.registry.save_camera_profile(camera.id, values)

    def save_analysis_roi(self, camera_id, cell_id, values):
        if self.digiflot.execution_locked or self.digiflot.recording:
            raise RuntimeError("Analysis ROI cannot change during an experiment")
        if any(cam.state == cam.RECORDING for cam in self.digiflot.cameras.values()):
            raise RuntimeError("Stop recording before editing the analysis ROI")
        if not isinstance(values, dict) or "roi_cm" not in values:
            raise ValueError("Provide roi_cm (or null to clear the ROI)")
        result = self.registry.save_analysis_roi(camera_id, cell_id, values["roi_cm"])
        self._map_key, self._roi_map = None, None
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
        return self.registry.save_association(camera_id, cell_id, pending["candidate"])

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
