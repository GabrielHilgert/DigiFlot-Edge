"""Persistent, versioned physical cells, camera profiles, and camera-cell associations.

Never overwrite a confirmed association without retaining the previous version.
All data is local and does not require the central Server or an online connection.
"""
from __future__ import annotations

import json
import math
import os
import re
import threading
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from .aruco import DEFAULT_LAYOUT, PRESETS, validate_layout

_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")


def _safe_id(value):
    value = str(value)
    if not _ID.fullmatch(value) or value.startswith(".") or ".." in value:
        raise ValueError("Identifier must contain only letters, digits, _, - or .")
    return value


def _write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        with temporary.open("w", encoding="utf-8") as file:
            json.dump(data, file, indent=2, ensure_ascii=False, allow_nan=False)
            file.write("\n")
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _read(path, default=None):
    try:
        with path.open(encoding="utf-8") as file:
            data = json.load(file)
        return data if isinstance(data, dict) else deepcopy(default)
    except FileNotFoundError:
        return deepcopy(default)


def _positive_optional(value, name):
    if value in (None, ""):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"Invalid {name}") from None
    if not math.isfinite(result) or result <= 0:
        raise ValueError(f"{name} must be positive")
    return result


def _timestamp():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


class VisionRegistry:
    def __init__(self, local_storage_root):
        self.root = Path(local_storage_root) / "vision"
        self.lock = threading.RLock()

    def list_cells(self):
        with self.lock:
            result = []
            for path in sorted((self.root / "cells").glob("*.json")):
                try:
                    record = _read(path)
                    if isinstance(record, dict) and record.get("id"):
                        result.append(record)
                except (OSError, ValueError):
                    continue
            return sorted(result, key=lambda item: str(item.get("name", "")).lower())

    def get_cell(self, cell_id):
        with self.lock:
            cell = _read(self.root / "cells" / f"{_safe_id(cell_id)}.json")
            if cell is None:
                raise KeyError(f"Cell not found: {cell_id}")
            return cell

    def save_cell(self, record):
        if not isinstance(record, dict):
            raise ValueError("Invalid cell")
        ident = _safe_id(record.get("id") or f"cell_{uuid4().hex[:10]}")
        with self.lock:
            path = self.root / "cells" / f"{ident}.json"
            old = _read(path, {})
            name = str(record.get("name", old.get("name", ""))).strip()
            if not name or len(name) > 80:
                raise ValueError("Cell name must contain 1–80 characters")
            volume = _positive_optional(record.get("working_volume_l", old.get("working_volume_l")), "working volume")
            geometry = record.get("geometry", old.get("geometry", {})) or {}
            if not isinstance(geometry, dict):
                raise ValueError("Geometry must be an object")
            if any(not isinstance(key, str) for key in geometry):
                raise ValueError("Invalid geometry field")
            layout = validate_layout(record.get("marker_layout", old.get("marker_layout", DEFAULT_LAYOUT)))
            result = {"schema_version": 1, "id": ident, "name": name, "working_volume_l": volume,
                      "geometry": deepcopy(geometry), "marker_layout": layout,
                      "revision": int(old.get("revision", 0)) + 1, "updated_at": _timestamp()}
            _write(path, result)
            return result

    def camera_profile(self, camera_id):
        with self.lock:
            ident = _safe_id(camera_id)
            record = _read(self.root / "cameras" / f"{ident}.json", {})
            return {"camera_id": ident, "roi_norm": [0, 0, 1, 1], "invert": False,
                    "optics": {"mode": "none"}, "revision": 0, **record}

    def save_camera_profile(self, camera_id, fields):
        if not isinstance(fields, dict):
            raise ValueError("Invalid camera profile")
        with self.lock:
            current = self.camera_profile(camera_id)
            optics = deepcopy(fields.get("optics", current["optics"]))
            if not isinstance(optics, dict) or optics.get("mode", "none") not in ("none", "preset", "custom"):
                raise ValueError("Invalid optics")
            if optics.get("mode") == "preset" and optics.get("preset") not in PRESETS:
                raise ValueError("Unknown lens preset")
            if optics.get("mode") == "custom":
                try:
                    import numpy as np
                    K = np.asarray(optics["K"], float)
                    D = np.asarray(optics["D"], float)
                    size = optics["reference_size"]
                    if K.shape != (3, 3) or D.size not in (4, 5, 8, 12, 14) or min(size) <= 0 or not np.isfinite(K).all() or not np.isfinite(D).all():
                        raise ValueError("Invalid camera intrinsics")
                except (KeyError, TypeError):
                    raise ValueError("Invalid camera intrinsics") from None
            roi = fields.get("roi_norm", current["roi_norm"])
            if not isinstance(roi, (list, tuple)) or len(roi) != 4:
                raise ValueError("ROI must be [x0,y0,x1,y1]")
            try:
                roi = [float(x) for x in roi]
            except (ValueError, TypeError):
                raise ValueError("Invalid ROI coordinates") from None
            if not all(math.isfinite(x) for x in roi) or not (0 <= roi[0] < roi[2] <= 1 and 0 <= roi[1] < roi[3] <= 1):
                raise ValueError("ROI must be inside normalized sensor coordinates")
            result = {"schema_version": 1, "camera_id": current["camera_id"], "roi_norm": roi,
                      "invert": bool(fields.get("invert", current["invert"])), "optics": optics,
                      "sensor_size": fields.get("sensor_size", current.get("sensor_size")),
                      "revision": current["revision"] + 1, "updated_at": _timestamp()}
            _write(self.root / "cameras" / f"{current['camera_id']}.json", result)
            return result

    def association(self, camera_id, cell_id):
        with self.lock:
            _safe_id(camera_id); _safe_id(cell_id)
            return _read(self.root / "associations" / f"{camera_id}__{cell_id}" / "latest.json")

    def save_association(self, camera_id, cell_id, calibration):
        with self.lock:
            cam_id, cell_id = _safe_id(camera_id), _safe_id(cell_id)
            cell = self.get_cell(cell_id)
            profile = self.camera_profile(cam_id)
            if not isinstance(calibration, dict) or not all(k in calibration for k in ("H", "H_inv", "frame", "rms_px")):
                raise ValueError("Invalid calibration data")
            old = self.association(cam_id, cell_id)
            revision = 1 + int((old or {}).get("revision", 0))
            identifier = f"cal_{revision:04d}_{uuid4().hex[:8]}"
            record = {"schema_version": 1, "camera_id": cam_id, "cell_id": cell_id,
                      "calibration_id": identifier, "revision": revision, "created_at": _timestamp(),
                      "camera_revision": profile["revision"], "cell_revision": cell["revision"],
                      "camera_profile": profile, "cell_snapshot": cell, "calibration": calibration}
            folder = self.root / "associations" / f"{cam_id}__{cell_id}"
            _write(folder / "history" / f"{identifier}.json", record)
            _write(folder / "latest.json", record)
            return record

    def settings(self):
        with self.lock:
            return {"camera_id": None, "cell_id": None, "enabled": False, "sampling_interval_s": 1.0,
                    **_read(self.root / "settings.json", {})}

    def save_settings(self, values):
        with self.lock:
            old = self.settings()
            for key in ("camera_id", "cell_id"):
                if key in values:
                    old[key] = _safe_id(values[key]) if values[key] is not None else None
            if "enabled" in values:
                if not isinstance(values["enabled"], bool):
                    raise ValueError("enabled must be a boolean")
                old["enabled"] = values["enabled"]
            if "sampling_interval_s" in values:
                val = _positive_optional(values["sampling_interval_s"], "sampling interval")
                if not 0.2 <= val <= 60:
                    raise ValueError("Sampling interval must be between 0.2 and 60 seconds")
                old["sampling_interval_s"] = val
            _write(self.root / "settings.json", old)
            return old
