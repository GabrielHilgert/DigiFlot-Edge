"""Persistent, versioned physical cells, camera profiles, and camera-cell associations.

Never overwrite a confirmed association without retaining the previous version.
All data is local and does not require the central Server or an online connection.
"""
from __future__ import annotations

import hashlib
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
            cell_id = _safe_id(cell_id)
            cell = _read(self.root / "cells" / f"{cell_id}.json")
            if cell is None:
                raise KeyError(f"Cell not found: {cell_id}")
            cell["vertical_reference"] = self.cell_vertical_reference(cell_id)
            cell["reference_points"] = self.reference_points(cell_id)
            return cell

    def cell_vertical_reference(self, cell_id):
        from .reference import normalize_cell_reference
        with self.lock:
            cell_id = _safe_id(cell_id)
            record = _read(self.root / "cell_references" / f"{cell_id}.json", {})
            return {**normalize_cell_reference(record), "revision": int(record.get("revision", 0)),
                    "updated_at": record.get("updated_at")}

    def save_cell_vertical_reference(self, cell_id, values):
        from .reference import normalize_cell_reference
        with self.lock:
            self.get_cell(cell_id)
            current = self.cell_vertical_reference(cell_id)
            updated = normalize_cell_reference(values)
            if all(current.get(key) == value for key, value in updated.items()):
                return current
            result = {**updated, "revision": current["revision"] + 1, "updated_at": _timestamp()}
            _write(self.root / "cell_references" / f"{_safe_id(cell_id)}.json", result)
            return result

    def reference_points(self, cell_id):
        from .reference import default_reference_points
        with self.lock:
            cell_id = _safe_id(cell_id)
            record = _read(self.root / "reference_points" / f"{cell_id}.json")
            if record is not None:
                return record
            # Non-destructive migration of older manually entered top/bottom datums.
            default = default_reference_points()
            legacy = self.cell_vertical_reference(cell_id)
            for kind, key, direction in (("top", "cell_top_y_cm", "down"),
                                         ("bottom", "cell_bottom_y_cm", "up")):
                if legacy.get(key) is not None:
                    default["points"].append({"id": "cell_"+kind, "name": "Cell "+kind,
                        "type": kind, "position_cm": [0., float(legacy[key])],
                        "direction": direction, "source": "measured"})
            return default

    def save_reference_points(self, cell_id, values):
        from .reference import normalize_reference_points
        with self.lock:
            self.get_cell(cell_id)
            current = self.reference_points(cell_id)
            normalized = normalize_reference_points(values)
            if all(current.get(key) == normalized[key] for key in ("points", "default_reference_id")):
                return current
            result = {**normalized, "revision": int(current.get("revision", 0))+1,
                      "updated_at": _timestamp()}
            _write(self.root / "reference_points" / f"{_safe_id(cell_id)}.json", result)
            return result

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

    def analysis_roi(self, camera_id, cell_id):
        """Selection is independent of calibration history and survives recalibration."""
        with self.lock:
            folder = self.root / "associations" / f"{_safe_id(camera_id)}__{_safe_id(cell_id)}"
            return _read(folder / "analysis_roi.json", {"roi_cm": None, "revision": 0})

    def save_analysis_roi(self, camera_id, cell_id, roi_cm):
        with self.lock:
            if self.association(camera_id, cell_id) is None:
                raise KeyError("Confirm the camera-cell calibration before saving an analysis ROI")
            if roi_cm is not None:
                if not isinstance(roi_cm, (list, tuple)) or len(roi_cm) != 4:
                    raise ValueError("Analysis ROI must be [x0_cm,y0_cm,x1_cm,y1_cm]")
                try:
                    roi_cm = [float(v) for v in roi_cm]
                except (ValueError, TypeError):
                    raise ValueError("Invalid analysis ROI coordinates") from None
                if not all(math.isfinite(v) and abs(v) <= 2000 for v in roi_cm):
                    raise ValueError("Analysis ROI coordinates must be finite and within 20 m of the reference")
                if roi_cm[2] <= roi_cm[0] or roi_cm[3] <= roi_cm[1]:
                    raise ValueError("Analysis ROI must have positive width and height")
            current = self.analysis_roi(camera_id, cell_id)
            result = {"schema_version": 1, "roi_cm": roi_cm, "revision": current["revision"] + 1,
                      "updated_at": _timestamp()}
            folder = self.root / "associations" / f"{_safe_id(camera_id)}__{_safe_id(cell_id)}"
            _write(folder / "analysis_roi.json", result)
            return result

    def virtual_profile(self, camera_id, cell_id, sensor_id="froth_interface"):
        from lib.virtual_sensors.interface import DEFAULTS, normalized_config
        with self.lock:
            camera_id, cell_id, sensor_id = _safe_id(camera_id), _safe_id(cell_id), _safe_id(sensor_id)
            path = self.root / "virtual_sensors" / sensor_id / f"{camera_id}__{cell_id}.json"
            saved = _read(path, {})
            return {"sensor_id": sensor_id, "camera_id": camera_id, "cell_id": cell_id,
                    "revision": int(saved.get("revision", 0)),
                    "config": normalized_config(saved.get("config", DEFAULTS)),
                    "updated_at": saved.get("updated_at"), "source": "saved" if saved else "default"}

    def save_virtual_profile(self, camera_id, cell_id, config, sensor_id="froth_interface"):
        from lib.virtual_sensors.interface import normalized_config
        with self.lock:
            camera_id, cell_id, sensor_id = _safe_id(camera_id), _safe_id(cell_id), _safe_id(sensor_id)
            self.get_cell(cell_id)
            if self.association(camera_id, cell_id) is None:
                raise ValueError("A confirmed camera-cell calibration is required")
            normalized = normalized_config(config)
            previous = self.virtual_profile(camera_id, cell_id, sensor_id)
            value = {"schema_version": 1, "sensor_id": sensor_id, "camera_id": camera_id,
                     "cell_id": cell_id, "revision": previous["revision"] + 1,
                     "updated_at": _timestamp(), "config": normalized}
            path = self.root / "virtual_sensors" / sensor_id / f"{camera_id}__{cell_id}.json"
            _write(path, value)
            return {**value, "source": "saved"}

    def successful_virtual_profiles(self, camera_id, cell_id, crop_region, calibration_id,
                                    sensor_id="froth_interface"):
        """Historical passing detector settings for this calibrated camera/crop/cell."""
        from lib.virtual_sensors.interface import normalized_config
        with self.lock:
            folder = self.root / "virtual_sensors" / _safe_id(sensor_id) / "successful"
            camera_id, cell_id = _safe_id(camera_id), _safe_id(cell_id)
            crop = list(crop_region or [])
            results = []
            for path in folder.glob("*.json"):
                try:
                    item = _read(path, {})
                    context = item.get("context") or {}
                    if (context.get("camera_id") != camera_id or context.get("cell_id") != cell_id
                            or context.get("crop_region") != crop
                            or context.get("calibration_id") != calibration_id):
                        continue
                    results.append({"id": path.stem, "tested_at": item.get("tested_at"),
                                    "context": context, "config": normalized_config(item.get("config")),
                                    "reusable": bool(item.get("signature") and (item.get("benchmark") or {}).get("passed"))})
                except (OSError, ValueError, TypeError, KeyError):
                    continue
            return sorted(results, key=lambda item: item.get("tested_at") or "", reverse=True)[:30]

    def remember_successful_virtual_profile(self, camera_id, cell_id, crop_region, calibration_id,
                                             roi_cm, sampling_interval_s, config,
                                             sensor_id="froth_interface", *, signature=None, benchmark=None):
        """Persist only a passing benchmark, never a saved draft or failed test."""
        from lib.virtual_sensors.interface import normalized_config
        with self.lock:
            normalized = normalized_config(config)
            context = {"sensor_id": _safe_id(sensor_id), "camera_id": _safe_id(camera_id),
                       "cell_id": _safe_id(cell_id), "crop_region": list(crop_region or []),
                       "calibration_id": str(calibration_id), "detection_roi_cm": [float(v) for v in roi_cm],
                       "sampling_interval_s": float(sampling_interval_s)}
            payload = json.dumps(context, sort_keys=True, separators=(",", ":"))
            key = hashlib.sha256(payload.encode("utf-8")).hexdigest()
            value = {"schema_version": 2 if signature else 1, "context": context, "tested_at": _timestamp(),
                     "config": normalized}
            if signature:
                value["signature"] = str(signature)
                # Retain measured evidence, not pictures, a full time-series or a draft.
                value["benchmark"] = deepcopy(benchmark or {})
            folder = self.root / "virtual_sensors" / context["sensor_id"] / "successful"
            _write(folder / f"{key}.json", value)
            return {"id": key, **value}

    def matching_successful_virtual_profile(self, camera_id, cell_id, crop_region, calibration_id,
                                           roi_cm, sampling_interval_s, config, signature,
                                           sensor_id="froth_interface"):
        """Return a signed, passing record for exactly these physical and algorithmic conditions."""
        from lib.virtual_sensors.interface import normalized_config
        with self.lock:
            context = {"sensor_id": _safe_id(sensor_id), "camera_id": _safe_id(camera_id),
                       "cell_id": _safe_id(cell_id), "crop_region": list(crop_region or []),
                       "calibration_id": str(calibration_id), "detection_roi_cm": [float(v) for v in roi_cm],
                       "sampling_interval_s": float(sampling_interval_s)}
            key = hashlib.sha256(json.dumps(context, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
            folder = self.root / "virtual_sensors" / context["sensor_id"] / "successful"
            item = _read(folder / f"{key}.json", {})
            if (item.get("schema_version") != 2 or item.get("signature") != signature
                    or item.get("context") != context or not (item.get("benchmark") or {}).get("passed")):
                return None
            try:
                if normalized_config(item.get("config")) != normalized_config(config):
                    return None
            except (TypeError, ValueError, KeyError):
                return None
            return {"id": key, **item}

    def association(self, camera_id, cell_id):
        with self.lock:
            folder = self.root / "associations" / f"{_safe_id(camera_id)}__{_safe_id(cell_id)}"
            record = _read(folder / "latest.json")
            if record is not None:
                selection = self.analysis_roi(camera_id, cell_id)
                record["analysis_roi_cm"] = selection["roi_cm"]
                record["analysis_roi_revision"] = selection["revision"]
                record["cell_vertical_reference"] = self.cell_vertical_reference(cell_id)
                record["reference_points"] = self.reference_points(cell_id)
            return record

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
