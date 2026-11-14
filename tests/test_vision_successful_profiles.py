"""HIFIE benchmark approval is global per real sensor configuration, not per experiment."""
import hashlib
import json
import tempfile
import unittest

from lib.vision.registry import VisionRegistry, _write
from lib.virtual_sensors.interface import normalized_config


class SuccessfulHifieProfilesTest(unittest.TestCase):
    def test_global_profiles_survive_restart_and_independent_calibration_ids(self):
        with tempfile.TemporaryDirectory() as root:
            registry = VisionRegistry(root)
            crop, roi = [0, 0, 2028, 1520], [1., 2., 10., 12.]
            config = normalized_config({"method":"dual_entropy_hybrid", "resolution_px":256,
                                        "detection_roi_cm":roi, "sampling_interval_s":.5})
            first = registry.remember_successful_virtual_profile(
                0, "cell_1", crop, "cal_first_run", roi, .5, config,
                signature="runtime-signature-first", benchmark={"passed":True, "p95_ms":25.})
            self.assertEqual(first["schema_version"], 3)
            self.assertIsNotNone(registry.matching_successful_virtual_profile(
                0, "cell_1", crop, roi, .5, config))
            self.assertEqual(len(registry.successful_virtual_profiles(0, "cell_1", crop)), 1)
            self.assertFalse(registry.successful_virtual_profiles(0, "cell_2", crop))
            self.assertFalse(registry.successful_virtual_profiles(0, "cell_1", [0, 2, 2028, 1520]))

            # New experiment, freshly confirmed ArUco, same physical camera and detector:
            # no test or new record is required and even old implementation hashes may differ.
            fresh = VisionRegistry(root)
            match = fresh.matching_successful_virtual_profile(0, "cell_1", crop, roi, .5, config)
            self.assertEqual(match["id"], first["id"])
            self.assertEqual(match["benchmark"]["p95_ms"], 25.)

            repeated = registry.remember_successful_virtual_profile(
                0, "cell_1", crop, "cal_second_run", roi, .5, config,
                signature="different-runtime-signature", benchmark={"passed":True, "p95_ms":19.})
            self.assertEqual(repeated["id"], first["id"])
            self.assertEqual(len(registry.successful_virtual_profiles(0, "cell_1", crop)), 1)
            self.assertEqual(registry.matching_successful_virtual_profile(
                0, "cell_1", crop, roi, .5, config)["benchmark"]["p95_ms"], 19.)

    def test_distinct_settings_keep_their_own_last_success(self):
        with tempfile.TemporaryDirectory() as root:
            registry = VisionRegistry(root)
            crop, roi = [0,0,1920,1080], [1.,2.,8.,10.]
            config = normalized_config({"sampling_interval_s":.5, "detection_roi_cm":roi})
            def passed(conf, crop_value=crop, roi_value=roi):
                return registry.remember_successful_virtual_profile(
                    0, "cell_1", crop_value, "cal_1", roi_value, conf["sampling_interval_s"],
                    conf, signature="verified", benchmark={"passed":True})
            first = passed(config)
            tuned = normalized_config({**config, "entropy_radius":21})
            second = passed(tuned)
            slower = normalized_config({**config, "sampling_interval_s":1.})
            third = passed(slower)
            new_roi = [2.,3.,8.,9.]
            shifted = normalized_config({**config, "detection_roi_cm":new_roi})
            fourth = passed(shifted, roi_value=new_roi)
            self.assertEqual(len({first["id"],second["id"],third["id"],fourth["id"]}), 4)
            self.assertEqual(len(registry.successful_virtual_profiles(0, "cell_1", crop)), 4)
            for conf, roi_value in [(config,roi),(tuned,roi),(slower,roi),(shifted,new_roi)]:
                self.assertIsNotNone(registry.matching_successful_virtual_profile(
                    0, "cell_1", crop, roi_value, conf["sampling_interval_s"], conf))
            self.assertIsNone(registry.matching_successful_virtual_profile(
                0, "cell_1", [1,0,1920,1080], roi, .5, config))
            self.assertIsNone(registry.matching_successful_virtual_profile(
                1, "cell_1", crop, roi, .5, config))
            self.assertIsNone(registry.matching_successful_virtual_profile(
                0, "cell_2", crop, roi, .5, config))

    def test_existing_signed_schema_two_profiles_are_reused_across_experiments(self):
        with tempfile.TemporaryDirectory() as root:
            registry = VisionRegistry(root)
            crop, roi = [0,0,1920,1080], [1.,2.,8.,10.]
            config = normalized_config({"sampling_interval_s":.5, "detection_roi_cm":roi})
            context = registry._successful_virtual_context(0, "cell_1", crop, roi, .5)
            context["calibration_id"] = "old_arucos"
            old_key = hashlib.sha256(json.dumps(context, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
            folder = registry.root / "virtual_sensors" / "froth_interface" / "successful"
            _write(folder / f"{old_key}.json", {"schema_version":2, "context":context, "config":config,
                "signature":"old-full-signature", "tested_at":"2026-11-14T18:00:00Z",
                "benchmark":{"passed":True, "samples":20}})
            fresh = VisionRegistry(root)
            match = fresh.matching_successful_virtual_profile(0, "cell_1", crop, roi, .5, config)
            self.assertEqual(match["id"], old_key)
            self.assertEqual(match["benchmark"]["samples"], 20)
            self.assertEqual(match["context"]["calibration_id"], "old_arucos")

    def test_unsigned_legacy_and_drafts_never_count_as_benchmarks(self):
        with tempfile.TemporaryDirectory() as root:
            registry = VisionRegistry(root)
            crop, roi = [0,0,1920,1080], [1.,2.,8.,10.]
            config = normalized_config({"sampling_interval_s":.5, "detection_roi_cm":roi})
            registry.remember_successful_virtual_profile(0, "cell_1", crop, "cal_1", roi, .5, config)
            self.assertIsNone(registry.matching_successful_virtual_profile(0, "cell_1", crop, roi, .5, config))
            self.assertIsNone(registry.matching_successful_virtual_profile(
                0, "cell_1", crop, roi, .5, normalized_config({**config, "entropy_radius":18})))


if __name__ == "__main__":
    unittest.main()
