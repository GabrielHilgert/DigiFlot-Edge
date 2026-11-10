"""Hardware-free regression tests for froth-interface virtual sensor profiles."""
import tempfile
import unittest

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
