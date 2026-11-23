"""HIFIE owns only its own lores preview and frees it after deactivation."""
import ast, threading, unittest
from pathlib import Path
from types import SimpleNamespace

SOURCE=Path(__file__).resolve().parents[1]/"src/lib/vision/service.py"
OWNER=next(x for x in ast.parse(SOURCE.read_text()).body if isinstance(x,ast.ClassDef) and x.name=="VisionService")
def read(name):
    fn=next(x for x in OWNER.body if isinstance(x,ast.FunctionDef) and x.name==name)
    ns={}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),str(SOURCE),"exec"),ns)
    return ns[name]

class Camera:
    PREVIEW="Preview";RECORDING="Recording";IDLE="Idle"
    def __init__(self):
        self.id=1;self.state=self.IDLE;self.starts=0
    def start_preview(self):
        self.state=self.PREVIEW;self.starts+=1
    def stop_preview(self):
        self.state=self.IDLE

class LoresOwnershipTests(unittest.TestCase):
    def fake(self):
        camera=Camera();stopped=[]
        digiflot=SimpleNamespace(lock=threading.RLock(),state="Running",
            SENSOR_CALIBRATION="SensorCalibration",preview_camera_id=None,
            preview_owner_id=None,cameras={1:camera})
        def stop_preview():
            stopped.append(camera.id);camera.stop_preview();digiflot.preview_camera_id=None
        digiflot.stop_preview=stop_preview
        sensor=SimpleNamespace(digiflot=digiflot,_benchmarking=False,
            _diagnostic_preview_camera_id=None,_operational_preview_camera_id=None)
        sensor.virtual_test_passed=lambda:True
        return sensor,camera,stopped

    def test_worker_owns_only_the_preview_it_starts_and_releases_it(self):
        sensor,camera,stopped=self.fake()
        self.assertTrue(read("ensure_live_preview")(sensor,{"camera":camera}))
        self.assertEqual(sensor._operational_preview_camera_id,1)
        read("_release_operational_preview")(sensor)
        self.assertEqual(stopped,[1])
        self.assertIsNone(sensor.digiflot.preview_camera_id)
        self.assertIsNone(sensor._operational_preview_camera_id)

    def test_tab_owned_preview_is_never_released(self):
        sensor,camera,stopped=self.fake()
        camera.state=camera.PREVIEW;sensor.digiflot.preview_camera_id=1
        sensor.digiflot.preview_owner_id="browser-tab"
        sensor._operational_preview_camera_id=1
        read("_release_operational_preview")(sensor)
        self.assertEqual(stopped,[])
        self.assertEqual(camera.state,camera.PREVIEW)

    def test_changed_camera_or_main_encoder_is_never_interrupted(self):
        sensor,camera,stopped=self.fake()
        sensor._operational_preview_camera_id=1
        camera.state=camera.RECORDING;sensor.digiflot.preview_camera_id=1
        read("_release_operational_preview")(sensor)
        self.assertEqual(stopped,[])
        self.assertEqual(camera.state,camera.RECORDING)

if __name__=="__main__":unittest.main()
