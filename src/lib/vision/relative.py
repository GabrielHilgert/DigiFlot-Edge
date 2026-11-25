"""Independent, approximate image-plane scale from a calibrated camera and known cell length.

Never creates or replaces ArUco homographies. Reference/target pairs are measured
in one undistorted or raw image at the same image geometry. Scale is isotropic
only on the specified target physical plane.
"""
from __future__ import annotations
import math
import numpy as np
from .aruco import optical_parameters, _undistort_points

FIELDS = ("width_mm", "depth_mm", "height_mm", "collection_height_mm")


def normalize_pair(value, name):
    if not isinstance(value, list) or len(value) != 2:
        raise ValueError(f"{name} requires two clicked points")
    result = []
    for point in value:
        if not isinstance(point, (list, tuple)) or len(point) != 2:
            raise ValueError(f"{name} points must be [x,y]")
        xy = [float(v) for v in point]
        if not all(math.isfinite(v) and 0 <= v <= 1 for v in xy):
            raise ValueError(f"{name} points must use normalized image coordinates")
        result.append(xy)
    if math.dist(*result) < .005:
        raise ValueError(f"{name} endpoints are too close")
    return result


def normalized_distance(pair, frame_size, camera_profile, image_space):
    width, height = [int(x) for x in frame_size]
    if min(width, height) <= 0 or max(width, height) > 16000:
        raise ValueError("Invalid source frame size")
    coords = np.array([[p[0] * width, p[1] * height] for p in pair], dtype=np.float32)
    if image_space == "raw":
        K, D, model = optical_parameters(camera_profile, (width, height))
        coords = _undistort_points(coords, K, D, model)
    elif image_space != "undistorted":
        raise ValueError("Select raw or undistorted image coordinates")
    distance = float(np.linalg.norm(coords[1]-coords[0]))
    if not math.isfinite(distance) or distance < 3:
        raise ValueError("Select points separated by at least 3 image pixels")
    return distance


def relative_scale(payload, source_mm, target_camera_profile):
    if not isinstance(payload, dict) or payload.get("reference_field") not in FIELDS:
        raise ValueError("Select a known cell dimension for the calibration scale")
    if payload.get("target_field") not in FIELDS:
        raise ValueError("Choose the target dimension to estimate")
    if payload["reference_field"] == payload["target_field"]:
        raise ValueError("Use a different dimension for the estimated target")
    try:
        source_mm = float(source_mm)
    except (ValueError, TypeError):
        raise ValueError("Reference dimension has no known physical value") from None
    if not math.isfinite(source_mm) or source_mm <= 0:
        raise ValueError("Reference dimension must be positive")
    frame_size = payload.get("frame_size")
    image_space = payload.get("image_space", "raw")
    base = normalize_pair(payload.get("reference_pair"), "Reference")
    target = normalize_pair(payload.get("target_pair"), "Target")
    base_px = normalized_distance(base, frame_size, target_camera_profile, image_space)
    target_px = normalized_distance(target, frame_size, target_camera_profile, image_space)
    if not 0.01 <= target_px / base_px <= 100:
        raise ValueError("The estimated length is outside the supported ratio")
    return {"reference_pair": base, "target_pair": target, "frame_size": list(frame_size),
            "image_space": image_space, "reference_mm": source_mm,
            "reference_px": base_px, "target_px": target_px,
            "mm_per_px": source_mm / base_px,
            "target_mm": source_mm * target_px / base_px,
            "model": "relative_planar_isotropic_scale", "quality": "estimated"}
