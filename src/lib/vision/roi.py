"""Planar ROI geometry and precompiled remapping for low-latency Cell Vision.

The full-plane transform is for setup/inspection. During acquisition, only the
confirmed physical ROI is mapped, and source pixels are cropped before remap.
"""
from __future__ import annotations

import math
import cv2
import numpy as np

from .aruco import _undistort_points, frame_transform, optical_parameters, project_rectified


def full_plane_geometry(calibration, camera_profile, target_geometry, max_size=(1600, 1200)):
    """Project sampled image borders onto the ArUco plane and bound a preview.

    Assumes the image border corresponds to the marker plane; areas outside
    that plane are extrapolations, not metrically corrected 3-D surfaces.
    """
    w, h = (int(v) for v in target_geometry["size"])
    if w < 2 or h < 2:
        raise ValueError("Invalid source image dimensions")
    x = np.linspace(0, w - 1, 33, dtype=np.float32)
    y = np.linspace(0, h - 1, 33, dtype=np.float32)
    border = np.vstack((np.column_stack((x, np.zeros_like(x))),
                        np.column_stack((x, np.full_like(x, h - 1))),
                        np.column_stack((np.zeros_like(y), y)),
                        np.column_stack((np.full_like(y, w - 1), y))))
    source = calibration["frame"]
    back = frame_transform(target_geometry, source)
    native = cv2.perspectiveTransform(border.reshape(-1, 1, 2), back).reshape(-1, 2)
    K, D, model = optical_parameters(camera_profile, source["size"])
    corrected = _undistort_points(native, K, D, model)
    projected = cv2.perspectiveTransform(corrected.reshape(-1, 1, 2),
                                         np.asarray(calibration["H"], np.float64)).reshape(-1, 2)
    density = float(calibration["px_per_cm"])
    world = projected / density + np.asarray(calibration["min_xy_cm"], float)
    if not np.isfinite(world).all():
        raise ValueError("Camera border cannot be projected onto the ArUco plane")
    minimum, maximum = np.min(world, axis=0), np.max(world, axis=0)
    minimum -= 1.0 / density
    maximum += 1.0 / density
    span = maximum - minimum
    if np.any(span <= 0) or np.any(span > 2000):
        raise ValueError("Unstable plane extrapolation at the image border; check the camera angle and optics")
    scale = min(density, max_size[0] / span[0], max_size[1] / span[1],
                math.sqrt(1_800_000 / float(span[0] * span[1])))
    if not math.isfinite(scale) or scale <= 0:
        raise ValueError("Invalid planar preview resolution")
    size = np.ceil(span * scale).astype(int)
    if min(size) < 2:
        raise ValueError("Planar preview is too small")
    actual_maximum = minimum + size / scale
    return {"min_xy_cm": minimum.tolist(), "max_xy_cm": actual_maximum.tolist(),
            "px_per_cm": float(scale), "size": size.tolist()}


def compile_roi_maps(calibration, camera_profile, target_geometry, roi_cm, px_per_cm=None,
                     output_size=None, max_pixels=4_000_000):
    """Compile a rectified physical ROI into fixed-point maps and a source crop.

    All expensive distortion, perspective projection and fixed-point conversion
    happen once per ROI, camera geometry and calibration revision.
    """
    roi = np.asarray(roi_cm, np.float64)
    if roi.shape != (4,) or not np.isfinite(roi).all() or roi[2] <= roi[0] or roi[3] <= roi[1]:
        raise ValueError("ROI must be [x0_cm,y0_cm,x1_cm,y1_cm] with positive dimensions")
    density = float(px_per_cm if px_per_cm is not None else calibration["px_per_cm"])
    if not math.isfinite(density) or density <= 0:
        raise ValueError("Invalid ROI output resolution")
    size = np.ceil((roi[2:] - roi[:2]) * density).astype(int) if output_size is None else np.asarray(output_size, int)
    width, height = (int(v) for v in size)
    if width < 2 or height < 2 or width * height > max_pixels:
        raise ValueError("ROI output exceeds resolution or memory limits")
    xs, ys = np.meshgrid(roi[0] + np.arange(width, dtype=np.float32) / density,
                         roi[1] + np.arange(height, dtype=np.float32) / density)
    old_minimum = np.asarray(calibration["min_xy_cm"], np.float32)
    old_density = float(calibration["px_per_cm"])
    rectified = (np.column_stack((xs.ravel(), ys.ravel())) - old_minimum) * old_density
    maps = np.empty((len(rectified), 2), np.float32)
    for first in range(0, len(rectified), 100_000):
        last = min(first + 100_000, len(rectified))
        maps[first:last] = project_rectified(rectified[first:last], calibration, camera_profile, target_geometry)
    w, h = (int(v) for v in target_geometry["size"])
    valid = np.isfinite(maps).all(axis=1) & (maps[:, 0] >= 0) & (maps[:, 0] < w) & (maps[:, 1] >= 0) & (maps[:, 1] < h)
    if not valid.any():
        raise ValueError("The selected planar ROI is outside the camera field of view")
    xmin = max(0, int(np.floor(maps[valid, 0].min())) - 1)
    ymin = max(0, int(np.floor(maps[valid, 1].min())) - 1)
    xmax = min(w, int(np.ceil(maps[valid, 0].max())) + 2)
    ymax = min(h, int(np.ceil(maps[valid, 1].max())) + 2)
    maps[~valid] = (-2, -2)
    map_x = np.ascontiguousarray((maps[:, 0].reshape(height, width) - xmin).astype(np.float32))
    map_y = np.ascontiguousarray((maps[:, 1].reshape(height, width) - ymin).astype(np.float32))
    map1, map2 = cv2.convertMaps(map_x, map_y, cv2.CV_16SC2)
    return {"map1": map1, "map2": map2, "source_bbox": (xmin, ymin, xmax, ymax),
            "size": [width, height], "roi_cm": roi.tolist(), "coverage": float(np.mean(valid))}


def remap_roi(image, compiled):
    """Apply only the precompiled ROI mapping (supports Y-plane or BGR)."""
    x0, y0, x1, y1 = compiled["source_bbox"]
    source = image[y0:y1, x0:x1]
    if source.size == 0:
        raise ValueError("ROI source crop is empty")
    return cv2.remap(source, compiled["map1"], compiled["map2"], cv2.INTER_LINEAR,
                     borderMode=cv2.BORDER_CONSTANT, borderValue=0)
