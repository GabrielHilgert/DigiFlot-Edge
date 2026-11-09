import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from lib.performance import PerformanceManager


class SystemTelemetryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        with patch.object(PerformanceManager, "sample_system", return_value=self.sample()):
            self.manager = PerformanceManager(
                {"performance": {"telemetry_interval_s": 1, "idle_telemetry_interval_s": 1}},
                self.root,
            )
        self.addCleanup(self.manager.stop_system_monitor)

    @staticmethod
    def sample():
        return {"timestamp": "2026-11-09T00:00:00+00:00", "temperature_c": 45.0,
                "load1": 0.1, "load5": 0.2, "load15": 0.3, "cpu_count": 4,
                "throttled": {"current": False, "raw": "0x0"},
                "disk": {"free_gb": 100.0, "used_gb": 2.0, "total_gb": 102.0}}

    def test_health_reads_cached_sample(self):
        with patch.object(self.manager, "sample_system", side_effect=AssertionError("Health sampled hardware")):
            self.assertEqual(self.manager.system_health()["system"]["temperature_c"], 45.0)
            self.assertEqual(self.manager.status["system"]["temperature_c"], 45.0)

    def test_telemetry_records_multiple_samples(self):
        self.manager.sample_system = self.sample
        self.manager.start_system_monitor()
        self.manager.start_experiment_telemetry(self.root / "run")
        time.sleep(1.3)
        self.manager.stop_experiment_telemetry()
        self.manager.stop_system_monitor()
        lines = (self.root / "run" / "system_metrics.tsv").read_text().strip().splitlines()
        self.assertGreaterEqual(len(lines), 3)
        self.assertEqual(lines[0].split("\t")[0], "timestamp")
        self.assertEqual(len(lines[1].split("\t")), 8)

    def test_configuration_updates_monitor_interval(self):
        self.manager.update_monitor_settings({
            "telemetry_interval_s": 12, "idle_telemetry_interval_s": 45,
            "min_disk_free_gb": 4, "storage_safety_margin_pct": 20,
        })
        health = self.manager.system_health()
        self.assertEqual(health["telemetry"]["experiment_interval_s"], 12)
        self.assertEqual(health["min_disk_free_gb"], 4)


if __name__ == "__main__":
    unittest.main()
