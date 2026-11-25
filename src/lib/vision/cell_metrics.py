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
        pos, source = position(ident)
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
