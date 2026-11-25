"""Versioned camera-image cross-section outlines; independent from ArUco and V(h)."""
from __future__ import annotations

import math
import re

KINDS = ("rectangle", "square", "circle", "polygon")
METHODS = ("diagonal", "three_corners", "four_faces", "vertices", "diameter")
ANCHORS = ("horizontal", "vertical")
DIMENSIONS = ("width_mm", "depth_mm")


def _pixels(points, size):
    return [(p[0] * size[0], p[1] * size[1]) for p in points]


def _cross(a, b, c):
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _polygon_area(points):
    return abs(sum(a[0] * b[1] - b[0] * a[1]
                   for a, b in zip(points, points[1:] + points[:1]))) / 2


def _simple_polygon(points):
    n = len(points)
    for i in range(n):
        a, b = points[i], points[(i + 1) % n]
        for j in range(i + 1, n):
            if (j == i + 1) or (i == 0 and j == n - 1):
                continue
            c, d = points[j], points[(j + 1) % n]
            v = [_cross(a, b, c), _cross(a, b, d),
                 _cross(c, d, a), _cross(c, d, b)]
            if v[0] * v[1] <= 0 and v[2] * v[3] <= 0:
                return False
    return True


def outline_vertices(item):
    """Normalized vertices; input points remain owned by the outline, not references."""
    points = item.get("points_norm") or item.get("bounds_norm")
    method = item.get("method", "diagonal")
    if method in ("diagonal", "diameter"):
        a, b = points
        return [[a[0], a[1]], [b[0], a[1]], [b[0], b[1]], [a[0], b[1]]]
    if method == "three_corners":
        a, b, c = points
        return [a, b, c, [a[0] + c[0] - b[0], a[1] + c[1] - b[1]]]
    if method == "four_faces":
        center = [sum(p[0] for p in points) / 4, sum(p[1] for p in points) / 4]
        return [[points[i][0] + points[(i + 1) % 4][0] - center[0],
                 points[i][1] + points[(i + 1) % 4][1] - center[1]]
                for i in range(4)]
    return [list(p) for p in points]


def normalize_shapes(payload):
    if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
        raise ValueError("Provide a list of geometric outlines")
    if len(payload["items"]) > 64:
        raise ValueError("At most 64 visual outlines are allowed per cell")
    items, used = [], set()
    for item in payload["items"]:
        if not isinstance(item, dict):
            raise ValueError("Each outline must be an object")
        ident, name, kind = str(item.get("id", "")), str(item.get("name", "")).strip(), item.get("kind")
        if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}", ident) or ident in used:
            raise ValueError("Outline IDs must be unique and stable")
        if not 1 <= len(name) <= 80 or kind not in KINDS:
            raise ValueError("Select rectangle, square, circle or polygon and a name")
        if item.get("plane") != "XY":
            raise ValueError("Cross-section outlines must belong to the top XY plane")
        if item.get("anchor_field") not in DIMENSIONS or item.get("anchor_axis") not in ANCHORS:
            raise ValueError("Link an outline edge to a known width or depth")
        method = item.get("method") or ("diameter" if kind == "circle" else
                                      "vertices" if kind == "polygon" else "diagonal")
        if method not in METHODS or (kind == "polygon" and method != "vertices") or (
                kind == "circle" and method != "diameter") or (
                kind in ("rectangle", "square") and method not in
                ("diagonal", "three_corners", "four_faces")):
            raise ValueError("Invalid input method for this shape")
        points = item.get("points_norm", item.get("bounds_norm"))
        count = len(points) if isinstance(points, list) else -1
        if not (count == 2 and method in ("diagonal", "diameter") or
                count == 3 and method == "three_corners" or
                count == 4 and method == "four_faces" or
                3 <= count <= 32 and method == "vertices"):
            raise ValueError("This input method requires a different number of points")
        if any(not isinstance(p, (list, tuple)) or len(p) != 2 for p in points):
            raise ValueError("Every shape point needs image X and Y coordinates")
        try:
            points = [[float(v) for v in p] for p in points]
            size = [int(v) for v in item["frame_size"]]
            rev = int(item["camera_revision"])
        except (TypeError, ValueError, KeyError):
            raise ValueError("Shape coordinates, frame size and optical revision are required") from None
        if (len(size) != 2 or not 16 <= min(size) <= max(size) <= 16000 or
                any(not math.isfinite(v) or not 0 <= v <= 1 for p in points for v in p)):
            raise ValueError("Shape points must lie within a valid camera image")
        temp = {"points_norm": points, "method": method}
        vertices = _pixels(outline_vertices(temp), size)
        if (_polygon_area(vertices) < 25 or
                any(math.dist(a, b) < 5 for a, b in zip(vertices, vertices[1:] + vertices[:1])) or
                not _simple_polygon(vertices)):
            raise ValueError("The geometric outline is too small or self-intersecting")
        camera = str(item.get("camera_id", ""))
        if not re.fullmatch(r"[0-9]{1,6}", camera):
            raise ValueError("Select the camera used for this outline")
        if item.get("image_space") not in ("raw", "undistorted", "rectified"):
            raise ValueError("Invalid outline image space")
        try:
            edge = int(item.get("anchor_edge", 0))
        except (TypeError, ValueError):
            raise ValueError("Select an outline edge for the known dimension") from None
        if not 0 <= edge < len(vertices):
            raise ValueError("Selected known-length edge is outside the outline")
        used.add(ident)
        normalized = {"id": ident, "name": name, "kind": kind, "method": method,
            "plane": "XY", "camera_id": camera, "camera_revision": rev,
            "points_norm": points, "frame_size": size, "image_space": item["image_space"],
            "optics_corrected": bool(item.get("optics_corrected",
                                            item["image_space"] == "rectified")),
            "anchor_field": item["anchor_field"], "anchor_axis": item["anchor_axis"],
            "anchor_edge": edge}
        if method in ("diagonal", "diameter"):
            normalized["bounds_norm"] = points  # Preserves old two-point client readers.
        items.append(normalized)
    return items


def estimate_area(item, dimensions, camera_revision):
    if camera_revision != item["camera_revision"]:
        return {"valid": False, "reason": "camera optics changed"}
    dim = dimensions.get(item["anchor_field"])
    if not dim or not math.isfinite(float(dim["value_mm"])) or dim["value_mm"] <= 0:
        return {"valid": False, "reason": "linked dimension is unknown"}
    size = item["frame_size"]
    vertices = _pixels(outline_vertices(item), size)
    method = item.get("method", "diagonal")
    known_cm = dim["value_mm"] / 10
    if item["kind"] == "circle":
        area = math.pi * (known_cm / 2) ** 2
    elif method == "diagonal":
        a, b = item.get("bounds_norm") or item["points_norm"]
        width, height = abs(b[0]-a[0])*size[0], abs(b[1]-a[1])*size[1]
        span = width if item["anchor_axis"] == "horizontal" else height
        area = (known_cm ** 2 if item["kind"] == "square" else
                known_cm ** 2 * (width * height) / (span ** 2))
    else:
        edge = item.get("anchor_edge", 0)
        anchor_px = math.dist(vertices[edge], vertices[(edge + 1) % len(vertices)])
        area = _polygon_area(vertices) * (known_cm / anchor_px) ** 2
    return {"valid": True, "area_cm2": area, "anchor_mm": dim["value_mm"],
        "anchor_source": dim["source"], "method": "visual_shape_ratio",
        "quality": "estimated", "optically_corrected": bool(item.get("optics_corrected", False))}
