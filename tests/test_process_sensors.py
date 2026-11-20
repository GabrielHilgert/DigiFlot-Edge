"""Hardware-free Bronkhorst/WAGO regression checks."""
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from lib import bronkhorst as bronk_module
from lib import wago as wago_module


def wait_until(predicate, timeout=3):
    limit = time.monotonic() + timeout
    while time.monotonic() < limit:
        if predicate():
            return True
        time.sleep(0.02)
    return False


class FakeBronkhorst:
    id = "EL-FLOW"
    def __init__(self):
        self.flow = 1.5
        self.setpoint = 0.0
        self.writes = []
        self.master = SimpleNamespace(stop=lambda: None)

    def readParameter(self, number):
        return {91: "EL-FLOW", 92: "SN-001", 129: "ln/min",
                205: self.flow, 206: self.setpoint}.get(number)

    def writeParameter(self, number, value):
        assert number == 206
        self.writes.append(value)
        self.setpoint = float(value)
        return True


class FakeModbus:
    def __init__(self, port, slave, mode, close_port_after_each_call):
        self.serial = SimpleNamespace(baudrate=None, parity=None, stopbits=None, timeout=None)
        self.clear_buffers_before_each_transaction = False
        self.values = {10: 180.0, 12: 1.25}

    def read_float(self, address, **kwargs):
        return self.values[address]

    def read_registers(self, address, count, functioncode=3):
        return [1300] if address in (0, 0x4000) else []


class ProcessSensorTests(unittest.TestCase):
    def test_bronkhorst_discovery_is_read_only(self):
        fake = FakeBronkhorst()
        with patch.object(bronk_module, "propar", SimpleNamespace(instrument=lambda *a, **kw: fake)):
            found = bronk_module.Bronkhorst.discover_available(
                [{"port": "/dev/ttyTEST0", "connection": {"usb_id": "x"}}])
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["device_serial"], "SN-001")
        self.assertEqual(fake.writes, [])

    def test_bronkhorst_commands_do_not_run_at_boot(self):
        fake = FakeBronkhorst()
        with patch.object(bronk_module, "propar", SimpleNamespace(instrument=lambda *a, **kw: fake)):
            device = bronk_module.Bronkhorst(id="air_flow_1", port="/dev/ttyTEST0",
                sample_interval=0.2, control_enabled=True, identity={"device_serial": "SN-001"})
            device.start()
            try:
                self.assertTrue(wait_until(lambda: device.snapshot()["status"] == "connected"))
                self.assertEqual(fake.writes, [])
                device.set_airflow(3.0)
                self.assertTrue(wait_until(lambda: device.snapshot()["control_state"] == "applied"))
                self.assertAlmostEqual(fake.setpoint, 3.0)
                with self.assertRaises(ValueError):
                    device.set_airflow(50)
                device.stop_airflow()
                self.assertTrue(wait_until(lambda: fake.setpoint == 0))
            finally:
                device.stop()

    def test_wago_requires_verified_register_map(self):
        device = wago_module.Wago(id="power_1", port="/dev/ttyTEST1")
        device.start()
        try:
            self.assertTrue(wait_until(lambda: device.snapshot()["status"] == "unconfigured"))
            self.assertIsNone(device.snapshot()["value"])
        finally:
            device.stop()

    def test_wago_reads_configured_channels(self):
        fake_lib = SimpleNamespace(Instrument=FakeModbus, MODE_RTU="rtu",
            BYTEORDER_BIG=0, BYTEORDER_LITTLE=1,
            BYTEORDER_BIG_SWAP=2, BYTEORDER_LITTLE_SWAP=3)
        with patch.object(wago_module, "minimalmodbus", fake_lib):
            register_map = {"active_power": {"address": 10, "data_type": "float32"},
                            "energy_import": {"address": 12, "data_type": "float32"}}
            device = wago_module.Wago(id="power_1", port="/dev/ttyTEST1",
                sample_interval=0.2, registers=register_map)
            device.start()
            try:
                self.assertTrue(wait_until(lambda: device.snapshot()["status"] == "connected"))
                snapshot = device.snapshot()
                self.assertEqual(snapshot["value"], 180.0)
                self.assertAlmostEqual(snapshot["channels"]["energy_import"], 1.25)
            finally:
                device.stop()


if __name__ == "__main__":
    unittest.main()
