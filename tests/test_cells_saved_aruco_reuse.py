"""Marker-free reuse must preserve saved ArUco history and reject changed geometry."""
import tempfile
import threading
import unittest
from lib.vision.service import VisionService


class FakeDigiFlot:
    IDLE = "Idle"
    def __init__(self):
        self.execution_locked = False
        self.recording = False
        self.lock = threading.RLock()
        self.virtual_camera_id = None
        self.cell_profile = None
        self.cameras = {}


class ReuseSavedArUcoTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.service = VisionService(FakeDigiFlot(), self.temp.name)
        self.cell = self.service.registry.save_cell({"name": "Cell", "geometry": {
            "shape": "rectangular", "height_mm": 160}})
        eye = [[1., 0., 0.], [0., 1., 0.], [0., 0., 1.]]
        self.first = self.service.registry.save_association(1, self.cell["id"], {
            "H": eye, "H_inv": eye, "frame": {"size": [800, 600], "sensor_crop": [0, 0, 800, 600]},
            "rms_px": .1, "size": [800, 600]})

    def test_existing_calibration_reused_after_nominal_change(self):
        self.service.registry.save_cell({"id": self.cell["id"], "name": "Cell", "geometry": {
            "shape": "rectangular", "height_mm": 165}})
        with self.assertRaisesRegex(ValueError, "Confirm"):
            self.service.reuse_confirmed_aruco(1, self.cell["id"], {})
        current = self.service.reuse_confirmed_aruco(1, self.cell["id"], {"ruler_unchanged": True})
        self.assertEqual(current["revision"], 2)
        self.assertEqual(current["calibration"], self.first["calibration"])
        self.assertEqual(current["cell_revision"], 2)
        old_file = self.service.registry.root / "associations" / f"1__{self.cell['id']}" / "history" / (
            self.first["calibration_id"] + ".json")
        self.assertTrue(old_file.exists())
        self.assertEqual(self.service.reuse_confirmed_aruco(1, self.cell["id"],
                         {"ruler_unchanged": True})["revision"], 2)

    def test_changed_marker_layout_cannot_revalidate_blindly(self):
        self.service.registry.save_cell({"id": self.cell["id"], "name": "Cell",
                                         "marker_layout": {"marker_ids": [5, 6, 7]}})
        with self.assertRaisesRegex(ValueError, "ruler dimensions"):
            self.service.reuse_confirmed_aruco(1, self.cell["id"], {"ruler_unchanged": True})
        self.assertEqual(self.service.registry.association(1, self.cell["id"])["revision"], 1)

    def test_changed_optics_cannot_revalidate_blindly(self):
        self.service.registry.save_camera_profile(1, {"optics": {"mode": "preset", "preset": "leve"}})
        with self.assertRaisesRegex(ValueError, "optical geometry"):
            self.service.reuse_confirmed_aruco(1, self.cell["id"], {"ruler_unchanged": True})


if __name__ == "__main__":
    unittest.main()
