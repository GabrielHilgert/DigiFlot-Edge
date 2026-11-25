"""Non-destructive Cells workspace lifecycle and relative calibration regression."""
import tempfile
import unittest

from lib.vision.registry import VisionRegistry
from lib.vision.relative import relative_scale


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.registry = VisionRegistry(self.temp.name)
        self.cell = self.registry.save_cell({"name": "4L", "geometry": {
            "shape": "rectangular", "height_mm": 160, "width_mm": 100, "depth_mm": 80}})
        eye = [[1., 0., 0.], [0., 1., 0.], [0., 0., 1.]]
        self.association = self.registry.save_association(1, self.cell["id"], {
            "H": eye, "H_inv": eye, "frame": {"size": [800, 600], "sensor_crop": [0, 0, 800, 600]},
            "rms_px": 0.2, "px_per_cm": 80., "size": [800, 600]})

    def test_rename_keeps_id_revision_and_confirmed_aruco(self):
        renamed = self.registry.rename_cell(self.cell["id"], "Renamed 4L")
        self.assertEqual(renamed["id"], self.cell["id"])
        self.assertEqual(renamed["revision"], self.cell["revision"])
        self.assertEqual(self.registry.association(1, self.cell["id"])["calibration_id"],
                         self.association["calibration_id"])
        self.assertEqual(self.registry.get_cell(self.cell["id"])["name"], "Renamed 4L")

    def test_archive_is_reversible_and_never_deletes_camera_history(self):
        item = self.registry.archive_cell(self.cell["id"], True)
        self.assertTrue(item["archived"])
        self.assertFalse(any(c["id"] == self.cell["id"] for c in self.registry.list_cells()))
        self.assertTrue(self.registry.get_cell(self.cell["id"])["archived"])
        self.assertEqual(len(self.registry.list_cells(include_archived=True)), 1)
        with self.assertRaisesRegex(RuntimeError, "camera calibration history"):
            self.registry.delete_empty_cell(self.cell["id"])
        self.registry.archive_cell(self.cell["id"], False)
        self.assertEqual(self.registry.list_cells()[0]["id"], self.cell["id"])

    def test_empty_archived_draft_can_be_deleted(self):
        cell = self.registry.save_cell({"name": "Draft"})
        with self.assertRaisesRegex(RuntimeError, "Archive"):
            self.registry.delete_empty_cell(cell["id"])
        self.registry.archive_cell(cell["id"])
        self.assertTrue(self.registry.delete_empty_cell(cell["id"])["deleted"])
        with self.assertRaises(KeyError):
            self.registry.get_cell(cell["id"])

    def test_relative_calibration_is_distinct_from_aruco_and_overrides_nominal(self):
        values = {"source_camera_id": 1, "reference_field": "width_mm",
                  "target_field": "depth_mm", "frame_size": [800, 600],
                  "image_space": "raw", "reference_pair": [[.1, .2], [.5, .2]],
                  "target_pair": [[.2, .2], [.2, .4]]}
        relative = self.registry.save_relative_calibration(2, self.cell["id"], values)
        self.assertAlmostEqual(relative["reference_mm"], 100)
        self.assertAlmostEqual(relative["target_mm"], 37.5)
        self.assertEqual(relative["source_aruco_calibration_id"], self.association["calibration_id"])
        result = self.registry.get_cell(self.cell["id"])
        self.assertEqual(result["relative_measurements"][0]["valid"], True)
        self.assertEqual(result["resolved_dimensions"]["dimensions"]["depth_mm"]["source"], "relative_estimate")
        self.assertAlmostEqual(result["resolved_dimensions"]["dimensions"]["depth_mm"]["value_mm"], 37.5)
        self.assertEqual(self.registry.association(1, self.cell["id"])["revision"], 1)
        self.assertIsNone(self.registry.association(2, self.cell["id"]))
        self.registry.rename_cell(self.cell["id"], "Still valid after rename")
        self.assertTrue(self.registry.get_cell(self.cell["id"])["relative_measurements"][0]["valid"])
        self.registry.save_camera_profile(2, {"roi_norm": [.1, .1, .9, .9]})
        updated = self.registry.get_cell(self.cell["id"])
        self.assertFalse(updated["relative_measurements"][0]["valid"])
        self.assertEqual(updated["resolved_dimensions"]["dimensions"]["depth_mm"]["source"], "nominal")

    def test_reference_observation_is_separate_from_aruco_physical_coordinates(self):
        initial=self.registry.get_cell(self.cell["id"])
        revision=initial["reference_points_revision"]
        saved=self.registry.save_reference_observation(self.cell["id"], 2, {
            "reference_id":"cell_bottom", "position_norm":[.3,.8], "frame_size":[800,600],
            "image_space":"undistorted", "expected_revision":0})
        self.assertEqual(saved["revision"], 1)
        cell=self.registry.get_cell(self.cell["id"])
        self.assertEqual(cell["reference_points_revision"], revision)
        self.assertEqual(cell["reference_observations"]["2"]["observations"]["cell_bottom"]["position_norm"], [.3,.8])
        self.assertIsNone(self.registry.association(2,self.cell["id"]))
        self.assertEqual(self.registry.association(1,self.cell["id"])["calibration_id"],
                         self.association["calibration_id"])
        self.registry.archive_cell(self.cell["id"])
        with self.assertRaises(RuntimeError):
            self.registry.delete_empty_cell(self.cell["id"])
        with self.assertRaisesRegex(RuntimeError,"another tab"):
            self.registry.save_reference_observation(self.cell["id"], 2, {
                "reference_id":"cell_top", "position_norm":[.3,.2],
                "frame_size":[800,600], "expected_revision":0})

    def test_invalid_relative_input_is_rejected(self):
        values = {"reference_field": "width_mm", "target_field": "depth_mm",
                  "frame_size": [800, 600], "image_space": "raw",
                  "reference_pair": [[.2, .2], [.2, .2]],
                  "target_pair": [[.1, .1], [.2, .2]]}
        with self.assertRaisesRegex(ValueError, "too close"):
            relative_scale(values, 100, self.registry.camera_profile(2))
        values["reference_pair"] = [[.1, .2], [.5, .2]]
        values["target_field"] = "width_mm"
        with self.assertRaisesRegex(ValueError, "different dimension"):
            relative_scale(values, 100, self.registry.camera_profile(2))


if __name__ == "__main__":
    unittest.main()
