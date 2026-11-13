"""Independent physical vertical datum for a camera-cell pair.

Image rows and the ArUco plane increase downward. Physical position is
reported upward from the bottom/ArUco datum or downward from the cell top.
The datum can lie outside the camera field of view.
"""
from __future__ import annotations

import math

CELL_MODES = ("aruco_bottom", "cell_top", "cell_bottom")
SENSOR_MODES = ("cell_default",) + CELL_MODES + ("historical_offset",)


def _optional_cm(value, name):
    if value is None or value == "":
        return None
    try:
        value = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a number in cm") from exc
    if not math.isfinite(value) or abs(value) > 2000:
        raise ValueError(f"{name} must be finite and within ±2000 cm")
    return value


def normalize_cell_reference(data=None):
    """Physical cell settings, independent of the marker homography revision."""
    values = data or {}
    if not isinstance(values, dict):
        raise ValueError("Cell vertical reference must be an object")
    mode = values.get("mode", "aruco_bottom")
    if mode not in CELL_MODES:
        raise ValueError("Unknown cell reference mode")
    return {"mode": mode, "cell_top_y_cm": _optional_cm(values.get("cell_top_y_cm"), "Cell top"),
            "cell_bottom_y_cm": _optional_cm(values.get("cell_bottom_y_cm"), "Cell bottom")}


def aruco_bottom_y_cm(layout):
    """Bottommost physical marker corner, NOT calibration rectangle padding."""
    if not isinstance(layout, dict):
        raise ValueError("No ArUco marker layout")
    span = float(layout["span_cm"])
    size = float(layout["marker_size_cm"])
    if not (math.isfinite(span) and span > 0 and math.isfinite(size) and size > 0):
        raise ValueError("Invalid ArUco layout")
    # In the L-ruler layout marker 0 has y=[0,s], markers 1 and 2
    # terminate at y=span (their anchor is corner 1).
    return max(span, size)



def default_reference_points():
    """Uncalibrated Outlet level is preferred; the ArUco datum is always available."""
    return {"schema_version": 2, "revision": 0, "default_reference_id": "outlet_level",
            "points": [
                {"id": "outlet_level", "name": "Outlet level", "type": "custom",
                 "position_cm": None, "direction": "up", "source": "unset"},
                {"id": "aruco_reference", "name": "ArUco reference", "type": "aruco",
                 "position_cm": None, "direction": "up", "source": "automatic"},
            ]}


def normalize_reference_points(value):
    """Validate a named, repeatable list of references without imposing a count limit."""
    import re
    if not isinstance(value, dict):
        raise ValueError("Reference points must be an object")
    points = value.get("points")
    if not isinstance(points, list) or not points or len(points) > 4096:
        raise ValueError("Provide at least one named reference (maximum 4096)")
    seen, normalized = set(), []
    for raw in points:
        if not isinstance(raw, dict):
            raise ValueError("Each reference must be an object")
        ident = str(raw.get("id", "")).strip()
        name = str(raw.get("name", "")).strip()
        kind = str(raw.get("type", "custom"))
        direction = str(raw.get("direction", "up"))
        source = str(raw.get("source", "unset"))
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", ident) or ident in seen:
            raise ValueError("References require unique stable identifiers")
        if not 1 <= len(name) <= 80 or kind not in ("top", "bottom", "aruco", "custom"):
            raise ValueError("Reference name or type is invalid")
        if direction not in ("up", "down") or source not in ("unset", "automatic", "image_selection", "measured", "derived", "reused"):
            raise ValueError("Reference direction or source is invalid")
        pos = raw.get("position_cm")
        if pos is not None:
            if not isinstance(pos, (list, tuple)) or len(pos) != 2:
                raise ValueError("Reference position must be [x_cm, y_cm]")
            pos = [_optional_cm(x, "Reference position") for x in pos]
            if any(x is None for x in pos):
                raise ValueError("Reference coordinates must be finite")
        if kind == "aruco" and ident == "aruco_reference":
            pos, source = None, "automatic"
        seen.add(ident)
        normalized.append({"id": ident, "name": name, "type": kind, "position_cm": pos,
                           "direction": direction, "source": source,
                           "derived_from": raw.get("derived_from") if source == "derived" else None,
                           "offset_y_cm": _optional_cm(raw.get("offset_y_cm"), "Derived Y offset")
                           if source == "derived" else None})
    default_id = str(value.get("default_reference_id") or "")
    if default_id not in seen:
        raise ValueError("Default reference must be one of the saved named points")
    return {"schema_version": 2, "default_reference_id": default_id, "points": normalized}


