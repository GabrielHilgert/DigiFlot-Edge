"""HIFIE worker is operational-only; calibration uses on-demand acquisition."""
import tempfile
import threading
import unittest
from lib.vision.service import VisionService


class NoCameraDigiflot:
    def __init__(self):
        self.cameras = {}
        self.lock = threading.RLock()


class HifieLifecycleTests(unittest.TestCase):
    def test_service_boot_does_not_create_measurement_worker(self):
        with tempfile.TemporaryDirectory() as folder:
            service = VisionService(NoCameraDigiflot(), folder)
            service.start()
            try:
                self.assertIsNone(service._thread)
                self.assertIsNone(service._last_virtual_measurement)
            finally:
                service.stop()

    def test_worker_starts_only_on_activation_and_stops_on_deactivation(self):
        with tempfile.TemporaryDirectory() as folder:
            service = VisionService(NoCameraDigiflot(), folder)
            service._loop = lambda stop: stop.wait(3)
            service.start()
            self.assertIsNone(service._thread)
            service.activate_sensor()
            thread = service._thread
            try:
                self.assertTrue(thread.is_alive())
                service.activate_sensor()
                self.assertIs(service._thread, thread)
                service.deactivate_sensor()
                thread.join(timeout=1)
                self.assertFalse(thread.is_alive())
            finally:
                service.stop()

    def test_unapproved_diagnostics_do_not_use_measurement_loop(self):
        with tempfile.TemporaryDirectory() as folder:
            service = VisionService(NoCameraDigiflot(), folder)
            service.start()
            self.assertIsNone(service._thread)
            # Without a calibrated camera, diagnostics cannot acquire a frame;
            # they must not activate the operational worker as a side effect.
            service.stop()
            self.assertIsNone(service._thread)


if __name__ == "__main__":
    unittest.main()
