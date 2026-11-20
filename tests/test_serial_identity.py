"""Regression tests for stable DigiFlot RS-232 endpoint associations."""
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from lib.serial_identity import connection_from_port, configured_endpoint_map, resolve_runtime_ports, serial_inventory, strong_match


class SerialIdentityTests(unittest.TestCase):
    def endpoint(self, port, serial="FT123", interface="A", usb_id=None):
        return {"port": port, "adapter_serial": serial, "interface": interface,
                "vid": 1027, "pid": 24592, "usb_id": usb_id, "usb_path": None}

    def test_moved_usb_port_preserves_logical_scale(self):
        previous = self.endpoint("/dev/ttyUSB0", usb_id="usb-FT4232-if00-port0")
        saved = [{"id": "scale_1", "port": previous["port"], "connection": connection_from_port(previous)}]
        moved = self.endpoint("/dev/ttyUSB3", usb_id="usb-FT4232-if00-port0")
        self.assertEqual(resolve_runtime_ports(saved, [moved]), {"scale_1": "/dev/ttyUSB3"})
        self.assertEqual(saved[0]["id"], "scale_1")
        self.assertEqual(saved[0]["port"], "/dev/ttyUSB0")

    def test_different_channels_are_not_same_identity(self):
        a = self.endpoint("/dev/ttyUSB0", interface="A", usb_id="usb-FT4232-if00-port0")
        b = self.endpoint("/dev/ttyUSB1", interface="B", usb_id="usb-FT4232-if01-port0")
        saved = [{"id": "scale_1", "port": a["port"], "connection": connection_from_port(a)}]
        self.assertIsNone(strong_match(saved[0]["connection"], [b]))
        self.assertNotEqual(resolve_runtime_ports(saved, [b]).get("scale_1"), b["port"])
        self.assertNotIn(b["port"], configured_endpoint_map(saved, [b]))

    def test_duplicate_converter_identifiers_cannot_match(self):
        previous = self.endpoint("/dev/ttyUSB0")
        saved = [{"id": "scale_1", "port": "/dev/ttyUSB0", "connection": connection_from_port(previous)}]
        candidates = [self.endpoint("/dev/ttyUSB1"), self.endpoint("/dev/ttyUSB2")]
        self.assertIsNone(strong_match(saved[0]["connection"], candidates))
        self.assertNotIn("scale_1", resolve_runtime_ports(saved, candidates))

    def test_reused_tty_is_not_misclassified_as_saved_scale(self):
        original = self.endpoint("/dev/ttyUSB0", interface="A", usb_id="usb-original-if00")
        replacement = self.endpoint("/dev/ttyUSB0", interface="B", usb_id="usb-other-if01")
        saved = [{"id": "scale_1", "port": original["port"],
                  "connection": connection_from_port(original)}]
        self.assertEqual(configured_endpoint_map(saved, [replacement]), {})
        self.assertNotEqual(resolve_runtime_ports(saved, [replacement])["scale_1"], replacement["port"])

    def test_legacy_config_keeps_current_port(self):
        saved = [{"id": "scale_1", "port": "/dev/ttyUSB2"}]
        self.assertEqual(resolve_runtime_ports(saved, [self.endpoint("/dev/ttyUSB2")]), {})

    def test_offline_cached_weight_does_not_confirm_scale(self):
        from lib.scale import Scale
        endpoint = self.endpoint("/dev/ttyUSB0")
        runtime = SimpleNamespace(snapshot=lambda: {
            "status": "offline", "value": 100.0, "unit": "g",
            "raw": "100.00 g", "timestamp_ns": "1", "error": "disconnected"
        })
        with patch("lib.scale.serial_inventory", return_value=[endpoint]):
            result = Scale.discover_available(runtime_scales={endpoint["port"]: runtime})
        self.assertFalse(result[0]["scale_detected"])
        self.assertEqual(result[0]["runtime_status"], "offline")

    def test_by_id_survives_reenumeration(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "by-id").mkdir()
            a, b = root / "ttyUSB0", root / "ttyUSB3"
            a.touch()
            info = lambda port: SimpleNamespace(device=str(port), description="FT4232",
                manufacturer="FTDI", serial_number="123", interface="A",
                location="1-1", vid=1027, pid=24592)
            link = root / "by-id" / "usb-FTDI_FT4232_123-if00-port0"
            link.symlink_to(a)
            before = serial_inventory([info(a)], serial_root=root)[0]
            a.rename(b)
            link.unlink()
            link.symlink_to(b)
            after = serial_inventory([info(b)], serial_root=root)[0]
            self.assertEqual(strong_match(connection_from_port(before), [after])["port"], str(b))


if __name__ == "__main__":
    unittest.main()
