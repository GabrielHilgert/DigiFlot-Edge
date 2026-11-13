"""Froth-interface virtual sensor configuration and physical measurement contract.

The detection algorithms in interface_detection are shared by live acquisition,
the calibration benchmark and optional diagnostics; no parallel plot-only detector.
"""
from __future__ import annotations

import hashlib
import json
import math
from copy import deepcopy

import numpy as np

METHODS = ("mean_derivative", "cumulative_distribution", "heuristic_entropy",
           "dual_entropy", "dual_entropy_striped", "dual_entropy_hybrid")
COLOR_METHODS = frozenset(METHODS[3:])
DEFAULTS = {
    "schema_version": 1, "method": "mean_derivative", "resolution_px": 320,
    "detection_roi_cm": None, "height_reference_offset_cm": 10.0,
    "vertical_reference_mode": "cell_default", "vertical_reference_y_cm": None,
    "reference_id": None,
    "vertical_reference_confirmed": False,
    "sampling_interval_s": 1.0, "entropy_radius": 20, "entropy_bins": 32,
    "sigma": 1.0, "threshold_froth": 0.0, "threshold_pulp": 1.0,
    "min_row": 10, "cdf_foam": 0.5, "cdf_pulp": 0.8,
    "selection_criteria": "hybrid", "simplification_alg": "turning_point",
    "simplification_tol": 0.2,
    "x0_frac": .12, "x1_frac": .95, "min_y_frac": .18,
    "lower_search_start": .40, "lower_search_end": .92, "min_thickness_px": 25,
    "sigma_rows": 7.0, "dual_entropy_radius": 11, "dual_entropy_bins": 16,
    "texture_ksize": 21, "upper_threshold_q": 62., "lower_bias": 0.,
    "n_stripes": 7, "stripe_overlap": .40, "min_valid_stripes": 3,
    "vote_sigma_px": 12., "outlier_mad": 2.5,
}
LIMITS = {
    "resolution_px": (64, 1920), "sampling_interval_s": (.2, 60.),
    "height_reference_offset_cm": (-2000., 2000.),
    "entropy_radius": (1, 100), "entropy_bins": (2, 256),
    "sigma": (0.0, 100), "threshold_froth": (-5, 5), "threshold_pulp": (-5, 5),
    "min_row": (0, 2000), "cdf_foam": (0, 1), "cdf_pulp": (0, 1),
    "simplification_tol": (0, 100), "x0_frac": (0, 1), "x1_frac": (0, 1),
    "min_y_frac": (0, 1), "lower_search_start": (0, 1), "lower_search_end": (0, 1),
    "min_thickness_px": (1, 1000), "sigma_rows": (0, 100),
    "dual_entropy_radius": (1, 100), "dual_entropy_bins": (4, 64),
    "texture_ksize": (3, 201), "upper_threshold_q": (0, 100),
    "lower_bias": (-10, 10), "n_stripes": (3, 30),
    "stripe_overlap": (0, .9), "min_valid_stripes": (1, 30),
    "vote_sigma_px": (1, 100), "outlier_mad": (.1, 20),
}
OPTIONS = {
    "vertical_reference_mode": ("cell_default", "aruco_bottom", "cell_top", "cell_bottom", "historical_offset"),
    "selection_criteria": ("strong_candidates", "next_tp_after_pulp", "hybrid", "interpolate"),
    "simplification_alg": ("turning_point", "reumann_witkam", "douglas_peucker", "opheim", "lang"),
}


