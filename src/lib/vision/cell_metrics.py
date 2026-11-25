"""Resolve cell dimensions from named ArUco positions before nominal values.

Coordinates are cm in the rectified plane; dimensions are mm. Geometrical
cross-section is not a calibrated effective area.
"""
from __future__ import annotations
import math
from .reference import aruco_bottom_y_cm, complete_reference_points

PAIR_FIELDS = ("width_mm", "depth_mm", "collection_height_mm")


def normalize_dimension_pairs(payload, references):
    if not isinstance(payload, dict):
        raise ValueError("Measured dimension mapping must be an object")
    pairs = payload.get("pairs", {})
    if not isinstance(pairs, dict) or set(pairs) - set(PAIR_FIELDS):
        raise ValueError("Unknown measured dimension field")
    refs = {p["id"] for p in complete_reference_points(references)["points"]}
    result = {}
    for field in PAIR_FIELDS:
        pair = pairs.get(field)
        if pair in (None, {}, ""):
            continue
        if not isinstance(pair, dict) or set(pair) - {"from_id", "to_id"}:
            raise ValueError(f"{field} requires two named physical references")
        a, b = str(pair.get("from_id") or ""), str(pair.get("to_id") or "")
        if a not in refs or b not in refs or a == b:
            raise ValueError(f"{field} requires two different saved reference points")
        result[field] = {"from_id": a, "to_id": b}
    return result


def _position(points, ident, layout, visited=None):
    visited = set(visited or ())
    if ident in visited:
        return None, None
    visited.add(ident)
    item = points.get(ident)
    if not item:
        return None, None
    if ident == "aruco_reference" and layout:
        try:
            return [0., aruco_bottom_y_cm(layout)], "aruco"
        except (ValueError, KeyError, TypeError):
            return None, None
    pos = item.get("position_cm")
    source = item.get("source", "unset")
    if source == "derived":
        base, _ = _position(points, str(item.get("derived_from") or ""), layout, visited)
        offset = item.get("offset_y_cm")
        if base is None or offset is None:
            return None, None
        return [base[0], base[1] + float(offset)], "derived"
    if pos is None or source in ("unset", "automatic"):
        return None, None
    return [float(pos[0]), float(pos[1])], "measured" if source in ("image_selection", "measured", "reused") else "derived"


def resolve_cell_dimensions(cell, pairs=None):
    cell = cell or {}
    geometry = cell.get("geometry") or {}
    library = complete_reference_points(cell.get("reference_points"))
    points = {p["id"]: p for p in library["points"]}
    layout = cell.get("marker_layout")
    dimensions, levels = {}, {}
    mapping = (pairs or {}).get("pairs") or {}

    def record(field, cm, provenance, references=None):
        if cm is None or not math.isfinite(cm) or cm <= 0:
            return
        entry = {"value_mm": cm*10., "source": provenance, "references": references or []}
        previous = dimensions.get(field)
        rank = {"measured": 3, "derived": 2, "nominal": 1}
        if previous is None or rank[provenance] > rank[previous["source"]]:
            dimensions[field] = entry

    def position(ident):
        return _position(points, ident, layout)

    for ident in ("outlet_level", "cell_top", "cell_bottom", "aruco_reference"):
        pos, source = _physical_position(cell, ident)
        levels[ident] = {"y_cm": pos[1] if pos else None, "source": source}

    top, top_source = position("cell_top")
    bottom, bottom_source = position("cell_bottom")
    if top and bottom and bottom[1] > top[1]:
        quality = "measured" if top_source == bottom_source == "measured" else "derived"
        record("height_mm", bottom[1] - top[1], quality, ["cell_top", "cell_bottom"])

    for field, selected in mapping.items():
        if field not in PAIR_FIELDS or not isinstance(selected, dict):
            continue
        a, source_a = position(selected.get("from_id"))
        b, source_b = position(selected.get("to_id"))
        if a and b:
            # Operator asserts both landmarks span this dimension in one physical plane.
            distance = math.hypot(a[0]-b[0], a[1]-b[1])
            quality = "measured" if source_a == source_b == "measured" else "derived"
            record(field, distance, quality, [selected["from_id"], selected["to_id"]])

    for field in ("height_mm",) + PAIR_FIELDS:
        try:
            value = geometry.get(field)
            cm = float(value) / 10 if value not in (None, "") else None
            record(field, cm, "nominal")
        except (TypeError, ValueError):
            continue

    shape = geometry.get("shape", "custom")
    width, depth = dimensions.get("width_mm"), dimensions.get("depth_mm")
    area, area_sources = None, []
    if shape == "cylindrical" and width:
        area = math.pi * (width["value_mm"] / 20) ** 2
        area_sources = [width["source"]]
    elif shape == "rectangular" and width and depth:
        area = (width["value_mm"]/10) * (depth["value_mm"]/10)
        area_sources = [width["source"], depth["source"]]
    area_source = ("measured_geometry" if all(x == "measured" for x in area_sources) else
                   "nominal_geometry" if all(x == "nominal" for x in area_sources) else
                   "mixed_geometry") if area_sources else None
    height = dimensions.get("height_mm")
    return {"dimensions": dimensions, "references": levels,
            "geometric_area_cm2": area, "geometric_area_source": area_source,
            "geometric_capacity_l": area * height["value_mm"] / 10000 if area and height else None,
            "effective_area_cm2": None, "geometry_shape": shape,
            "dimension_revision": (pairs or {}).get("revision", 0),
            "reference_revision": library.get("revision", 0)}


