"""Hardware-free regression tests for froth-interface virtual sensor profiles."""
import tempfile
import unittest
from unittest.mock import patch

import cv2
import numpy as np

from lib.virtual_sensors.interface import DEFAULTS, METHODS, config_signature, detect_interface, normalized_config
from lib.vision.aruco import DEFAULT_LAYOUT, calibrate, source_geometry
from lib.vision.registry import VisionRegistry
from test_vision_aruco import synthetic_ruler


class VirtualInterfaceTests(unittest.TestCase):
    def test_config_defaults_and_ranges(self):
        conf = normalized_config()
        self.assertEqual(conf["method"], "mean_derivative")
        self.assertEqual(conf["resolution_px"], 320)
        self.assertEqual(len(METHODS), 6)
        with self.assertRaises(ValueError):
            normalized_config({"resolution_px": 5})
        with self.assertRaises(ValueError):
            normalized_config({"sampling_interval_s": 0})
        with self.assertRaises(ValueError):
            normalized_config({"method": "not_real"})
        with self.assertRaises(ValueError):
            normalized_config({"unknown_field": 1})

    def test_registry_profile_revision_and_camera_cell_isolation(self):
        with tempfile.TemporaryDirectory() as root:
            registry = VisionRegistry(root)
            cell = registry.save_cell({"name": "Virtual test"})
            image = synthetic_ruler()
            frame = source_geometry([900,920], [0,0,900,920])
            cal = calibrate(image, DEFAULT_LAYOUT, frame_geometry=frame)
            assoc = registry.save_association(1, cell["id"], cal)
            registry.save_analysis_roi(1, cell["id"], [2,2,12,17])
            initial = registry.virtual_profile(1, cell["id"])
            self.assertEqual(initial["source"], "default")
            config = normalized_config({"method": "heuristic_entropy", "resolution_px": 480})
            result = registry.save_virtual_profile(1, cell["id"], config)
            self.assertEqual(result["revision"], 1)
            self.assertEqual(registry.virtual_profile(1, cell["id"])["config"]["resolution_px"], 480)
            self.assertEqual(registry.virtual_profile(2, cell["id"])["source"], "default")
            result2 = registry.save_virtual_profile(1, cell["id"], config)
            self.assertEqual(result2["revision"], 2)
            assoc2 = registry.association(1, cell["id"])
            s1 = config_signature(config, assoc2, {"size": [640,480]})
            assoc2["analysis_roi_cm"] = [3,2,12,17]
            s2 = config_signature(config, assoc2, {"size": [640,480]})
            self.assertNotEqual(s1,s2)
            self.assertEqual(assoc["cell_id"], cell["id"])

    def test_bottom_height_and_top_depth_keep_camera_boundary_order(self):
        """Image rows grow downward; bottom heights grow upward, top depths grow downward."""
        img = np.zeros((100, 100, 3), dtype=np.uint8)
        config = normalized_config({"method": "dual_entropy", "resolution_px": 100})
        roi = [0., 2., 10., 12.]
        # Rows 20 and 60 imply physical ArUco Y=4 and Y=8 cm, respectively.
        detections = {"upper_row_px": 20, "lower_row_px": 60}
        with patch("lib.virtual_sensors.interface_detection.detect_dual_entropy_boundaries",
                   return_value=detections):
            bottom = detect_interface(img, config, roi, 10.,
                                      vertical_reference={"direction": "up", "y_cm": 10., "mode": "cell_bottom"})
            top = detect_interface(img, config, roi, 10.,
                                   vertical_reference={"direction": "down", "y_cm": 1., "mode": "cell_top"})
        self.assertTrue(bottom["valid"])
        self.assertEqual((bottom["froth_surface_cm"], bottom["pulp_froth_interface_cm"]), (6., 2.))
        self.assertGreater(bottom["froth_surface_cm"], bottom["pulp_froth_interface_cm"])
        self.assertTrue(all(bottom[key] >= 0 for key in ("froth_surface_cm", "pulp_froth_interface_cm")))
        self.assertEqual((top["froth_surface_cm"], top["pulp_froth_interface_cm"]), (3., 7.))
        self.assertLess(top["froth_surface_cm"], top["pulp_froth_interface_cm"])
        self.assertEqual(bottom["froth_thickness_cm"], 4.)
        self.assertEqual(top["froth_thickness_cm"], 4.)
        # Negative heights are meaningful BELOW the chosen reference, not a
        # plotting sign error; the UI must not silently take the absolute value.
        with patch("lib.virtual_sensors.interface_detection.detect_dual_entropy_boundaries",
                   return_value=detections):
            above_interface = detect_interface(img, config, roi, 10.,
                              vertical_reference={"direction":"up", "y_cm":5., "mode":"aruco_bottom"})
        self.assertEqual(above_interface["pulp_froth_interface_cm"], -3.)

    def test_grayscale_and_color_detectors_return_physical_fields(self):
        rng = np.random.default_rng(12)
        image = rng.integers(0,255,(96,128),dtype=np.uint8)
        image[35:61] = rng.integers(70,210,(26,128),dtype=np.uint8)
        image[61:] = 95
        roi = [-2.0, 4.0, 10.8, 13.6]
        for method in ("mean_derivative", "cumulative_distribution", "dual_entropy"):
            src = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR) if method == "dual_entropy" else image
            out = detect_interface(src, normalized_config({"method": method, "resolution_px":128}), roi, 10.0)
            self.assertIn("froth_surface_cm",out)
            self.assertIn("pulp_froth_interface_cm",out)
            self.assertIn("froth_thickness_cm",out)
            self.assertIsInstance(out["valid"],bool)
            if out["valid"]:
                self.assertGreater(out["froth_thickness_cm"], 0)

if __name__ == "__main__":
    unittest.main()
