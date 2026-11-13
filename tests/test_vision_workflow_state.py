"""Hardware-free state-machine transition tests for pre-run calibration and execution gates."""
import ast
import threading
import time
import unittest
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

SOURCE = Path(__file__).resolve().parents[1] / "src/lib/digiflot.py"
TREE = ast.parse(SOURCE.read_text(encoding="utf-8"))
OWNER = next(n for n in TREE.body if isinstance(n, ast.ClassDef) and n.name == "DigiFlot")

def extract(name):
    fn = next(n for n in OWNER.body if isinstance(n, ast.FunctionDef) and n.name == name)
    ns = {"deepcopy":deepcopy, "time":time, "_utc_now":lambda:"test-time"}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),str(SOURCE),"exec"),ns)
    return ns[name]

class FakeFlow:
    IDLE="Idle"; CELL_SELECTION="CellSelection"; CAMERA_CALIBRATION="CameraCalibration"
    SENSOR_CALIBRATION="SensorCalibration"; READY="Ready"; RUNNING="Running"; PAUSED="Paused"
    COMPLETED="Completed"; ABORTED="Aborted"; ERROR="Error"; RECOVERY_REQUIRED="RecoveryRequired"
    STAGE_NONE="None"; STAGE_WAITING="Waiting"; STAGE_ACTIVE="Active"; STAGE_TRANSITION="Transition"
    reopen_sensor_calibration=extract("reopen_sensor_calibration")
    reopen_camera_calibration=extract("reopen_camera_calibration")
    cancel_calibration_edit=extract("cancel_calibration_edit")
    _mark_calibration_changed_unlocked=extract("_mark_calibration_changed_unlocked")
    _invalidate_virtual_calibration_unlocked=extract("_invalidate_virtual_calibration_unlocked")
    _advance_from_camera_calibration_unlocked=extract("_advance_from_camera_calibration_unlocked")
    complete_sensor_calibration=extract("complete_sensor_calibration")
    skip_sensor_calibration=extract("skip_sensor_calibration")
    start_next_stage=extract("start_next_stage")
    pause=extract("pause")
    resume=extract("resume")
    def __init__(self):
        self.lock=threading.RLock()
        self.state=self.READY; self.stage_state=self.STAGE_WAITING
        self.calibration_edit=None; self.preview_camera_id=None; self.virtual_camera_id=1
        self.cell_profile={"physical_cell_id":"cell-a"}
        self.sensor_calibration={"ph1":{"id":"ph1","name":"pH", "mode":"ph_points", "status":"passed",
            "confirmed_at":"old", "requested_points":2, "points":{"mid":{"status":"passed"},"low":{"status":"passed"}}}}
        self.camera_calibration={"1":{"id":1,"status":"passed","available":True,"confirmed_at":"old"}}
        self.vision=SimpleNamespace(clear_virtual_test=lambda:None,virtual_test_passed=lambda:True)
        self.events=[]; self.current_stage_index=None
        self.pause_started_monotonic=None;self.pause_started_at=None;self.paused_stage_state=None
        self.stage_started_monotonic=None;self.stage_deadline=None;self.next_scraping_deadline=None
        self.transition_started_monotonic=None;self.transition_deadline=None
    @property
    def status(self): return {"state":self.state,"calibration_edit":deepcopy(self.calibration_edit)}
    def _touch_unlocked(self,event,*args): self.events.append(event)
    def _sensor_status_unlocked(self, sensor_id): return {"status":"connected"}
    def _write_config_snapshot_unlocked(self): pass
    def stop_preview(self): self.preview_camera_id=None