def _physical_position(cell, ident):
    points = {p["id"]: p for p in complete_reference_points(cell.get("reference_points"))["points"]}
    position, source = _position(points, ident, cell.get("marker_layout"))
    if position is not None or ident not in ("cell_top", "cell_bottom"):
        return position, source
    # Fallback: infer one boundary from the other and a nominal full cell height.
    # This is not a measured physical datum; changes to nominal H invalidate V(h).
    counterpart = "cell_top" if ident == "cell_bottom" else "cell_bottom"
    other, _ = _position(points, counterpart, cell.get("marker_layout"))
    try:
        height_mm = float((cell.get("geometry") or {})["height_mm"])
    except (KeyError, ValueError, TypeError):
        return None, None
    if other is None or not math.isfinite(height_mm) or height_mm <= 0:
        return None, None
    offset = height_mm / 10 * (1 if ident == "cell_bottom" else -1)
    return [other[0], other[1] + offset], "nominal_derived"


def normalize_volume_curve(cell, payload):
    """Express known fills relative to a chosen datum, then anchor V(0)=0 at Cell bottom."""
    if not isinstance(payload, dict):
        raise ValueError("Volume calibration must be an object")
    reference_id = str(payload.get("datum_reference_id") or "cell_bottom")
    bottom, bottom_source = _physical_position(cell, "cell_bottom")
    datum, datum_source = _physical_position(cell, reference_id)
    if bottom is None:
        raise ValueError("Place Cell bottom in named physical references before calibrating V(h).")
    if datum is None:
        raise ValueError("The chosen reference has no physical coordinate. Place it in Cells.")
    raw_points = payload.get("points")
    if not isinstance(raw_points, list) or not 1 <= len(raw_points) <= 64:
        raise ValueError("Provide 1 to 64 known-volume calibration points.")
    known = []
    limit = ((cell.get("resolved_dimensions") or {}).get("dimensions") or {}).get("height_mm")
    max_height = float(limit["value_mm"]) / 10 if limit else None
    for raw in raw_points:
        if not isinstance(raw, dict):
            raise ValueError("Each known fill requires height_cm and volume_l.")
        try:
            height = float(raw["height_cm"])
            volume = float(raw["volume_l"])
        except (KeyError, TypeError, ValueError):
            raise ValueError("Calibration height and volume must be numeric.") from None
        if not math.isfinite(height) or not math.isfinite(volume) or volume <= 0:
            raise ValueError("Known fill volume must be positive and all values finite.")
        bottom_height = bottom[1] - datum[1] + height
        if bottom_height <= 0 or (max_height is not None and bottom_height > max_height + .01):
            raise ValueError("A known fill must lie above Cell bottom and inside the calibrated cell height.")
        known.append({"height_cm": bottom_height, "volume_l": volume,
                      "relative_height_cm": height})
    known.sort(key=lambda point: point["height_cm"])
    previous_h = previous_v = 0.
    for point in known:
        if point["height_cm"] - previous_h <= 1e-6 or point["volume_l"] < previous_v:
            raise ValueError("Known fills require distinct increasing heights and nondecreasing volumes.")
        previous_h, previous_v = point["height_cm"], point["volume_l"]
    points = [{"height_cm": 0., "volume_l": 0., "fixed_origin": True}] + [
        {"height_cm": round(point["height_cm"], 7), "volume_l": point["volume_l"]} for point in known]
    slopes = [1000 * (b["volume_l"]-a["volume_l"]) / (b["height_cm"]-a["height_cm"])
              for a, b in zip(points, points[1:])]
    return {"schema_version": 1, "model": "piecewise_linear", "datum_reference_id": reference_id,
            "datum_y_cm": datum[1], "bottom_y_cm": bottom[1],
            "datum_source": datum_source, "bottom_source": bottom_source,
            "reference_revision": cell.get("reference_points_revision", 0),
            "points": points, "raw_points": [
                {"height_cm": p["relative_height_cm"], "volume_l": p["volume_l"]} for p in known],
            "area_range_cm2": [min(slopes), max(slopes)]}


def volume_curve_is_current(cell, curve):
    if not curve or not curve.get("points"):
        return False
    if curve.get("reference_revision") != cell.get("reference_points_revision"):
        return False
    bottom, _ = _physical_position(cell, "cell_bottom")
    datum, _ = _physical_position(cell, curve.get("datum_reference_id"))
    return bool(bottom and datum and
                abs(bottom[1]-float(curve.get("bottom_y_cm", float("nan")))) < 1e-6 and
                abs(datum[1]-float(curve.get("datum_y_cm", float("nan")))) < 1e-6)


def evaluate_volume_curve(curve, height_cm):
    """Piecewise V(h), linear extrapolation above last known fill."""
    if not curve or not curve.get("valid"):
        raise ValueError("No current experimental volume calibration is available.")
    height = float(height_cm)
    if not math.isfinite(height) or height < -.01:
        raise ValueError("Volume height must be at or above Cell bottom.")
    height = max(0., height)
    points = curve["points"]
    previous, selected = points[0], points[-1]
    for next_point in points[1:]:
        selected = next_point
        if height <= next_point["height_cm"]:
            break
        previous = next_point
    else:
        previous, selected = points[-2], points[-1]
    slope = (selected["volume_l"]-previous["volume_l"]) / (selected["height_cm"]-previous["height_cm"])
    volume = previous["volume_l"] + slope * (height-previous["height_cm"])
    return {"volume_l": volume, "effective_area_cm2": slope*1000,
            "extrapolated": height > points[-1]["height_cm"]+1e-8,
            "calibration_revision": curve.get("revision")}
