"""Hardware-free tests of scraping scheduling, GPIO pulses and overdue events."""
import ast
import threading
import time
import unittest
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

from lib.scraping_gpio import ALLOWED_GPIO_PINS, ScrapingGPIO, validate_gpio_pin

SOURCE = Path(__file__).resolve().parents[1] / "src/lib/digiflot.py"
TREE = ast.parse(SOURCE.read_text(encoding="utf-8"))
OWNER = next(node for node in TREE.body if isinstance(node, ast.ClassDef) and node.name == "DigiFlot")


def method(name):
    fn = next(node for node in OWNER.body if isinstance(node, ast.FunctionDef) and node.name == name)
    ns = {"time": time, "deepcopy": deepcopy, "_utc_now": lambda: "test-utc"}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn], type_ignores=[])), str(SOURCE), "exec"), ns)
    return ns[name]


class FakeStage:
    RUNNING = "Running"; STAGE_ACTIVE = "Active"; STAGE_TRANSITION = "Transition"
    _start_stage_unlocked = method("_start_stage_unlocked")

    def __init__(self):
        self.stage_attempt = 1; self.recording = False; self.camera_ready_at = None
        self.scraping_gpio=SimpleNamespace(cancel_pending=lambda:None)
        self.current_stage = {"id": "flot", "name": "Flotation", "type": "flotation", "duration": 5}
        self.stage_state = self.STAGE_TRANSITION
        self.events = []
    def apply_stage_setpoints(self, stage): return {}
    def _camera_required(self, stage): return True
    def _start_camera_recording_unlocked(self, stage):
        time.sleep(.035)
        self.recording = True
        self.camera_ready_at = time.monotonic()
    def _scraping_required(self, stage): return True
    def _scraping_interval(self, stage): return 1.
    def _touch_unlocked(self, event, data=None): self.events.append(event)


class FakeOrchestrator:
    RUNNING = "Running"; STAGE_ACTIVE = "Active"; STAGE_TRANSITION = "Transition"
    PAUSED = "Paused"; RECOVERY_REQUIRED = "RecoveryRequired"
    _control_loop = method("_control_loop")

    def __init__(self, stage_expired):
        self.stop_event = threading.Event()
        self.lock = threading.RLock()
        self.condition = threading.Condition(self.lock)
        self._storage_abort_requested = False
        self.state = self.RUNNING
        self.stage_state = self.STAGE_ACTIVE
        self.current_stage = {"id": "flot"}
        now = time.monotonic()
        self.stage_deadline = now - .05 if stage_expired else now + 30
        self.next_scraping_deadline = now - 2.2
        self.transition_deadline = None
        self.events = []
    def _check_device_health_unlocked(self): return None
    def _scraping_interval(self, stage): return 1.0
    def _complete_stage_unlocked(self):
        self.events.append("stage_finished")
        self.stop_event.set()
    def _trigger_scraping_unlocked(self, scheduled=None):
        self.events.append(("scrape", scheduled))
        time.sleep(.03)
        self.stop_event.set()
    def _next_control_wait_unlocked(self): return .001


class GPIOTests(unittest.TestCase):
    def test_reserved_bus_pins_rejected(self):
        for pin in (0, 1, 2, 3, 7, 8, 9, 10, 11, 14, 15, 28, True):
            with self.subTest(pin=pin), self.assertRaises(ValueError):
                validate_gpio_pin(pin)
        self.assertEqual(validate_gpio_pin("17"), 17)
        self.assertIn(17, ALLOWED_GPIO_PINS)

    def test_nonblocking_pulse_and_no_late_replay(self):
        events = []; reports = []; delivered = threading.Event()
        class Device:
            def on(self): events.append(("on", time.monotonic()))
            def off(self): events.append(("off", time.monotonic()))
            def close(self): events.append(("close", time.monotonic()))
        def callback(result):
            reports.append(result); delivered.set()
        gpio = ScrapingGPIO(17, pulse_s=.03, output_factory=lambda _:Device(), report=callback)
        try:
            before = time.monotonic()
            self.assertTrue(gpio.schedule(before))
            self.assertLess(time.monotonic()-before, .1)
            self.assertTrue(delivered.wait(2))
            self.assertEqual(reports[0]["status"], "sent")
            self.assertEqual([x[0] for x in events[:2]], ["on", "off"])
            delivered.clear()
            self.assertTrue(gpio.schedule(time.monotonic()-5))
            self.assertTrue(delivered.wait(2))
            self.assertEqual(reports[1]["status"], "expired")
            self.assertEqual(len([x for x in events if x[0]=="on"]), 1)
        finally: gpio.close()

    def test_single_pending_slot_prevents_gpio_burst(self):
        started = threading.Event()
        class Device:
            def on(self): started.set()
            def off(self): pass
            def close(self): pass
        gpio = ScrapingGPIO(17, pulse_s=.2, output_factory=lambda _:Device())
        try:
            self.assertTrue(gpio.schedule(time.monotonic()))
            self.assertTrue(started.wait(2))
            self.assertTrue(gpio.schedule(time.monotonic()))
            self.assertFalse(gpio.schedule(time.monotonic()))
            self.assertEqual(gpio.dropped, 1)
        finally: gpio.close()

    def test_gpio_factory_failure_does_not_break_scheduler(self):
        reports = []; done = threading.Event()
        def factory(pin): raise RuntimeError("Permission denied")
        def report(result): reports.append(result); done.set()
        gpio = ScrapingGPIO(17, output_factory=factory, report=report)
        try:
            self.assertTrue(gpio.schedule(time.monotonic()))
            self.assertTrue(done.wait(2))
            self.assertEqual(reports[0]["status"],"error")
            self.assertIn("Permission denied",gpio.status()["last_error"])
        finally: gpio.close()


class SchedulerTests(unittest.TestCase):
    def test_camera_startup_is_not_counted_in_scraping_clock(self):
        controller=FakeStage()
        before=time.monotonic()
        controller._start_stage_unlocked(controller.current_stage)
        self.assertGreater(controller.stage_started_monotonic-before,.025)
        self.assertGreaterEqual(controller.stage_started_monotonic,controller.camera_ready_at)
        self.assertAlmostEqual(controller.next_scraping_deadline-controller.stage_started_monotonic,1.,delta=.005)
        self.assertAlmostEqual(controller.stage_deadline-controller.stage_started_monotonic,5.,delta=.005)

    def test_expired_stage_takes_priority_over_scraping(self):
        controller=FakeOrchestrator(stage_expired=True)
        controller._control_loop()
        self.assertEqual(controller.events,["stage_finished"])

    def test_missed_intervals_are_skipped_without_catchup(self):
        controller=FakeOrchestrator(stage_expired=False)
        controller._control_loop()
        self.assertEqual(len(controller.events),1)
        self.assertEqual(controller.events[0][0],"scrape")
        self.assertGreater(controller.next_scraping_deadline,time.monotonic())


if __name__ == "__main__":
    unittest.main()
