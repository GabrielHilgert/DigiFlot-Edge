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

from .aruco import (calibrate, detect_markers, grid_overlay, rectification_maps,
                    source_geometry)
from .registry import VisionRegistry, _write


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

    def _loop(self):
        # Separate from the Camera encoder. No unbounded queue or processing backlog.
        while not self._stop.wait(max(.2, float(self.registry.settings()["sampling_interval_s"]))):
            settings = self.registry.settings()
            if not settings["enabled"] or settings["camera_id"] is None:
                continue
            camera = self.digiflot.cameras.get(int(settings["camera_id"]))
            if camera is None or camera.state != camera.RECORDING:
                continue
            try:
                image, meta = camera.capture_analysis_frame()
                profile = self.registry.camera_profile(camera.id)
                cell_id = settings.get("cell_id")
                layout = self.registry.get_cell(cell_id)["marker_layout"] if cell_id else None
                found = detect_markers(image, (layout or {}).get("dictionary", "DICT_4X4_50"), profile["invert"])
                association = self.registry.association(camera.id, cell_id) if cell_id else None
                self._latest = {"state": "running", "camera_id": camera.id, "cell_id": cell_id,
                                "markers_detected": sorted(found), "associated_calibration": (association or {}).get("calibration_id"),
                                "updated_at": _utc(), "error": None}
                directory = self.digiflot.run_directory
                if directory is not None and association is not None and str(directory) not in self._seen_runs:
                    # A frozen calibration provenance record. No per-frame disk images.
                    _write(Path(directory) / "vision_calibration_snapshot.json", association)
                    self._seen_runs.add(str(directory))
            except Exception as error:
                self._latest = {"state": "error", "error": str(error), "updated_at": _utc()}

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
        map_x, map_y = rectification_maps(cal, association.get("camera_profile", profile), frame)
        rectified = cv2.remap(image, map_x, map_y, cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT)
        return {"jpeg_base64": _jpeg_base64(rectified), "size": [rectified.shape[1], rectified.shape[0]]}
