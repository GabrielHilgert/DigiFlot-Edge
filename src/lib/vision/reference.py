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


def resolve_vertical_reference(config, association):
    """Return a frozen, explicit datum that can be used without raw image pixels."""
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
