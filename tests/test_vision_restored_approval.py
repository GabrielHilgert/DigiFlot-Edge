"""Boot-time HIFIE validation waits for VisionService and keeps matching approvals."""
import ast
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace


def controller_validator():
    source = Path(__file__).resolve().parents[1] / "src/lib/digiflot.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    node = next(item for item in ast.walk(tree)
                if isinstance(item, ast.FunctionDef) and item.name == "validate_restored_virtual_calibration")
    namespace = {}
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(source), "exec"), namespace)
    return namespace[node.name]


class StartupApprovalTests(unittest.TestCase):
    def test_matching_previous_proof_preserves_ready_and_clean_edit(self):
        def make_controller(valid=True):
            host = SimpleNamespace(lock=threading.RLock(), SENSOR_CALIBRATION="SensorCalibration",
                                   READY="Ready", state="Ready",
                                   sensor_calibration={"froth_interface":{"status":"passed"}},
                                   calibration_edit={"kind":"sensor","id":"froth_interface",
                                                     "previous":{"status":"passed"},"dirty":False},
                                   vision=SimpleNamespace(virtual_test_passed=lambda:valid))
            host.invalidations, host.events = [], []
            def invalidate(reason):
                host.invalidations.append(reason)
                host.sensor_calibration["froth_interface"]["status"] = "pending"
                host.state = host.SENSOR_CALIBRATION
            host._invalidate_virtual_calibration_unlocked = invalidate
            host._touch_unlocked = lambda name:host.events.append(name)
            return host

        check = controller_validator()
        passing = make_controller()
        check(passing)
        self.assertEqual(passing.state,"Ready")
        self.assertEqual(passing.sensor_calibration["froth_interface"]["status"],"passed")
        self.assertFalse(passing.calibration_edit["dirty"])
        self.assertFalse(passing.invalidations)

        changed = make_controller(valid=False)
        check(changed)
        self.assertEqual(changed.state,"SensorCalibration")
        self.assertEqual(changed.sensor_calibration["froth_interface"]["status"],"pending")
        self.assertTrue(changed.calibration_edit["dirty"])
        self.assertEqual(len(changed.invalidations),1)

    def test_validation_hook_runs_after_service_is_created(self):
        startup = (Path(__file__).resolve().parents[1] / "src/app.py").read_text()
        self.assertLess(startup.index("digiflot.vision = app.state.vision"),
                        startup.index("digiflot.validate_restored_virtual_calibration()"))
        self.assertLess(startup.index("digiflot.validate_restored_virtual_calibration()"),
                        startup.index("app.state.vision.start()"))
        loader = (Path(__file__).resolve().parents[1] / "src/lib/digiflot.py").read_text()
        self.assertIn('self.vision is not None and self.sensor_calibration.get("froth_interface"', loader)


if __name__ == "__main__":
    unittest.main()
