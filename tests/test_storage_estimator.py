import tempfile
import unittest
from pathlib import Path
from lib.storage_estimator import StorageEstimator


class StorageEstimatorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.storage = StorageEstimator(Path(self.temp.name))
        self.camera = {"id": 0, "frame_size": [1000, 800], "frame_rate": 10, "recording": {"output_type": "mp4"}}
        self.experiment = {"stages": [
            {"type": "conditioning", "duration": 120},
            {"type": "flotation", "duration": 180},
            {"type": "flotation", "duration": 60},
            {"type": "conditioning", "duration": 40},
        ]}

    def estimate(self):
        return self.storage.estimate(self.experiment, [self.camera], lambda s: s["type"] == "flotation",
                                     min_free_gb=0, safety_margin_pct=0)

    def test_uses_stage_camera_policy(self):
        result = self.estimate()
        self.assertEqual(result["camera_recording_s"], 240)
        self.assertEqual(result["experiment_duration_s"], 400)
        self.assertEqual(result["video_bytes"], 240 * 10 * 400000)

    def test_works_without_history(self):
        self.assertEqual(self.estimate()["cameras"][0]["source"], "default")

    def test_training_updates_matched_camera_only(self):
        signature = self.storage.camera_signature(self.camera)
        self.storage.record_completed(Path(self.temp.name), [
            {"signature": signature, "frame_count": 10, "byte_count": 100000}
        ], 10)
        self.assertEqual(self.estimate()["cameras"][0]["source"], "history")
        self.assertEqual(self.estimate()["video_bytes"], 240 * 10 * 10000)
        changed = dict(self.camera, frame_rate=20)
        self.assertEqual(self.storage.estimate(self.experiment, [changed], lambda s: s["type"] == "flotation")["cameras"][0]["source"], "default")

    def test_transition_time_only_when_automatic(self):
        result = self.storage.estimate(self.experiment, [self.camera], lambda s: s["type"] == "flotation",
                                       auto_advance=True, transition_delay_s=5)
        self.assertEqual(result["experiment_duration_s"], 415)
        self.assertEqual(result["camera_recording_s"], 245)
        self.assertFalse(result["unplanned_transitions"])


if __name__ == "__main__":
    unittest.main()
