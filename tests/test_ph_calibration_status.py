"""Atlas EZO pH calibration parsing and non-hardware regressions."""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from lib.atlasScientific import AtlasScientific


class AtlasPhCalibrationStatusTests(unittest.TestCase):
    def setUp(self):
        self.device = AtlasScientific(sensors=[{"type": "pH", "name": "pH", "address": 99}])

    def test_chip_reports_zero_through_three_calibration_points(self):
        for count in range(4):
            for response in (f"?CAL,{count}", f"Cal,{count}", f"{count}", f"?Cal, {count}\r"):
                with self.subTest(response=response):
                    with patch.object(self.device, "query", return_value=response):
                        status = self.device.ph_calibration_status("pH")
                    self.assertEqual(status["points"], count)

    def test_unrecognized_response_is_not_treated_as_calibrated(self):
        for response in ("garbage3", "?CAL,9", "", "CAL,2,other"):
            with patch.object(self.device, "query", return_value=response):
                self.assertIsNone(self.device.ph_calibration_status("pH")["points"])

    def test_non_ph_sensor_is_rejected(self):
        other = AtlasScientific(sensors=[{"type": "ORP", "name": "ORP", "address": 98}])
        with self.assertRaises(ValueError):
            other.ph_calibration_status("ORP")


if __name__ == "__main__":
    unittest.main()