def normalized_config(values=None):
    config = deepcopy(DEFAULTS)
    if values is not None:
        if not isinstance(values, dict):
            raise ValueError("Detector configuration must be an object")
        unknown = set(values) - set(DEFAULTS)
        if unknown:
            raise ValueError("Unknown detector settings: " + ", ".join(sorted(unknown)))
        config.update(values)
    if config["method"] not in METHODS:
        raise ValueError("Unsupported detector method")
    for key, choices in OPTIONS.items():
        if config[key] not in choices:
            raise ValueError(f"Invalid {key}")
    for key, (lo, hi) in LIMITS.items():
        value = config[key]
        if isinstance(value, bool):
            raise ValueError(f"Invalid {key}")
        if key in {"resolution_px","entropy_radius","entropy_bins","min_row",
                   "min_thickness_px","dual_entropy_radius","dual_entropy_bins",
                   "texture_ksize","n_stripes","min_valid_stripes"}:
            if isinstance(value, float) and not value.is_integer():
                raise ValueError(f"{key} requires an integer")
            value = int(value)
        else:
            value = float(value)
        if not math.isfinite(value) or not lo <= value <= hi:
            raise ValueError(f"{key} outside permitted range [{lo}, {hi}]")
        config[key] = value
    value = config.get("vertical_reference_y_cm")
    if value not in (None, ""):
        try:
            value = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError("Reference Y must be a numeric centimetre coordinate") from exc
        if not math.isfinite(value) or abs(value) > 2000:
            raise ValueError("Reference Y must be finite and within ±2000 cm")
    else:
        value = None
    config["vertical_reference_y_cm"] = value
    ident = config.get("reference_id")
    if ident in (None, ""):
        config["reference_id"] = None
    elif not isinstance(ident, str) or len(ident) > 64 or not __import__("re").fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", ident):
        raise ValueError("Invalid named reference ID")
    if not isinstance(config["vertical_reference_confirmed"], bool):
        raise ValueError("Reference confirmation must be true or false")
    if config["x1_frac"] <= config["x0_frac"] or config["lower_search_end"] <= config["lower_search_start"]:
        raise ValueError("Invalid search window")
    roi = config.get("detection_roi_cm")
    if roi is not None:
        if not isinstance(roi, (tuple, list)) or len(roi) != 4:
            raise ValueError("Detection ROI must be four physical coordinates in centimetres")
        try:
            roi = [float(x) for x in roi]
        except (TypeError, ValueError) as exc:
            raise ValueError("Detection ROI must contain numeric coordinates") from exc
        if not all(math.isfinite(v) and abs(v) <= 2000 for v in roi):
            raise ValueError("Detection ROI coordinates must be finite and within the 20 m reference field")
        if roi[2] <= roi[0] or roi[3] <= roi[1]:
            raise ValueError("Detection ROI must have positive width and height")
        config["detection_roi_cm"] = roi
    return config


def detection_roi(config, association):
    """Dedicated physical sensor ROI; fall back to the former Cells ROI for old profiles."""
    roi = config.get("detection_roi_cm") if config else None
    roi = roi if roi is not None else association.get("analysis_roi_cm")
    if roi is None:
        raise ValueError("Select a Detection ROI before testing the virtual sensor")
    return [float(x) for x in roi]


def config_signature(config, association, camera_geometry=None):
    payload = {"config": normalized_config(config), "calibration_id": association["calibration_id"],
               "roi_cm": association.get("analysis_roi_cm"),
               "roi_revision": association.get("analysis_roi_revision"),
               "camera_revision": association.get("camera_revision"),
               "cell_revision": association.get("cell_revision"),
               "vertical_reference": association.get("cell_vertical_reference"),
               "reference_points": association.get("reference_points"),
               "geometry": camera_geometry}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


