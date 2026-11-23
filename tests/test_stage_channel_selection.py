"""Regression tests for stage-aware writer selection and independent camera previews."""
import ast, tempfile, time, unittest
from pathlib import Path
from types import SimpleNamespace

SOURCE=Path(__file__).resolve().parents[1]/"src/lib/digiflot.py"
OWNER=next(n for n in ast.parse(SOURCE.read_text()).body if isinstance(n,ast.ClassDef) and n.name=="DigiFlot")
def method(name):
    fn=next(n for n in OWNER.body if isinstance(n,ast.FunctionDef) and n.name==name)
    namespace={"Path":Path,"time":time,"_safe_path_name":lambda name: str(name)}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),str(SOURCE),"exec"),namespace)
    return namespace[name]

class Device:
    def __init__(self, ident):
        self.id=ident;self.name=ident;self.recording=False;self.writer_active=False;self.calls=[]
    def snapshot(self):return {"status":"connected"}
    def start_recording(self, output_dir, file_stem):
        self.calls.append(file_stem);self.recording=True
        return Path(output_dir)/f"{file_stem}.tsv"
    def stop_recording(self):self.recording=False

class StageChannelTests(unittest.TestCase):
    def test_wago_bronkhorst_plugins_respect_selection_and_never_restart_existing_writer(self):
        wago,airflow,plugin=(Device(k) for k in ("wago-1","airflow-1","plugin-1"))
        with tempfile.TemporaryDirectory() as directory:
            events=[]
            ctrl=SimpleNamespace(run_directory=Path(directory),current_stage_index=0,stage_attempt=1,
                scales={},atlas=None,bronkhorst={"a":airflow},wago={"w":wago},
                plugin_sensors={"p":plugin},plugin_catalog=SimpleNamespace(snapshot=lambda d:d.snapshot()),
                _append_event_unlocked=lambda event,data:events.append((event,data)),
                _add_warning_unlocked=lambda *args:None)
            start=method("_start_sensor_recording_unlocked")
            start(ctrl,allowed={"wago-1"});start(ctrl,allowed={"wago-1"})
            self.assertEqual((len(wago.calls),len(airflow.calls),len(plugin.calls)),(1,0,0))
            start(ctrl,allowed={"airflow-1","plugin-1"})
            self.assertEqual((len(wago.calls),len(airflow.calls),len(plugin.calls)),(1,1,1))
            self.assertEqual(len({entry for d in (wago,airflow,plugin) for entry in d.calls}),3)
            self.assertEqual(len([event for event,_ in events if event=="SENSOR_RECORDING_STARTED"]),3)

    def test_recording_second_camera_never_interrupts_first_camera_preview(self):
        with tempfile.TemporaryDirectory() as directory:
            camera1=SimpleNamespace(id=1,name="Camera 1",recording=False,
                exposure_time_us=None,analogue_gain=None)
            camera2=SimpleNamespace(id=2,name="Camera 2",recording=False,
                exposure_time_us=None,analogue_gain=None)
            ctrl=SimpleNamespace(run_directory=Path(directory),preview_camera_id=1,
                cameras={1:camera1,2:camera2},camera_calibration={},
                _add_warning_unlocked=lambda *args:None,
                _append_event_unlocked=lambda *args:None)
            interrupted=[]
            def stop_preview():
                interrupted.append(ctrl.preview_camera_id);ctrl.preview_camera_id=None
            ctrl.stop_preview=stop_preview
            start=method("_start_camera_recording_unlocked")
            start(ctrl,{"id":"stage"},selected_ids={2})
            self.assertEqual(interrupted,[])
            self.assertEqual(ctrl.preview_camera_id,1)
            start(ctrl,{"id":"stage"},selected_ids={1})
            self.assertEqual(interrupted,[1])
            self.assertIsNone(ctrl.preview_camera_id)

if __name__=="__main__":unittest.main()
