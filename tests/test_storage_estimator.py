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
        self.assertEqual(result["video_bytes"], 240 * 10 * 64000)

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
        result = self.storage.estimate(self.experiment, [changed], lambda s: s["type"] == "flotation")
        self.assertEqual(result["cameras"][0]["source"], "history")
        self.assertEqual(result["video_bytes"], 240 * 20 * 10000)

    def test_crop_takes_precedence_over_stale_full_frame_size(self):
        camera = dict(self.camera, frame_size=[4056, 3040], crop_region=[80, 60, 800, 600], frame_rate=15)
        sig = self.storage.camera_signature(camera)
        self.assertEqual((sig["width"], sig["height"]), (800, 600))
        estimate = self.storage.estimate(self.experiment, [camera], lambda s: s["type"] == "flotation")
        self.assertEqual(estimate["cameras"][0]["bytes_per_frame"], 38400)

    def test_bootstrap_from_existing_video_metadata_without_decoding(self):
        root = Path(self.temp.name)
        run = root / "20260101_000000_test"
        (run / "cameras" / "C1").mkdir(parents=True)
        (run / "runtime.json").write_text('{"state":"Completed"}')
        (run / "config_snapshot.json").write_text(
            '{"output":{"quality":90},"cameras":[{"id":0,"frame_rate":15,'
            '"frame_size":[4056,3040],"crop_region":[0,0,800,600],'
            '"recording":{"output_type":"mp4"}}]}')
        video = run / "cameras" / "C1" / "segment.mp4"
        with video.open("wb") as handle:
            handle.truncate(3_000_000)
        (run / "cameras" / "C1" / "segment.mp4.json").write_text(
            '{"camera_id":0,"start_monotonic_ns":1000000000,"end_monotonic_ns":11000000000}')
        storage = StorageEstimator(root)
        camera = dict(self.camera, crop_region=[0, 0, 800, 600], frame_rate=20)
        result = storage.estimate(self.experiment, [camera], lambda s: s["type"] == "flotation")
        self.assertEqual(result["cameras"][0]["source"], "history")
        self.assertEqual(result["cameras"][0]["bytes_per_frame"], 20000)

    def test_legacy_fps_profile_is_migrated(self):
        import json
        root = Path(self.temp.name)
        file = root / "performance" / "storage_profiles.json"
        file.parent.mkdir(parents=True, exist_ok=True)
        old_sig = self.storage.camera_signature(self.camera)
        file.write_text(json.dumps({"version":1, "bootstrap_scanned":True,
            "cameras":{json.dumps(old_sig, sort_keys=True, separators=(",",":")):{
                "bytes_per_frame":15000,"samples":1}},
            "auxiliary":{"bytes_per_second":8192,"samples":0}}))
        storage = StorageEstimator(root)
        next_cam = dict(self.camera, frame_rate=15)
        result = storage.estimate(self.experiment, [next_cam], lambda s: s["type"] == "flotation")
        self.assertEqual(result["cameras"][0]["bytes_per_frame"], 15000)

    def test_transition_time_only_when_automatic(self):
        result = self.storage.estimate(self.experiment, [self.camera], lambda s: s["type"] == "flotation",
                                       auto_advance=True, transition_delay_s=5)
        self.assertEqual(result["experiment_duration_s"], 415)
        self.assertEqual(result["camera_recording_s"], 245)
        self.assertFalse(result["unplanned_transitions"])


if __name__ == "__main__":
    unittest.main()
