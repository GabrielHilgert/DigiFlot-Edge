"""Detector diagnostics must reuse the same numerical method, with no plot IO."""
import base64
import json
import unittest

import cv2
import numpy as np

from lib.virtual_sensors.interface import detect_interface, normalized_config
from lib.vision.service import build_interface_diagnostic


class VirtualDiagnosticTests(unittest.TestCase):
    def assert_same_boundaries(self, baseline, detailed):
        for key in ("froth_surface_row_px", "pulp_froth_row_px",
                    "froth_surface_cm", "pulp_froth_interface_cm", "froth_thickness_cm"):
            self.assertEqual(baseline.get(key), detailed.get(key), key)
        self.assertEqual(baseline["valid"], detailed["valid"])

    def test_grayscale_profiles_share_exactly_the_measured_rows(self):
        rng = np.random.default_rng(101)
        image = rng.integers(20, 190, size=(90, 96), dtype=np.uint8)
        image[40:65] = 60
        config = normalized_config({"method": "mean_derivative", "entropy_radius": 3,
                                    "entropy_bins": 12, "resolution_px": 96,
                                    "sigma": 1.0, "min_row": 4})
        roi = [1., 2., 10.6, 11.]
        original = detect_interface(image, config, roi, 10.)
        detailed = detect_interface(image, config, roi, 10., diagnostics=True)
        self.assert_same_boundaries(original, detailed)
        data = detailed["_diagnostics"]
        self.assertEqual(data["entropy_map"].shape, image.shape)
        self.assertEqual(len(data["profiles"]["row_entropy"]), image.shape[0])
        self.assertEqual(len(data["profiles"]["row_derivative"]), image.shape[0])
        serializable = build_interface_diagnostic(image, detailed, roi, 123456789012345)
        self.assertEqual(serializable["image_size"], [96, 90])
        self.assertEqual(len(serializable["profiles"]["row_derivative"]["values"]), 90)
        self.assertGreater(len(base64.b64decode(serializable["image_jpeg_base64"])), 100)
        self.assertGreater(len(base64.b64decode(serializable["entropy_jpeg_base64"])), 100)
        json.dumps(serializable)

    def test_saved_hybrid_method_yields_global_entropy_and_striped_vote(self):
        rng = np.random.default_rng(32)
        image = rng.integers(50, 185, size=(120, 112, 3), dtype=np.uint8)
        image[20:45, :, :] = 178
        image[81:, :, :] = 39
        config = normalized_config({"method": "dual_entropy_hybrid",
                                    "selection_criteria": "hybrid",
                                    "simplification_alg": "turning_point",
                                    "dual_entropy_radius": 2, "dual_entropy_bins": 8,
                                    "texture_ksize": 7, "sigma_rows": 2,
                                    "min_thickness_px": 8, "n_stripes": 3,
                                    "min_valid_stripes": 2, "resolution_px": 112})
        roi = [0., 0., 11.2, 12.]
        original = detect_interface(image, config, roi, 10.)
        detailed = detect_interface(image, config, roi, 10., diagnostics=True)
        self.assert_same_boundaries(original, detailed)
        self.assertEqual(config["method"], "dual_entropy_hybrid")
        self.assertEqual(config["selection_criteria"], "hybrid")
        self.assertEqual(config["simplification_alg"], "turning_point")
        diagnostics = detailed["_diagnostics"]
        self.assertEqual(diagnostics["entropy_map"].shape, image.shape[:2])
        self.assertIn("upper_vote", diagnostics["profiles"])
        self.assertIn("lower_score", diagnostics["profiles"])
        payload = build_interface_diagnostic(image, detailed, roi, 123456789012345)
        self.assertIn("upper_vote", payload["profiles"])
        self.assertIn("lower_score", payload["profiles"])
        self.assertEqual(payload["image_size"], [112, 120])
        json.dumps(payload)


if __name__ == "__main__":
    unittest.main()
