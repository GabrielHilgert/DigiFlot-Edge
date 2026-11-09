"""Frame-based DigiFlot ArUco calibration extracted from the historical batch pipeline.

The reference points form a LOCAL ruler coordinate system (centimetres), not
absolute camera/cell positions. A calibration is valid for one image geometry;
its frame metadata allows grid reprojection under an acquisition crop change.
"""
from __future__ import annotations

import math
import cv2
import numpy as np

DEFAULT_LAYOUT = {"dictionary": "DICT_4X4_50", "marker_ids": [0, 1, 2], "marker_size_cm": 2.0, "span_cm": 14.0}
PRESETS = {
    "quase_sem_distorcao": [8000, -.02, 0, 0, 0], "leve": [6000, -.08, .01, 0, 0],
    "media": [5000, -.15, .03, 0, 0], "forte": [4000, -.28, .08, 0, 0],
    "muito_forte": [3000, -.45, .18, -.02, 0], "fisheye_extremo": [2200, -.75, .35, -.08, .01],
}


def _dictionary(name):
    if not isinstance(name, str) or not name.startswith("DICT_") or not hasattr(cv2.aruco, name):
        raise ValueError("Unknown ArUco dictionary")
    return cv2.aruco.getPredefinedDictionary(getattr(cv2.aruco, name))


def detect_markers(image, dictionary="DICT_4X4_50", invert=False):
    """Return detected marker ID -> (4, 2) raw image pixel coordinates."""
    if image.ndim == 2:
        gray = image
    elif image.ndim == 3 and image.shape[2] in (3, 4):
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY if image.shape[2] == 3 else cv2.COLOR_BGRA2GRAY)
    else:
        raise ValueError("Expected grayscale, BGR or BGRA image")
    if invert:
        _, gray = cv2.threshold(cv2.bitwise_not(gray), 127, 255, cv2.THRESH_BINARY)
    dictionary = _dictionary(dictionary)
    params = cv2.aruco.DetectorParameters()
    if hasattr(cv2.aruco, "ArucoDetector"):
        corners, ids, _ = cv2.aruco.ArucoDetector(dictionary, params).detectMarkers(gray)
    else:
        corners, ids, _ = cv2.aruco.detectMarkers(gray, dictionary, parameters=params)
    return {int(mid): np.asarray(c, dtype=np.float32).reshape(4, 2) for mid, c in zip(ids.flatten(), corners)} if ids is not None else {}


def validate_layout(layout):
    data = dict(DEFAULT_LAYOUT)
    data.update(layout or {})
    ids = data["marker_ids"]
    if not isinstance(ids, list) or len(ids) != 3 or len(set(ids)) != 3 or any(not isinstance(x, int) or x < 0 for x in ids):
        raise ValueError("The initial L-ruler layout needs three distinct nonnegative marker IDs")
    for key in ("marker_size_cm", "span_cm"):
        val = float(data[key])
        if not math.isfinite(val) or val <= 0:
            raise ValueError(f"{key} must be positive")
        data[key] = val
    _dictionary(data["dictionary"])
    return data


def ruler_points(markers, layout):
    """Match the old ID0/c0, ID1/c1, ID2/c1 L-ruler anchors and corner convention."""
    layout = validate_layout(layout)
    ids = layout["marker_ids"]
    if any(mid not in markers for mid in ids):
        raise ValueError(f"Missing required markers: {[mid for mid in ids if mid not in markers]}")
    s, span = layout["marker_size_cm"], layout["span_cm"]
    local = np.array([[0, 0], [0, s], [-s, s], [-s, 0]], dtype=np.float32)
    anchors = [(0, [0, 0]), (1, [0, span]), (1, [span, span])]
    src, dst = [], []
    for mid, (ci, pos) in zip(ids, anchors):
        corner = np.asarray(markers[mid], dtype=np.float32).reshape(4, 2)
        world = np.asarray(pos, dtype=np.float32) - local[ci] + local
        src.extend(corner)
        dst.extend(world)
    return np.asarray(src, np.float32), np.asarray(dst, np.float32)