class WorkflowTests(unittest.TestCase):
    def test_ready_sensor_reopen_is_reversible_without_changes(self):
        run=FakeFlow(); original=deepcopy(run.sensor_calibration["ph1"])
        run.reopen_sensor_calibration("ph1")
        self.assertEqual(run.state,run.SENSOR_CALIBRATION)
        self.assertEqual(run.sensor_calibration["ph1"]["status"],"pending")
        self.assertFalse(run.calibration_edit["dirty"])
        run.cancel_calibration_edit()
        self.assertEqual(run.state,run.READY)
        self.assertEqual(run.sensor_calibration["ph1"],original)
        self.assertIsNone(run.calibration_edit)

    def test_calibration_cancel_refuses_to_restore_hardware_changed_approval(self):
        run=FakeFlow();run.reopen_sensor_calibration("ph1")
        run._mark_calibration_changed_unlocked("sensor","ph1")
        with self.assertRaisesRegex(RuntimeError,"changed"):
            run.cancel_calibration_edit()
        self.assertEqual(run.state,run.SENSOR_CALIBRATION)
        run.skip_sensor_calibration("ph1","operator skipped after recalibration")
        run.complete_sensor_calibration()
        self.assertEqual(run.state,run.READY)
        self.assertEqual(run.sensor_calibration["ph1"]["status"],"skipped")
        self.assertIsNone(run.calibration_edit)

    def test_camera_reopen_can_be_cancelled_before_changes(self):
        run=FakeFlow();original=deepcopy(run.camera_calibration["1"])
        run.reopen_camera_calibration(1)
        self.assertEqual(run.state,run.CAMERA_CALIBRATION)
        run.cancel_calibration_edit()
        self.assertEqual(run.state,run.READY)
        self.assertEqual(run.camera_calibration["1"],original)

    def test_named_reference_change_requires_retest_only_for_enabled_virtual_sensor(self):
        run=FakeFlow();run.sensor_calibration["froth_interface"]={"status":"passed","mode":"virtual_interface","confirmed_at":"old","benchmark":{"passed":True}}
        run._invalidate_virtual_calibration_unlocked("Named reference changed")
        self.assertEqual(run.state,run.SENSOR_CALIBRATION)
        self.assertEqual(run.sensor_calibration["froth_interface"]["status"],"pending")
        self.assertNotIn("benchmark",run.sensor_calibration["froth_interface"])
        run=FakeFlow();run.sensor_calibration["froth_interface"]={"status":"skipped","mode":"virtual_interface"}
        run._invalidate_virtual_calibration_unlocked("Named reference changed")
        self.assertEqual(run.state,run.READY)
        self.assertEqual(run.sensor_calibration["froth_interface"]["status"],"skipped")

    def test_ready_start_gate_redirects_incomplete_cameras_or_sensors(self):
        run=FakeFlow();run.camera_calibration["1"]["status"]="pending"
        with self.assertRaisesRegex(RuntimeError,"Camera calibration"):
            run.start_next_stage()
        self.assertEqual(run.state,run.CAMERA_CALIBRATION)
        run=FakeFlow();run.sensor_calibration["ph1"]["status"]="pending"
        with self.assertRaisesRegex(RuntimeError,"Sensor calibration"):
            run.start_next_stage()
        self.assertEqual(run.state,run.SENSOR_CALIBRATION)

    def test_ready_start_gate_rejects_stale_virtual_benchmark(self):
        run=FakeFlow();run.sensor_calibration["froth_interface"]={"status":"passed","mode":"virtual_interface"}
        run.vision.virtual_test_passed=lambda:False
        with self.assertRaisesRegex(RuntimeError,"fresh benchmark"):
            run.start_next_stage()
        self.assertEqual(run.state,run.SENSOR_CALIBRATION)
        self.assertEqual(run.sensor_calibration["froth_interface"]["status"],"pending")

    def test_pause_and_resume_preserve_active_stage_remaining_time(self):
        run=FakeFlow();run.state=run.RUNNING;run.stage_state=run.STAGE_ACTIVE
        now=time.monotonic();run.stage_started_monotonic=now-2;run.stage_deadline=now+40;run.next_scraping_deadline=now+5
        original_remaining=run.stage_deadline-now
        run.pause()
        self.assertEqual(run.state,run.PAUSED)
        self.assertEqual(run.paused_stage_state,run.STAGE_ACTIVE)
        time.sleep(.01); run.resume()
        self.assertEqual(run.state,run.RUNNING)
        self.assertEqual(run.stage_state,run.STAGE_ACTIVE)
        self.assertAlmostEqual(run.stage_deadline-time.monotonic(),original_remaining,delta=.1)

if __name__ == "__main__": unittest.main()
