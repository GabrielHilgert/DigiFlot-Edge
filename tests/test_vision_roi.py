"""Hardware-free tests for the full-plane preview and optimized physical ROI path."""
import tempfile
import unittest

import cv2
import numpy as np

from lib.vision.aruco import DEFAULT_LAYOUT, calibrate, source_geometry
from lib.vision.registry import VisionRegistry
from lib.vision.roi import compile_roi_maps, full_plane_geometry, remap_roi, remap_yuv420_roi
from test_vision_aruco import synthetic_ruler


class PhysicalRoiTests(unittest.TestCase):
    def setUp(self):
        self.image = synthetic_ruler()
        self.geometry = source_geometry([900, 920], [0, 0, 900, 920])
        self.calibration = calibrate(self.image, DEFAULT_LAYOUT, frame_geometry=self.geometry)
        self.profile = {"optics": {"mode": "none"}}

    def test_full_plane_extends_beyond_marker_bounds(self):
        plane = full_plane_geometry(self.calibration, self.profile, self.geometry)
        self.assertGreater(plane["size"][0], self.calibration["size"][0])
        self.assertGreater(plane["size"][1], self.calibration["size"][1])
        self.assertLessEqual(plane["size"][0], 1600)
        self.assertLessEqual(plane["size"][1], 1200)
        bounds = [*plane["min_xy_cm"], *plane["max_xy_cm"]]
        maps = compile_roi_maps(self.calibration, self.profile, self.geometry, bounds,
                                px_per_cm=plane["px_per_cm"], output_size=plane["size"],
                                max_pixels=2_000_000)
        preview = remap_roi(self.image, maps)
        self.assertEqual(preview.shape[::-1], tuple(plane["size"]))
        self.assertGreater(maps["coverage"], 0.5)

    def test_roi_map_crops_input_and_preserves_pixels(self):
        maps = compile_roi_maps(self.calibration, self.profile, self.geometry, [2, 2, 10, 10])
        patch = remap_roi(self.image, maps)
        self.assertEqual(patch.ndim, 2)
        self.assertGreater(maps["coverage"], 0.99)
        self.assertEqual(patch.shape, tuple(maps["size"][::-1]))
        x0, y0, x1, y1 = maps["source_bbox"]
        self.assertLess((x1 - x0) * (y1 - y0), self.image.size)
        colored = cv2.cvtColor(self.image, cv2.COLOR_GRAY2BGR)
        self.assertEqual(remap_roi(colored, maps).shape[:2], patch.shape)

    def test_yuv420_color_crop_matches_full_frame_conversion(self):
        maps = compile_roi_maps(self.calibration, self.profile, self.geometry, [2, 2, 10, 10])
        source_bgr = cv2.cvtColor(self.image, cv2.COLOR_GRAY2BGR)
        yuv = cv2.cvtColor(source_bgr, cv2.COLOR_BGR2YUV_I420)
        full_bgr = cv2.cvtColor(yuv, cv2.COLOR_YUV2BGR_I420)
        expected = remap_roi(full_bgr, maps)
        actual = remap_yuv420_roi(yuv, maps, self.geometry["size"])
        self.assertEqual(actual.shape, expected.shape)
        self.assertLess(np.mean(np.abs(actual.astype(np.float32) - expected.astype(np.float32))), 2)

    def test_maps_reject_invalid_roi_and_excessive_allocation(self):
        for coords in ([3, 4, 3, 5], [2, 5, 4, 2], [np.nan, 0, 1, 1]):
            with self.assertRaises(ValueError):
                compile_roi_maps(self.calibration, self.profile, self.geometry, coords)
        with self.assertRaises(ValueError):
            compile_roi_maps(self.calibration, self.profile, self.geometry, [0, 0, 500, 500])

    def test_selection_persists_across_recalibration_without_rewriting_history(self):
        with tempfile.TemporaryDirectory() as root:
            store = VisionRegistry(root)
            cell = store.save_cell({"name": "ROI test cell"})
            first = store.save_association(1, cell["id"], self.calibration)
            selection = [2.5, 3.0, 12.0, 15.0]
            result = store.save_analysis_roi(1, cell["id"], selection)
            self.assertEqual(result["revision"], 1)
            self.assertEqual(store.association(1, cell["id"])["analysis_roi_cm"], selection)
            second = store.save_association(1, cell["id"], self.calibration)
            self.assertNotEqual(first["calibration_id"], second["calibration_id"])
            self.assertEqual(store.association(1, cell["id"])["analysis_roi_cm"], selection)
            self.assertIsNone(store.save_analysis_roi(1, cell["id"], None)["roi_cm"])
            self.assertIsNone(store.association(1, cell["id"])["analysis_roi_cm"])

    def test_roi_requires_calibration(self):
        with tempfile.TemporaryDirectory() as root:
            store = VisionRegistry(root)
            cell = store.save_cell({"name": "Uncalibrated"})
            with self.assertRaises(KeyError):
                store.save_analysis_roi(1, cell["id"], [1, 1, 2, 2])


if __name__ == "__main__":
    unittest.main()