def optical_parameters(profile, source_size):
    """Scale camera intrinsics to a source image of identical sensor FOV."""
    optics = (profile or {}).get("optics") or {}
    mode = optics.get("mode", "none")
    w, h = [int(v) for v in source_size]
    if mode == "none":
        return None, None, "standard"
    if mode == "preset":
        vals = PRESETS.get(optics.get("preset"))
        if vals is None:
            raise ValueError("Unknown distortion preset")
        K = np.array([[vals[0] * w / 3840, 0, w / 2], [0, vals[0] * w / 3840, h / 2], [0, 0, 1]], np.float64)
        return K, np.asarray(vals[1:], dtype=np.float64), "fisheye"
    if mode == "custom":
        ref = optics.get("reference_size") or source_size
        if len(ref) != 2 or min(ref) <= 0:
            raise ValueError("Invalid intrinsic reference size")
        K = np.asarray(optics.get("K"), np.float64).reshape(3, 3).copy()
        K[0, :] *= w / ref[0]
        K[1, :] *= h / ref[1]
        D = np.asarray(optics.get("D"), np.float64).reshape(-1)
        model = optics.get("dist_model", "standard")
        if model not in ("standard", "fisheye") or (model == "fisheye" and len(D) != 4):
            raise ValueError("Invalid intrinsic distortion model")
        return K, D, model
    raise ValueError("Unknown optics mode")


def _undistort_points(points, K, D, model):
    points = np.asarray(points, np.float32).reshape(-1, 1, 2)
    if K is None:
        return points.reshape(-1, 2)
    if model == "fisheye":
        return cv2.fisheye.undistortPoints(points, K, D.reshape(-1, 1), P=K).reshape(-1, 2)
    return cv2.undistortPoints(points, K, D, P=K).reshape(-1, 2)


def _distort_points(points, K, D, model):
    pts = np.asarray(points, np.float64).reshape(-1, 2)
    if K is None:
        return pts.astype(np.float32)
    norm = np.column_stack(((pts[:, 0] - K[0, 2]) / K[0, 0], (pts[:, 1] - K[1, 2]) / K[1, 1]))
    if model == "fisheye":
        return cv2.fisheye.distortPoints(norm.reshape(-1, 1, 2), K, D.reshape(-1, 1)).reshape(-1, 2).astype(np.float32)
    objects = np.column_stack([norm, np.ones(len(norm))]).reshape(-1, 1, 3)
    projected, _ = cv2.projectPoints(objects, np.zeros(3), np.zeros(3), K, D)
    return projected.reshape(-1, 2).astype(np.float32)


def source_geometry(size, sensor_crop=None):
    w, h = [int(v) for v in size]
    if min(w, h) <= 0:
        raise ValueError("Invalid image dimensions")
    crop = [float(v) for v in (sensor_crop or [0, 0, w, h])]
    if len(crop) != 4 or min(crop[2:]) <= 0:
        raise ValueError("Invalid sensor crop")
    return {"size": [w, h], "sensor_crop": crop}


def frame_transform(from_geometry, to_geometry):
    """Raw pixel transform from one stream image to another, through sensor coordinates."""
    fw, fh = from_geometry["size"]
    tw, th = to_geometry["size"]
    fx, fy, cw, ch = from_geometry["sensor_crop"]
    tx, ty, dw, dh = to_geometry["sensor_crop"]
    return np.array([[tw * cw / (fw * dw), 0, tw * (fx - tx) / dw],
                     [0, th * ch / (fh * dh), th * (fy - ty) / dh], [0, 0, 1]], np.float64)


def calibrate(image, layout=None, camera_profile=None, frame_geometry=None, margin_cm=1.0, px_per_cm=None):
    """Estimate a local ruler-to-image rectification compatible with the legacy batch code."""
    layout = validate_layout(layout)
    h, w = image.shape[:2]
    frame_geometry = frame_geometry or source_geometry([w, h])
    if frame_geometry["size"] != [w, h]:
        raise ValueError("Frame size does not match calibration source metadata")
    markers = detect_markers(image, layout["dictionary"], bool((camera_profile or {}).get("invert", False)))
    src, dst_cm = ruler_points(markers, layout)
    K, D, model = optical_parameters(camera_profile, (w, h))
    src_geom = _undistort_points(src, K, D, model)
    if px_per_cm is None:
        p0, p1, p2 = src_geom[0], src_geom[5], src_geom[9]
        px_per_cm = (np.linalg.norm(p1 - p0) + np.linalg.norm(p2 - p1)) / (2 * layout["span_cm"])
    px_per_cm = float(px_per_cm)
    margin_cm = float(margin_cm)
    if not math.isfinite(px_per_cm) or px_per_cm <= 0 or not 0 <= margin_cm <= 20:
        raise ValueError("Invalid rectification scale or margin")
    mn, mx = dst_cm.min(axis=0) - margin_cm, dst_cm.max(axis=0) + margin_cm
    width, height = np.ceil((mx - mn) * px_per_cm).astype(int)
    if not 10 <= width <= 8192 or not 10 <= height <= 8192:
        raise ValueError("Rectification dimensions are outside supported bounds")
    dst_px = (dst_cm - mn) * px_per_cm
    H, _ = cv2.findHomography(src_geom, dst_px, method=0)
    if H is None or not np.isfinite(H).all() or abs(np.linalg.det(H)) < 1e-12:
        raise ValueError("Degenerate ArUco homography")
    pred = cv2.perspectiveTransform(src_geom.reshape(-1, 1, 2), H).reshape(-1, 2)
    residual = np.linalg.norm(pred - dst_px, axis=1)
    return {"H": H.tolist(), "H_inv": np.linalg.inv(H).tolist(), "size": [int(width), int(height)],
            "min_xy_cm": mn.tolist(), "max_xy_cm": mx.tolist(), "px_per_cm": px_per_cm,
            "rms_px": float(np.sqrt(np.mean(residual ** 2))), "max_err_px": float(np.max(residual)),
            "ids_detected": sorted(markers), "markers": {str(k): v.tolist() for k, v in markers.items()},
            "frame": frame_geometry, "layout": layout, "warp_model": "homography", "unwrap_mode": "direct"}


