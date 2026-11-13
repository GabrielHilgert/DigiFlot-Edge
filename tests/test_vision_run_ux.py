"""Hardware-independent tests for run preparation, camera-tab leases and abort cleanup."""
import ast
import tempfile
import threading
import time
import unittest
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1] / "src/lib/digiflot.py"
TREE = ast.parse(ROOT.read_text(encoding="utf-8"))
OWNER = next(node for node in TREE.body if isinstance(node, ast.ClassDef) and node.name == "DigiFlot")


def method(name, env=None):
    node = next(node for node in OWNER.body if isinstance(node, ast.FunctionDef) and node.name == name)
    namespace = {"time": time, "deepcopy": deepcopy, "planned_inputs": lambda experiment: {
        "working_cell_volume": {"value": 3.4, "source": "recipe"},
        "feed_mass": {"value": 200., "source": "recipe"},
        "water_volume": {"value": 2., "source": "recipe"},
    }, **(env or {})}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[])),
                 str(ROOT), "exec"), namespace)
    return namespace[name]


class Camera:
    IDLE, PREVIEW = "Idle", "Preview"

    def __init__(self):
        self.id, self.state = 1, self.IDLE
    def start_preview(self): self.state = self.PREVIEW
    def stop_preview(self): self.state = self.IDLE


class FakeRuntime:
    IDLE = "Idle"
    CAMERA_CALIBRATION = "CameraCalibration"
    SENSOR_CALIBRATION = "SensorCalibration"

    start_preview = method("start_preview")
    stop_preview = method("stop_preview")
    preview_heartbeat = method("preview_heartbeat")

    def __init__(self):
        self.lock = threading.RLock()
        self.camera = Camera()
        self.cameras = {1: self.camera}
        self.state, self.recording, self.preview_camera_id = "Idle", False, None
        self.preview_owner_id, self.preview_owner_until = None, 0
        self.revision = 0
        self.condition = SimpleNamespace(notify_all=lambda: None)

    def get_camera(self, camera_id): return self.cameras[camera_id]
    @property
    def status(self): return {"state": self.state, "preview_camera_id": self.preview_camera_id}
    def _status_unlocked(self): return self.status


class RunUXTests(unittest.TestCase):
    def test_two_tabs_cannot_start_same_or_different_camera_preview(self):
        run = FakeRuntime()
        run.start_preview(1, owner_id="tab-A")
        self.assertEqual(run.preview_heartbeat("tab-A")["camera_id"], 1)
        with self.assertRaisesRegex(RuntimeError, "another browser tab"):
            run.start_preview(1, owner_id="tab-B")
        with self.assertRaisesRegex(RuntimeError, "another browser tab"):
            run.stop_preview(owner_id="tab-B")
        run.stop_preview(owner_id="tab-A")
        run.start_preview(1, owner_id="tab-B")
        self.assertEqual(run.preview_owner_id, "tab-B")
        run.stop_preview()

    def test_stale_browser_lease_is_released_before_new_owner(self):
        run = FakeRuntime()
        run.start_preview(1, owner_id="tab-A")
        run.preview_owner_until = time.monotonic()-1
        run.start_preview(1, owner_id="tab-B")
        self.assertEqual(run.preview_owner_id, "tab-B")
        self.assertEqual(run.camera.state, run.camera.PREVIEW)

    def test_feed_water_are_optional_and_start_unblocked(self):
        initial = method("_initialise_execution_inputs_unlocked")
        payload = method("_execution_inputs_payload_unlocked")
        specs = {"working_cell_volume": {"label":"Working cell volume","unit":"L"},
                 "feed_mass": {"label":"Feed mass","unit":"g"},
                 "water_volume": {"label":"Water volume","unit":"L"}}
        run = SimpleNamespace(REQUIRED_EXECUTION_INPUTS=specs,
                              experiment={"metadata": {}}, execution_inputs={},
                              measurements=[], cell_profile=None, server_sync_manager=None)
        run._derived_metrics_unlocked=lambda:{}
        initial(run)
        self.assertEqual(run.execution_inputs["working_cell_volume"]["value"],3.4)
        self.assertIsNone(run.execution_inputs["feed_mass"]["value"])
        self.assertIsNone(run.execution_inputs["water_volume"]["value"])
        self.assertFalse(run.execution_inputs["feed_mass"]["required"])
        self.assertEqual(payload(run)["missing"],[])
        self.assertTrue(payload(run)["complete"])

    def test_abort_is_logged_before_state_returns_to_idle(self):
        abort = method("abort_experiment", {"_utc_now":lambda:"now"})
        events = []
        run = SimpleNamespace(lock=threading.RLock(), IDLE="Idle", ABORTED="Aborted",
            state="Running", next_scraping_deadline=3, stage_deadline=5, transition_deadline=7,
            stage_state="Running", STAGE_NONE="None", recovery_context={},
            revision=0, condition=SimpleNamespace(notify_all=lambda:None), last_error=None)
        run._stop_camera_recording_unlocked=lambda **kw: events.append("camera_stopped")
        run._stop_sensor_recording_unlocked=lambda:events.append("sensors_stopped")
        run._stop_performance_telemetry_unlocked=lambda:events.append("telemetry_stopped")
        run.stop_preview=lambda:events.append("preview_stopped")
        run._touch_unlocked=lambda name,data=None:events.append(name)
        run._sync_execution_state_unlocked=lambda state,ensure=False:events.append("persist_"+state)
        def reset():
            events.append("reset")
            run.state="Idle"
        run._reset_run_state_unlocked=reset
        run.status={"state": "Idle"}
        abort(run,"Stopped by operator",return_to_idle=True)
        self.assertEqual(run.state,"Idle")
        self.assertLess(events.index("EXPERIMENT_ABORTED"),events.index("reset"))
        self.assertLess(events.index("persist_aborted"),events.index("reset"))


if __name__ == "__main__":
    unittest.main()
