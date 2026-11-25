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
        self._successful_match_cache = {}  # Cache disk proofs between live lores frames.

    def list_cells(self, include_archived=False):
        with self.lock:
            result = []
            for path in sorted((self.root / "cells").glob("*.json")):
                try:
                    record = _read(path)
                    if isinstance(record, dict) and record.get("id"):
                        lifecycle = self.cell_lifecycle(record["id"])
                        if lifecycle["archived"] and not include_archived:
                            continue
                        record["archived"] = lifecycle["archived"]
                        record["thumbnail"] = self.thumbnail_info(record["id"])
                        record["reference_points_revision"] = self.reference_points(record["id"]).get("revision", 0)
                        record["vertical_reference_revision"] = self.cell_vertical_reference(record["id"]).get("revision", 0)
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
            cell["reference_points_revision"] = cell["reference_points"].get("revision", 0)
            cell["vertical_reference_revision"] = cell["vertical_reference"].get("revision", 0)
            cell["thumbnail"] = self.thumbnail_info(cell_id)
            cell["archived"] = self.cell_lifecycle(cell_id)["archived"]
            from .cell_metrics import resolve_cell_dimensions
            cell["dimension_measurements"] = self.dimension_measurements(cell_id)
            cell["resolved_dimensions"] = resolve_cell_dimensions(cell, cell["dimension_measurements"])
            relative = self.relative_calibrations_for_cell(cell_id)
            verified = []
            for record in relative:
                source_assoc = self.association(record["source_camera_id"], cell_id)
                source = cell["resolved_dimensions"]["dimensions"].get(record.get("reference_field"))
                current = bool(source_assoc and
                    source_assoc.get("calibration_id") == record.get("source_aruco_calibration_id") and
                    record.get("cell_revision") == cell["revision"] and
                    record.get("camera_revision") == self.camera_profile(record["camera_id"])["revision"] and
                    record.get("reference_points_revision") == cell["reference_points_revision"] and
                    record.get("dimension_revision") == cell["dimension_measurements"]["revision"] and
                    source and abs(source["value_mm"]-record.get("reference_mm", -1)) < .001)
                verified.append({**record, "valid": current})
            cell["relative_measurements"] = verified
            # A relative estimate is lower-confidence than reference-measured or
            # reference-derived dimensions, but is preferred over a nominal fallback.
            estimates = [r for r in verified if r["valid"]]
            if estimates:
                cell["resolved_dimensions"] = resolve_cell_dimensions(
                    cell, cell["dimension_measurements"], relative_estimates=estimates)
            from .cell_metrics import volume_curve_is_current
            cell["volume_calibration"] = self.volume_calibration(cell_id)
            cell["volume_calibration"]["valid"] = volume_curve_is_current(cell, cell["volume_calibration"])
            if cell["volume_calibration"]["valid"]:
                cell["resolved_dimensions"]["effective_area_range_cm2"] = cell["volume_calibration"]["area_range_cm2"]
                cell["resolved_dimensions"]["volume_model"] = "calibrated_volume_curve"
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
        from .reference import default_reference_points, complete_reference_points
        with self.lock:
            cell_id = _safe_id(cell_id)
            record = _read(self.root / "reference_points" / f"{cell_id}.json")
            if record is not None:
                completed = complete_reference_points(record)
                legacy = self.cell_vertical_reference(cell_id)
                for kind, field in (("top", "cell_top_y_cm"), ("bottom", "cell_bottom_y_cm")):
                    item = next(p for p in completed["points"] if p["id"] == "cell_" + kind)
                    if item.get("position_cm") is None and legacy.get(field) is not None:
                        item.update({"position_cm": [0., float(legacy[field])], "source": "measured"})
                return completed
            # Non-destructive migration of older manually entered top/bottom datums.
            default = default_reference_points()
            legacy = self.cell_vertical_reference(cell_id)
            for kind, key, direction in (("top", "cell_top_y_cm", "down"),
                                         ("bottom", "cell_bottom_y_cm", "up")):
                if legacy.get(key) is not None:
                    point = next(p for p in default["points"] if p["id"] == "cell_"+kind)
                    point.update({"position_cm": [0., float(legacy[key])],
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

    def get_cell_base(self, cell_id):
        ident = _safe_id(cell_id)
        cell = _read(self.root / "cells" / f"{ident}.json")
        if cell is None:
            raise KeyError(f"Cell not found: {ident}")
        return cell

    def dimension_measurements(self, cell_id):
        """Reference pairs are independent from nominal geometry and ArUco revisions."""
        with self.lock:
            self.get_cell_base(cell_id)
            return {"revision": 0, "pairs": {},
                    **_read(self.root / "dimension_measurements" / f"{_safe_id(cell_id)}.json", {})}

    def save_dimension_measurements(self, cell_id, values):
        from .cell_metrics import normalize_dimension_pairs
        with self.lock:
            self.get_cell_base(cell_id)
            current = self.dimension_measurements(cell_id)
            expected = (values or {}).get("expected_revision")
            if expected is not None and int(expected) != current["revision"]:
                raise RuntimeError("Dimension mapping was updated in another tab. Reload the cell.")
            pairs = normalize_dimension_pairs(values or {}, self.reference_points(cell_id))
            if pairs == current["pairs"]:
                return current
            record = {"revision": current["revision"] + 1, "pairs": pairs, "updated_at": _timestamp()}
            _write(self.root / "dimension_measurements" / f"{_safe_id(cell_id)}.json", record)
            return record

    def volume_calibration(self, cell_id):
        """Measured fill-volume curve, versioned separately from ArUco geometry."""
        with self.lock:
            self.get_cell_base(cell_id)
            return {"revision": 0, "points": [], "raw_points": [],
                    "datum_reference_id": "cell_bottom", "valid": False,
                    **_read(self.root / "volume_calibrations" / f"{_safe_id(cell_id)}.json", {})}

    def save_volume_calibration(self, cell_id, values):
        from .cell_metrics import normalize_volume_curve
        with self.lock:
            cell = self.get_cell(cell_id)
            current = self.volume_calibration(cell_id)
            expected = (values or {}).get("expected_revision")
            if expected is not None and int(expected) != current["revision"]:
                raise RuntimeError("Volume calibration was updated in another tab. Reload the cell.")
            curve = normalize_volume_curve(cell, values)
            comparable = ("points", "datum_reference_id", "reference_revision",
                          "bottom_y_cm", "datum_y_cm")
            if all(curve.get(key) == current.get(key) for key in comparable):
                return current
            result = {**curve, "revision": current["revision"] + 1, "updated_at": _timestamp()}
            _write(self.root / "volume_calibrations" / f"{_safe_id(cell_id)}.json", result)
            return result

    def relative_calibration(self, camera_id, cell_id):
        """One relative metric estimate per target camera and cell; ArUco stays untouched."""
        with self.lock:
            self.get_cell_base(cell_id)
            return _read(self.root / "relative_calibrations" /
                         f"{_safe_id(camera_id)}__{_safe_id(cell_id)}.json", None)

    def relative_calibrations_for_cell(self, cell_id):
        with self.lock:
            cell_id = _safe_id(cell_id)
            items = []
            for path in (self.root / "relative_calibrations").glob(f"*__{cell_id}.json"):
                try:
                    record = _read(path)
                    if record and record.get("cell_id") == cell_id:
                        items.append(record)
                except (ValueError, OSError):
                    continue
            return items

    def save_relative_calibration(self, camera_id, cell_id, values):
        """No changes to camera profile, reference geometry or saved homographies."""
        from .relative import relative_scale
        with self.lock:
            cell = self.get_cell(cell_id)
            camera_id = _safe_id(camera_id)
            source_id = _safe_id(values.get("source_camera_id"))
            if camera_id == source_id:
                raise ValueError("Source and target must be different cameras")
            source_association = self.association(source_id, cell_id)
            if source_association is None:
                raise ValueError("Calibrate the source camera first or reuse its saved ArUco association")
            if source_association.get("cell_revision") != cell["revision"] or (
                    source_association.get("camera_revision") != self.camera_profile(source_id)["revision"]):
                raise RuntimeError("Source ArUco calibration is outdated. Review its original profile first")
            base = cell["resolved_dimensions"]["dimensions"]
            field = values.get("reference_field")
            known = base.get(field)
            if known is None:
                raise ValueError("Select a known cell dimension from the calibrated source")
            profile = self.camera_profile(camera_id)
            calculated = relative_scale(values, known["value_mm"], profile)
            previous = self.relative_calibration(camera_id, cell_id) or {}
            expected = values.get("expected_revision")
            if expected is not None and int(expected) != int(previous.get("revision", 0)):
                raise RuntimeError("Relative calibration changed in another tab; reload before saving")
            item = {"schema_version": 1, "camera_id": camera_id, "cell_id": _safe_id(cell_id),
                    "source_camera_id": source_id,
                    "source_aruco_calibration_id": source_association["calibration_id"],
                    "cell_revision": cell["revision"],
                    "camera_revision": profile["revision"],
                    "reference_points_revision": cell["reference_points_revision"],
                    "dimension_revision": cell["dimension_measurements"]["revision"],
                    "reference_field": field,
                    "target_field": values["target_field"],
                    "reference_source": known["source"],
                    **calculated, "revision": int(previous.get("revision", 0)) + 1,
                    "updated_at": _timestamp()}
            _write(self.root / "relative_calibrations" /
                   f"{camera_id}__{_safe_id(cell_id)}.json", item)
            return item

    def cell_lifecycle(self, cell_id):
        """Presentation/availability metadata. Never changes the geometrical revision."""
        with self.lock:
            self.get_cell_base(cell_id)
            return {"archived": False,
                    **_read(self.root / "cell_lifecycle" / f"{_safe_id(cell_id)}.json", {})}

    def rename_cell(self, cell_id, name):
        with self.lock:
            original = self.get_cell_base(cell_id)
            new_name = str(name or "").strip()
            if not 1 <= len(new_name) <= 80:
                raise ValueError("Cell name must contain 1–80 characters")
            if new_name == original["name"]:
                return self.get_cell(cell_id)
            updated = {**original, "name": new_name, "renamed_at": _timestamp()}
            # Name-only edits are not physical geometry changes.
            _write(self.root / "cells" / f"{_safe_id(cell_id)}.json", updated)
            return self.get_cell(cell_id)

    def archive_cell(self, cell_id, archived=True):
        with self.lock:
            self.get_cell_base(cell_id)
            current = self.cell_lifecycle(cell_id)
            if bool(current["archived"]) == bool(archived):
                return {"cell_id": cell_id, **current}
            result = {"archived": bool(archived), "updated_at": _timestamp()}
            _write(self.root / "cell_lifecycle" / f"{_safe_id(cell_id)}.json", result)
            return {"cell_id": cell_id, **result}

    def delete_empty_cell(self, cell_id):
        """Permanent deletion is restricted to unreferenced archived draft cells."""
        with self.lock:
            cell_id = _safe_id(cell_id)
            self.get_cell_base(cell_id)
            if not self.cell_lifecycle(cell_id)["archived"]:
                raise RuntimeError("Archive the cell before permanently deleting it.")
            dependent = ["reference_points", "cell_references", "dimension_measurements",
                         "volume_calibrations", "cell_thumbnails"]
            if any((self.root / folder / f"{cell_id}.json").exists() for folder in dependent):
                raise RuntimeError("Cell contains physical measurements or a photo; keep it archived.")
            if self.thumbnail_path(cell_id).exists():
                raise RuntimeError("Cell contains a stored photo; keep it archived.")
            if any((self.root / "associations").glob(f"*__{cell_id}")):
                raise RuntimeError("Cell has camera calibration history; keep it archived.")
            if any((self.root / "relative_calibrations").glob(f"*__{cell_id}.json")):
                raise RuntimeError("Cell has relative camera calibration; keep it archived.")
            if any((self.root / "virtual_sensors").glob(f"*/*__{cell_id}.json")):
                raise RuntimeError("Cell has HIFIE profiles; keep it archived.")
            for path in (self.root / "virtual_sensors").glob("*/successful/*.json"):
                item = _read(path, {})
                if str((item.get("context") or {}).get("cell_id")) == cell_id:
                    raise RuntimeError("Cell has validated HIFIE history; keep it archived.")
            settings = self.settings()
            if cell_id in (str(settings.get("cell_id")), str(settings.get("last_used_cell_id"))):
                raise RuntimeError("Cell is selected or last used by the vision worker; keep it archived.")
            (self.root / "cells" / f"{cell_id}.json").unlink()
            (self.root / "cell_lifecycle" / f"{cell_id}.json").unlink(missing_ok=True)
            return {"deleted": True, "cell_id": cell_id}

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
            comparable = {"name": name, "working_volume_l": volume, "geometry": deepcopy(geometry),
                          "marker_layout": layout}
            if old and all(old.get(key) == value for key, value in comparable.items()):
                return old
            result = {"schema_version": 1, "id": ident, **comparable,
                      "revision": int(old.get("revision", 0)) + 1, "updated_at": _timestamp()}
            _write(path, result)
            return result

    def thumbnail_info(self, cell_id):
        with self.lock:
            return _read(self.root / "cell_thumbnails" / f"{_safe_id(cell_id)}.json", None)

    def thumbnail_path(self, cell_id):
        return self.root / "cell_thumbnails" / f"{_safe_id(cell_id)}.webp"

    def save_thumbnail(self, cell_id, data):
        """Store a compact browser-confirmed photo without touching geometry revisions."""
        with self.lock:
            self.get_cell(cell_id)
            if not isinstance(data, bytes) or not data or len(data) > 180 * 1024:
                raise ValueError("Thumbnail must be a WebP image smaller than 180 KB")
            if data[:4] != b"RIFF" or data[8:12] != b"WEBP":
                raise ValueError("Invalid WebP thumbnail")
            digest = hashlib.sha256(data).hexdigest()
            previous = self.thumbnail_info(cell_id) or {}
            if digest == previous.get("sha256"):
                return previous
            path = self.thumbnail_path(cell_id)
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
            try:
                with temporary.open("wb") as file:
                    file.write(data)
                    file.flush()
                    os.fsync(file.fileno())
                os.replace(temporary, path)
            finally:
                temporary.unlink(missing_ok=True)
            result = {"revision": int(previous.get("revision") or 0) + 1,
                      "sha256": digest, "content_type": "image/webp", "updated_at": _timestamp()}
            _write(path.with_suffix(".json"), result)
            return result

    def delete_thumbnail(self, cell_id):
        with self.lock:
            self.get_cell(cell_id)
            path = self.thumbnail_path(cell_id)
            path.unlink(missing_ok=True)
            path.with_suffix(".json").unlink(missing_ok=True)
            return {"deleted": True}

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

    @staticmethod
    def _successful_virtual_context(camera_id, cell_id, crop_region, roi_cm, sampling_interval_s,
                                    sensor_id="froth_interface"):
        """Stable sensor identity across experiments and ArUco calibration revisions."""
        return {"sensor_id": _safe_id(sensor_id), "camera_id": _safe_id(camera_id),
                "cell_id": _safe_id(cell_id), "crop_region": list(crop_region or []),
                "detection_roi_cm": [float(v) for v in roi_cm],
                "sampling_interval_s": float(sampling_interval_s)}

    def successful_virtual_profiles(self, camera_id, cell_id, crop_region, sensor_id="froth_interface"):
        """Previous passing configurations across all experiments and camera calibrations."""
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
                    if (context.get("sensor_id") != _safe_id(sensor_id)
                            or context.get("camera_id") != camera_id
                            or context.get("cell_id") != cell_id
                            or context.get("crop_region") != crop):
                        continue
                    config = normalized_config(item.get("config"))
                    results.append({"id": path.stem, "tested_at": item.get("tested_at"),
                                    "context": context, "config": config,
                                    "reusable": bool(item.get("signature") and
                                                     (item.get("benchmark") or {}).get("passed"))})
                except (OSError, ValueError, TypeError, KeyError):
                    continue
            return sorted(results, key=lambda item: item.get("tested_at") or "", reverse=True)[:30]

    def remember_successful_virtual_profile(self, camera_id, cell_id, crop_region, calibration_id,
                                             roi_cm, sampling_interval_s, config,
                                             sensor_id="froth_interface", *, signature=None, benchmark=None):
        """Keep the latest passing result PER actual sensor configuration, not per experiment."""
        from lib.virtual_sensors.interface import normalized_config
        with self.lock:
            normalized = normalized_config(config)
            identity = self._successful_virtual_context(camera_id, cell_id, crop_region, roi_cm,
                                                        sampling_interval_s, sensor_id)
            # Calibration ID is useful provenance, but is NOT part of validity:
            # repeated ArUco confirmation does not change the sensor algorithm.
            context = {**identity, "calibration_id": str(calibration_id)}
            payload = json.dumps({"identity": identity, "config": normalized},
                                 sort_keys=True, separators=(",", ":"))
            key = hashlib.sha256(payload.encode("utf-8")).hexdigest()
            value = {"schema_version": 3 if signature else 1, "context": context,
                     "tested_at": _timestamp(), "config": normalized}
            if signature:
                value["signature"] = str(signature)  # Provenance; no longer a reuse gate.
                value["benchmark"] = deepcopy(benchmark or {})
            folder = self.root / "virtual_sensors" / context["sensor_id"] / "successful"
            _write(folder / f"{key}.json", value)
            saved = {"id": key, **value}
            self._successful_match_cache[key] = deepcopy(saved) if signature and (benchmark or {}).get("passed") else None
            return saved

    def matching_successful_virtual_profile(self, camera_id, cell_id, crop_region, roi_cm,
                                           sampling_interval_s, config, sensor_id="froth_interface"):
        """Reuse any passing record with the same camera, crop, ROI, rate and detector settings.

        Old signed schema-v2 records are eligible. Their calibration ID and
        strict runtime signature are deliberately not part of the global key.
        Unsigned legacy records are not evidence of a successful benchmark.
        """
        from lib.virtual_sensors.interface import normalized_config
        with self.lock:
            identity = self._successful_virtual_context(camera_id, cell_id, crop_region, roi_cm,
                                                        sampling_interval_s, sensor_id)
            normalized = normalized_config(config)
            payload = json.dumps({"identity": identity, "config": normalized},
                                 sort_keys=True, separators=(",", ":"))
            cache_key = hashlib.sha256(payload.encode("utf-8")).hexdigest()
            if cache_key in self._successful_match_cache:
                return deepcopy(self._successful_match_cache[cache_key])
            folder = self.root / "virtual_sensors" / identity["sensor_id"] / "successful"
            latest = None
            for path in folder.glob("*.json"):
                try:
                    item = _read(path, {})
                    context = item.get("context") or {}
                    if (item.get("schema_version", 0) < 2 or not item.get("signature")
                            or not (item.get("benchmark") or {}).get("passed")):
                        continue
                    if any(context.get(k) != expected for k, expected in identity.items()):
                        continue
                    if normalized_config(item.get("config")) != normalized:
                        continue
                    candidate = {"id": path.stem, **item}
                    if latest is None or (candidate.get("tested_at") or "") > (latest.get("tested_at") or ""):
                        latest = candidate
                except (OSError, ValueError, TypeError, KeyError):
                    continue
            self._successful_match_cache[cache_key] = deepcopy(latest)
            return deepcopy(latest)

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
            for key in ("camera_id", "cell_id", "last_used_cell_id", "last_used_camera_id"):
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