def project_rectified(points_rect, calibration, camera_profile=None, target_geometry=None):
    """Project points from local rectified output to raw pixels of a target stream."""
    old = calibration["frame"]
    rect = np.asarray(points_rect, np.float32).reshape(-1, 1, 2)
    H_inv = np.asarray(calibration["H_inv"], np.float64)
    points = cv2.perspectiveTransform(rect, H_inv).reshape(-1, 2)
    K, D, model = optical_parameters(camera_profile, old["size"])
    raw = _distort_points(points, K, D, model)
    transform = frame_transform(old, target_geometry or old)
    return cv2.perspectiveTransform(raw.reshape(-1, 1, 2), transform).reshape(-1, 2)


def grid_overlay(image, calibration, camera_profile=None, target_geometry=None, roi_norm=None):
    """Draw saved geometry and camera-owned ROI on a frame; never mutate source."""
    if image.ndim == 2:
        output = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
    else:
        output = image.copy()
    h, w = output.shape[:2]
    target = target_geometry or source_geometry([w, h])
    if calibration:
        mn, mx = calibration["min_xy_cm"], calibration["max_xy_cm"]
        density = float(calibration["px_per_cm"])
        def segment(a, b):
            pts = project_rectified([(a[0]-mn[0])*density, (a[1]-mn[1])*density,
                                      (b[0]-mn[0])*density, (b[1]-mn[1])*density], calibration, camera_profile, target)
            if np.isfinite(pts).all():
                cv2.line(output, tuple(np.round(pts[0]).astype(int)), tuple(np.round(pts[1]).astype(int)), (230, 180, 20), 1, cv2.LINE_AA)
        for x in np.arange(math.ceil(mn[0]), mx[0] + .01, 1):
            segment((x, mn[1]), (x, mx[1]))
        for y in np.arange(math.ceil(mn[1]), mx[1] + .01, 1):
            segment((mn[0], y), (mx[0], y))
    if roi_norm is not None:
        x0, y0, x1, y1 = [float(v) for v in roi_norm]
        pts = np.array([[x0, y0], [x1, y1]])
        sensor = target["sensor_crop"]
        # ROI coordinates refer to the complete sensor, not the local crop.
        sensor_width, sensor_height = (camera_profile or {}).get("sensor_size", target["size"])
        a = (pts * [sensor_width, sensor_height] - sensor[:2]) * [w / sensor[2], h / sensor[3]]
        p0, p1 = [tuple(np.round(p).astype(int)) for p in a]
        cv2.rectangle(output, p0, p1, (0, 225, 255), 2)
    return output


def rectification_maps(calibration, camera_profile=None, target_geometry=None):
    """Build reusable inverse maps; call once per association/stream geometry."""
    source = calibration["frame"]
    target = target_geometry or source
    width, height = calibration["size"]
    if width * height > 16_000_000:
        raise ValueError("Rectified output is too large")
    xs, ys = np.meshgrid(np.arange(width, dtype=np.float32), np.arange(height, dtype=np.float32))
    pts = np.column_stack([xs.ravel(), ys.ravel()])
    # Process in strips to avoid large fisheye distortion allocations.
    out = np.empty((len(pts), 2), np.float32)
    for start in range(0, len(pts), 100_000):
        out[start:start+100_000] = project_rectified(pts[start:start+100_000], calibration, camera_profile, target)
    return out[:, 0].reshape(height, width), out[:, 1].reshape(height, width)
