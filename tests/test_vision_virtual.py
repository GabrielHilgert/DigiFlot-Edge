"""Hardware-independent validation of virtual sensor profiles and physical provenance."""
import tempfile
import unittest

import numpy as np

from lib.vision.registry import VisionRegistry
from lib.virtual_sensors.interface import DEFAULTS, config_signature, detect_interface, detection_roi, normalized_config


class VirtualSensorTests(unittest.TestCase):
    def test_parameters_validate_and_defaults_remain_immutable(self):
        config = normalized_config({"resolution_px": 256, "sampling_interval_s": 0.5})
        self.assertEqual(config["method"], "mean_derivative")
        self.assertEqual(DEFAULTS["resolution_px"], 320)
        for change in ({"resolution_px": 0}, {"sampling_interval_s": -1},
                       {"method": "not-a-detector"}, {"entropy_bins": 300},
                       {"unknown_key": 12}, {"x0_frac": .9, "x1_frac": .2},
                       {"detection_roi_cm": [1,2,1,4]}, {"detection_roi_cm": [0,0,1]},
                       {"detection_roi_cm": [0,float("nan"),3,5]},
                       {"height_reference_offset_cm": 99999}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                normalized_config(change)

    def test_gray_detector_returns_physical_schema_without_plot_io(self):
        # Controlled texture steps exercise the image-in-memory interface.
        rng = np.random.default_rng(12)
        img = np.full((90, 80), 75, dtype=np.uint8)
        img[24:62] = rng.integers(40, 210, size=(38, 80), dtype=np.uint8)
        img[62:] = 24
        conf = normalized_config({"entropy_radius": 2, "entropy_bins": 8,
                                  "resolution_px": 80, "sigma": 1.0})
        result = detect_interface(img, conf, [0., 5., 8., 14.], px_per_cm=10.)
        self.assertEqual(result["method"], "mean_derivative")
        self.assertIn("froth_surface_cm", result)
        self.assertIn("pulp_froth_interface_cm", result)
        self.assertIn("valid", result)
        if result["froth_surface_row_px"] is not None:
            self.assertAlmostEqual(result["froth_surface_cm"],
                                   15. + result["froth_surface_row_px"] / 10.)
        self.assertEqual(result["height_reference_offset_cm"], 10.)
        zero = detect_interface(img, {**conf, "height_reference_offset_cm": 0.}, [0., 5., 8., 14.], 10.)
        self.assertEqual(result["froth_thickness_cm"], zero["froth_thickness_cm"])
        for key in ("froth_surface_cm","pulp_froth_interface_cm"):
            if zero[key] is not None:
                self.assertAlmostEqual(result[key]-zero[key], 10.)

    def test_per_camera_cell_defaults_profiles_and_signatures(self):
        cal = {"H": np.eye(3).tolist(), "H_inv": np.eye(3).tolist(),
               "frame": {"size": [200, 200], "sensor_crop": [0, 0, 200, 200]},
               "rms_px": 0., "min_xy_cm": [0, 0], "px_per_cm": 10., "size": [200, 200]}
        with tempfile.TemporaryDirectory() as directory:
            store = VisionRegistry(directory)
            a = store.save_cell({"name": "Cell A"})
            b = store.save_cell({"name": "Cell B"})
            store.save_association(1, a["id"], cal)
            store.save_association(1, b["id"], cal)
            self.assertEqual(store.virtual_profile(1, a["id"])["source"], "default")
            self.assertEqual(store.virtual_profile(1, b["id"])["config"]["resolution_px"], 320)
            saved = store.save_virtual_profile(1, a["id"], {"resolution_px": 256})
            self.assertEqual(saved["revision"], 1)
            self.assertEqual(store.virtual_profile(1, a["id"])["config"]["resolution_px"], 256)
            self.assertEqual(store.virtual_profile(1, b["id"])["config"]["resolution_px"], 320)
            store.save_analysis_roi(1, a["id"], [1, 1, 6, 8])
            first = store.association(1, a["id"])
            sig1 = config_signature(saved["config"], first, {"lores": [640, 480]})
            store.save_analysis_roi(1, a["id"], [1, 2, 6, 8])
            second = store.association(1, a["id"])
            self.assertNotEqual(sig1, config_signature(saved["config"], second, {"lores": [640, 480]}))
            self.assertNotEqual(sig1, config_signature(saved["config"], first, {"lores": [320, 240]}))
            store.save_association(1, a["id"], cal)
            self.assertEqual(store.virtual_profile(1, a["id"])["config"]["resolution_px"], 256)
            # The sensor ROI is independent of the pre-existing Cells ROI.
            selected = [-3., -4., 5., 9.]
            updated = store.save_virtual_profile(1, a["id"], {
                **store.virtual_profile(1, a["id"])["config"],
                "method": "dual_entropy_hybrid", "detection_roi_cm": selected,
                "height_reference_offset_cm": 10.})
            self.assertEqual(updated["config"]["detection_roi_cm"], selected)
            self.assertEqual(detection_roi(updated["config"], store.association(1,a["id"])),selected)
            self.assertEqual(store.association(1,a["id"])["analysis_roi_cm"], [1,2,6,8])
            self.assertIsNone(store.virtual_profile(1,b["id"])["config"]["detection_roi_cm"])
            old_sig = config_signature(saved["config"], first)
            self.assertNotEqual(old_sig, config_signature(updated["config"], first))


if __name__ == "__main__":
    unittest.main()
