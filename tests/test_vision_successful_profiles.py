"""Passing HIFIE presets survive restarts and are keyed by camera, crop, ROI and acquisition rate."""
import tempfile
import unittest

from lib.vision.registry import VisionRegistry
from lib.virtual_sensors.interface import normalized_config


class SuccessfulHifieProfilesTest(unittest.TestCase):
    def test_matching_context_and_independent_combinations(self):
        with tempfile.TemporaryDirectory() as root:
            registry = VisionRegistry(root)
            crop = [0, 0, 2028, 1520]
            roi = [1., 2., 10., 12.]
            conf = normalized_config({"method": "dual_entropy_hybrid", "resolution_px": 256,
                                      "detection_roi_cm": roi, "sampling_interval_s": .5})
            item = registry.remember_successful_virtual_profile(
                0, "cell_1", crop, "cal_0001", roi, .5, conf)
            self.assertEqual(len(registry.successful_virtual_profiles(0, "cell_1", crop, "cal_0001")), 1)
            self.assertEqual(item["config"]["method"], "dual_entropy_hybrid")
            self.assertFalse(registry.successful_virtual_profiles(0, "cell_2", crop, "cal_0001"))
            self.assertFalse(registry.successful_virtual_profiles(0, "cell_1", crop, "cal_0002"))
            self.assertFalse(registry.successful_virtual_profiles(0, "cell_1", [4, 0, 2028, 1520], "cal_0001"))

            # A new passed rate or ROI is retained separately, not overwritten.
            slower = normalized_config({**conf, "sampling_interval_s": 1.})
            registry.remember_successful_virtual_profile(0, "cell_1", crop, "cal_0001", roi, 1., slower)
            another_roi = [2., 3., 8., 9.]
            moved = normalized_config({**conf, "detection_roi_cm": another_roi})
            registry.remember_successful_virtual_profile(0, "cell_1", crop, "cal_0001", another_roi, .5, moved)
            entries = registry.successful_virtual_profiles(0, "cell_1", crop, "cal_0001")
            self.assertEqual(len(entries), 3)
            self.assertEqual({item["context"]["sampling_interval_s"] for item in entries}, {.5, 1.})
            self.assertEqual(len({tuple(item["context"]["detection_roi_cm"]) for item in entries}), 2)

            # Retesting the same physical configuration updates its last success only.
            newer = normalized_config({**conf, "entropy_radius": 18})
            replacement = registry.remember_successful_virtual_profile(
                0, "cell_1", crop, "cal_0001", roi, .5, newer)
            self.assertEqual(replacement["id"], item["id"])
            self.assertEqual(len(registry.successful_virtual_profiles(0, "cell_1", crop, "cal_0001")), 3)
            fresh = VisionRegistry(root)
            recovered = fresh.successful_virtual_profiles(0, "cell_1", crop, "cal_0001")
            self.assertEqual(len(recovered), 3)
            self.assertEqual(next(x for x in recovered if x["id"] == item["id"])["config"]["entropy_radius"], 18)


    def test_legacy_record_is_not_reusable_without_verified_signature(self):
        with tempfile.TemporaryDirectory() as root:
            registry = VisionRegistry(root)
            crop, roi = [0, 0, 1920, 1080], [1., 2., 8., 10.]
            config = normalized_config({"sampling_interval_s": .5, "detection_roi_cm": roi})
            registry.remember_successful_virtual_profile(0, "cell_1", crop, "cal_1", roi, .5, config)
            self.assertIsNone(registry.matching_successful_virtual_profile(
                0, "cell_1", crop, "cal_1", roi, .5, config, "signature-123"))
            registry.remember_successful_virtual_profile(
                0, "cell_1", crop, "cal_1", roi, .5, config,
                signature="signature-123", benchmark={"passed": True, "p95_ms": 25.})
            record = registry.matching_successful_virtual_profile(
                0, "cell_1", crop, "cal_1", roi, .5, config, "signature-123")
            self.assertIsNotNone(record)
            self.assertEqual(record["benchmark"]["p95_ms"], 25.)
            self.assertIsNone(registry.matching_successful_virtual_profile(
                0, "cell_1", crop, "cal_1", roi, .5, config, "signature-456"))
            self.assertIsNone(registry.matching_successful_virtual_profile(
                0, "cell_1", crop, "cal_1", roi, .5,
                normalized_config({**config, "entropy_radius": 21}), "signature-123"))
            self.assertIsNone(registry.matching_successful_virtual_profile(
                0, "cell_1", crop, "cal_1", roi, .25, config, "signature-123"))
            fresh = VisionRegistry(root)
            self.assertIsNotNone(fresh.matching_successful_virtual_profile(
                0, "cell_1", crop, "cal_1", roi, .5, config, "signature-123"))

    def test_draft_is_not_a_successful_profile(self):
        with tempfile.TemporaryDirectory() as root:
            registry = VisionRegistry(root)
            # The normal draft file is separate from the passing benchmark directory.
            self.assertEqual(registry.successful_virtual_profiles(1, "cell_1", [0,0,100,100], "cal_1"), [])
            self.assertFalse((registry.root / "virtual_sensors" / "froth_interface" / "successful").exists())


if __name__ == "__main__":
    unittest.main()