def resolve_named_reference(config, association):
    library = association.get("reference_points") or default_reference_points()
    ident = str(config.get("reference_id") or library.get("default_reference_id") or "")
    points = {item["id"]: item for item in library.get("points", [])}
    selected = points.get(ident)
    if selected is None:
        raise ValueError("Selected named physical reference no longer exists")
    if selected["type"] == "aruco" and selected["source"] == "automatic":
        cell = association.get("cell_snapshot") or {}
        layout = (association.get("calibration") or {}).get("layout") or cell.get("marker_layout")
        y = aruco_bottom_y_cm(layout)
    elif selected["source"] == "derived":
        base = points.get(selected.get("derived_from"))
        if not base or base.get("position_cm") is None:
            raise ValueError("Derived reference requires a calibrated source point")
        y = float(base["position_cm"][1]) + float(selected.get("offset_y_cm") or 0.0)
    else:
        position = selected.get("position_cm")
        if position is None:
            raise ValueError(f"Reference '{selected['name']}' has no physical position. Select it in Cells.")
        y = float(position[1])
    return {"mode": "named", "reference_id": ident, "name": selected["name"],
            "type": selected["type"], "y_cm": y, "direction": selected["direction"],
            "source": selected["source"], "reference_revision": library.get("revision", 0)}

def resolve_vertical_reference(config, association):
    """Return a frozen, explicit datum that can be used without raw image pixels."""
    if (config or {}).get("reference_id"):
        return resolve_named_reference(config, association)
    mode = (config or {}).get("vertical_reference_mode") or "cell_default"
    if mode == "historical_offset":
        return {"mode": mode, "y_cm": None, "direction": "down",
                "source": "historical_run", "offset_cm": float(config.get("height_reference_offset_cm", 0.))}
    if mode not in SENSOR_MODES:
        raise ValueError("Invalid vertical reference mode")
    cell = association.get("cell_snapshot") or {}
    cell_ref = normalize_cell_reference(association.get("cell_vertical_reference"))
    selected = cell_ref["mode"] if mode == "cell_default" else mode
    source = "cell" if mode == "cell_default" else "sensor_override"
    custom_y = _optional_cm((config or {}).get("vertical_reference_y_cm"), "Sensor reference")
    if selected == "aruco_bottom":
        layout = (association.get("calibration") or {}).get("layout") or cell.get("marker_layout")
        value = aruco_bottom_y_cm(layout)
        direction = "up"
        source = "aruco_markers"
    else:
        top, bottom = cell_ref["cell_top_y_cm"], cell_ref["cell_bottom_y_cm"]
        if custom_y is not None and mode != "cell_default":
            value = custom_y
        else:
            height = (cell.get("geometry") or {}).get("height_mm")
            try:
                height = float(height) / 10 if height is not None else None
            except (TypeError, ValueError):
                height = None
            if height is not None and (not math.isfinite(height) or height <= 0):
                height = None
            if selected == "cell_top":
                value = top if top is not None else bottom - height if bottom is not None and height else None
            else:
                value = bottom if bottom is not None else top + height if top is not None and height else None
        if value is None:
            raise ValueError(f"{selected.replace('_',' ')} requires a physical Y position in cm "
                             "(Cell reference or sensor override), even when outside the camera view")
        direction = "down" if selected == "cell_top" else "up"
    return {"mode": selected, "y_cm": float(value), "direction": direction, "source": source,
            "cell_reference_revision": (association.get("cell_vertical_reference") or {}).get("revision", 0)}
