"""Tests for optional, trusted local plugins and the synthetic sensor template."""
import tempfile
import time
import unittest
from pathlib import Path
from lib.plugins import PluginCatalog

ROOT = Path(__file__).resolve().parents[1] / "src" / "plugins"


def wait(predicate, timeout=3.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return True
        time.sleep(.03)
    return False


class PluginTests(unittest.TestCase):
    def test_demo_plugin_is_disabled_by_default(self):
        catalog = PluginCatalog(ROOT, {})
        listing = {item["id"]: item for item in catalog.list_installed()}
        self.assertIn("test_sensor", listing)
        self.assertFalse(listing["test_sensor"]["enabled"])
        self.assertFalse(listing["test_sensor"]["loaded"])
        self.assertEqual(catalog.sensors, {})
        self.assertEqual(listing["test_sensor"]["calibration"], "optional")
        self.assertEqual([item["type"] for item in listing["test_sensor"]["display"]],
                         ["metric", "metric", "gauge"])

    def test_disabled_plugin_module_is_not_executed(self):
        with tempfile.TemporaryDirectory() as root:
            folder = Path(root) / "danger_test"
            folder.mkdir()
            (folder / "danger_test.py").write_text(
                'PLUGIN = {"id": "danger_test", "name": "Should not run"}\n'
                'raise RuntimeError("executed unexpectedly")\n')
            catalog = PluginCatalog(root, {})
            self.assertTrue(catalog.contains("danger_test"))
            self.assertEqual(catalog.sensors, {})
            active = PluginCatalog(root, {"danger_test": {"enabled": True}})
            self.assertIn("executed unexpectedly", active.errors["danger_test"])

    def test_simulated_acquisition_and_recording(self):
        catalog = PluginCatalog(ROOT, {"test_sensor": {"enabled": True, "sample_interval": .2}})
        self.assertEqual(list(catalog.sensors), ["plugin_test_sensor"])
        sensor = catalog.sensors["plugin_test_sensor"]
        sensor.set_context_provider(lambda: {"stage_id": "s1", "digiflot_state": "Running"})
        sensor.start()
        try:
            self.assertTrue(wait(lambda: sensor.snapshot()["status"] == "connected"))
            snap = catalog.snapshot(sensor)
            self.assertEqual(snap["plugin_id"], "test_sensor")
            self.assertEqual(snap["calibration_policy"], "optional")
            self.assertEqual(snap["unit"], "°C")
            self.assertTrue(0 < snap["channels"]["signal_pct"] < 100)
            with tempfile.TemporaryDirectory() as folder:
                path = sensor.start_recording(folder, "synthetic")
                self.assertTrue(wait(lambda: sensor.sample_count >= 3))
                sensor.stop_recording()
                lines = path.read_text().splitlines()
                self.assertGreaterEqual(len(lines), 2)
                self.assertIn("temperature_c", lines[0])
                self.assertIn("stage_id", lines[0])
        finally:
            sensor.stop()
        self.assertEqual(sensor.snapshot()["status"], "stopped")

    def test_templates_are_not_plugins(self):
        catalog = PluginCatalog(ROOT, {})
        self.assertNotIn("Templates", catalog.installed)
        self.assertNotIn("sampled_sensor", catalog.installed)


if __name__ == "__main__":
    unittest.main()
