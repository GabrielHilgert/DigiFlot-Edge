"""Multiplexed sensor stream preserves per-sensor event payloads."""
import json
import unittest
from unittest.mock import patch
from api import sensors


class TestSensorMultiplex(unittest.TestCase):
    def test_route_before_sensor_id(self):
        paths = [route.path for route in sensors.router.routes]
        self.assertLess(paths.index("/api/sensors/stream"), paths.index("/api/sensors/{sensor_id}"))

    def test_changes(self):
        records = [{"id": "scale_1", "revision": 1}, {"id": "atlas-98", "revision": 1}]
        with patch.object(sensors, "list_all_sensors", side_effect=lambda _: list(records)), \
             patch.object(sensors.time, "sleep", return_value=None):
            feed = sensors.multiplex_sensor_events(None)
            first, second = next(feed), next(feed)
            self.assertTrue(first.startswith("event: measurement\n"))
            self.assertEqual(json.loads(first.split("data: ")[1])["id"], "scale_1")
            self.assertEqual(json.loads(second.split("data: ")[1])["id"], "atlas-98")
            records[0] = {"id": "scale_1", "revision": 2}
            changed = next(feed)
            self.assertEqual(json.loads(changed.split("data: ")[1])["revision"], 2)
            feed.close()


if __name__ == "__main__":
    unittest.main()
