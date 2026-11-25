"""Independent visual cell cross-section outlines. No ArUco or HIFIE file changes."""
from __future__ import annotations
import math
import re

KINDS = ("rectangle", "square", "circle")
ANCHORS = ("horizontal", "vertical")
DIMENSIONS = ("width_mm", "depth_mm")


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
            raise ValueError("Select a shape (rectangle, square, circle) and its name")
        if item.get("plane") != "XY":
            raise ValueError("Cross-section outlines must belong to the top XY plane")
        if item.get("anchor_field") not in DIMENSIONS or item.get("anchor_axis") not in ANCHORS:
            raise ValueError("Link an outline's width or depth to an existing physical dimension")
        box = item.get("bounds_norm")
        if not isinstance(box, list) or len(box) != 2 or any(
                not isinstance(p, (list, tuple)) or len(p) != 2 for p in box):
            raise ValueError("Outline requires two opposite image corners")
        try:
            box = [[float(v) for v in p] for p in box]
            size = [int(v) for v in item["frame_size"]]
            rev = int(item["camera_revision"])
        except (TypeError, ValueError, KeyError):
            raise ValueError("Outline coordinates, frame size and optical revision are required") from None
        if not all(math.isfinite(v) and 0 <= v <= 1 for p in box for v in p):
            raise ValueError("Outline corners must lie within the image")
        if len(size) != 2 or min(size) < 16 or max(size) > 16000:
            raise ValueError("Invalid image frame size")
        if abs(box[1][0]-box[0][0])*size[0] < 5 or abs(box[1][1]-box[0][1])*size[1] < 5:
            raise ValueError("Draw a larger outline")
        camera = str(item.get("camera_id", ""))
        if not re.fullmatch(r"[0-9]{1,6}", camera):
            raise ValueError("Select the camera used for this outline")
        if item.get("image_space") not in ("raw", "undistorted", "rectified"):
            raise ValueError("Invalid outline image space")
        used.add(ident)
        items.append({"id": ident, "name": name, "kind": kind, "plane": "XY",
            "camera_id": camera, "camera_revision": rev, "bounds_norm": box,
            "frame_size": size, "image_space": item["image_space"],
            "optics_corrected": bool(item.get("optics_corrected", item["image_space"] == "rectified")),
            "anchor_field": item["anchor_field"], "anchor_axis": item["anchor_axis"]})
    return items


def estimate_area(item, dimensions, camera_revision):
    if camera_revision != item["camera_revision"]:
        return {"valid": False, "reason": "camera optics changed"}
    dim = dimensions.get(item["anchor_field"])
    if not dim or not math.isfinite(float(dim["value_mm"])) or dim["value_mm"] <= 0:
        return {"valid": False, "reason": "linked dimension is unknown"}
    x0, y0 = item["bounds_norm"][0]
    x1, y1 = item["bounds_norm"][1]
    w, h = abs(x1-x0)*item["frame_size"][0], abs(y1-y0)*item["frame_size"][1]
    span = w if item["anchor_axis"] == "horizontal" else h
    known_cm = dim["value_mm"]/10
    if item["kind"] == "circle":
        area = math.pi*(known_cm/2)**2
    elif item["kind"] == "square":
        area = known_cm**2
    else:
        area = known_cm**2*(h/w if item["anchor_axis"]=="horizontal" else w/h)
    return {"valid": True, "area_cm2": area, "anchor_mm": dim["value_mm"],
        "anchor_source": dim["source"], "method": "visual_shape_ratio",
        "quality": "estimated", "optically_corrected": bool(item.get("optics_corrected", False))}