def detect_interface(image, config, roi_cm, px_per_cm, *, diagnostics=False, vertical_reference=None):
    """Return physical heights and validity without requiring plot IO."""
    conf = normalized_config(config)
    if not isinstance(image, np.ndarray) or image.ndim not in (2, 3):
        raise ValueError("Expected a grayscale or BGR ROI image")
    if image.size == 0 or not math.isfinite(px_per_cm) or px_per_cm <= 0:
        raise ValueError("Invalid ROI image or physical scale")
    from . import interface_detection as algorithms
    method = conf["method"]
    scale = image.shape[1] / max(1.0, conf["resolution_px"])
    # The configured parameters refer to the chosen ROI processing width.
    # When the processing width is re-negotiated, pixel kernels retain a
    # predictable physical footprint through this scale.
    scale = max(.05, scale)
    if method in COLOR_METHODS:
        if image.ndim != 3 or image.shape[2] != 3:
            raise ValueError("This method requires BGR color frames")
        kwargs = {
            "x0_frac": conf["x0_frac"], "x1_frac": conf["x1_frac"],
            "min_y_frac": conf["min_y_frac"],
            "lower_search_start": conf["lower_search_start"],
            "lower_search_end": conf["lower_search_end"],
            "min_thickness_px": max(1, round(conf["min_thickness_px"] * scale)),
            "sigma_rows": max(.1, conf["sigma_rows"] * scale),
            "entropy_radius": max(1, round(conf["dual_entropy_radius"] * scale)),
            "entropy_bins": conf["dual_entropy_bins"],
            "texture_ksize": max(3, round(conf["texture_ksize"] * scale)) | 1,
            "upper_threshold_q": conf["upper_threshold_q"], "lower_bias": conf["lower_bias"]}
        if method in {"dual_entropy_striped", "dual_entropy_hybrid"}:
            kwargs.update(n_stripes=conf["n_stripes"], stripe_overlap=conf["stripe_overlap"],
                          min_valid_stripes=conf["min_valid_stripes"],
                          vote_sigma_px=max(1, conf["vote_sigma_px"] * scale),
                          outlier_mad=conf["outlier_mad"])
        func = getattr(algorithms, {"dual_entropy": "detect_dual_entropy_boundaries",
                                "dual_entropy_striped": "detect_dual_entropy_striped_boundaries",
                                "dual_entropy_hybrid": "detect_dual_entropy_hybrid_boundaries"}[method])
        result = func(image, **kwargs, return_diagnostics=diagnostics)
        upper, lower = result["upper_row_px"], result["lower_row_px"]
        quality = {"valid_stripes": result.get("valid_stripes"), "combine_method": result.get("combine_method")}
    else:
        detector = algorithms.EntropyFoamDetector(px_per_cm=float(px_per_cm), origin_y_cm=float(roi_cm[1]))
        result = detector.entropy_foam_detection(
            image, method=method, entropy_radius=max(1, round(conf["entropy_radius"] * scale)),
            entropy_bins=conf["entropy_bins"], sigma=conf["sigma"] * scale,
            threshold_froth=conf["threshold_froth"], threshold_pulp=conf["threshold_pulp"],
            min_row=round(conf["min_row"] * scale), simplification_alg=conf["simplification_alg"],
            return_diagnostics=diagnostics,
            simplification_tol=conf["simplification_tol"], save_plot=False, show_plot=False,
            options={"cdf_foam":conf["cdf_foam"],"cdf_pulp":conf["cdf_pulp"],
                     "threshold_froth":conf["threshold_froth"],
                     "threshold_pulp":conf["threshold_pulp"],
                     "selection_criteria":conf["selection_criteria"]})
        upper, lower = result.froth_row_px, result.pulp_row_px
        quality = {}
    height = image.shape[0]
    def valid_row(x):
        try:
            n = float(x)
            return n if math.isfinite(n) and 0 <= n < height else None
        except (ValueError, TypeError):
            return None
    upper, lower = valid_row(upper), valid_row(lower)
    valid = upper is not None and lower is not None and lower > upper
    oy = float(roi_cm[1])
    if vertical_reference is None:
        from lib.vision.aruco import DEFAULT_LAYOUT
        from lib.vision.reference import resolve_vertical_reference
        vertical_reference = resolve_vertical_reference(conf, {"calibration": {"layout": DEFAULT_LAYOUT}})
    direction = vertical_reference["direction"]
    ref_y = vertical_reference.get("y_cm")
    offset = float(vertical_reference.get("offset_cm", 0.0))
    def position(row):
        if row is None:
            return None
        absolute_y = oy + row / px_per_cm
        if ref_y is None:
            return absolute_y + offset
        return absolute_y - ref_y if direction == "down" else ref_y - absolute_y
    output = {
        "froth_surface_cm": position(upper),
        "pulp_froth_interface_cm": position(lower),
        "vertical_reference": vertical_reference,
        "froth_thickness_cm": (lower - upper) / px_per_cm if valid else None,
        "froth_surface_row_px": upper, "pulp_froth_row_px": lower,
        "valid": bool(valid), "method": method, "quality": quality,
    }
    if diagnostics:
        source = result if method in COLOR_METHODS else result.diagnostics or {}
        output["_diagnostics"] = {
            "entropy_map": source.get("entropy_map"),
            "profiles": source.get("profiles") or {},
            "x_range_used": source.get("x_range_used", [0, image.shape[1]]),
            "method": method,
        }
    return output
