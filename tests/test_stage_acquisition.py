"""Stage-specific transition, manual duration and channel-selection tests without hardware."""
import ast, math, threading, time, unittest
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

SOURCE=Path(__file__).resolve().parents[1]/"src/lib/digiflot.py"
TREE=ast.parse(SOURCE.read_text())
OWNER=next(n for n in TREE.body if isinstance(n,ast.ClassDef) and n.name=="DigiFlot")
def extract(name):
    fn=next(n for n in OWNER.body if isinstance(n,ast.FunctionDef) and n.name==name)
    ns={"time":time,"math":math,"deepcopy":deepcopy,"_utc_now":lambda:"test-time"}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),str(SOURCE),"exec"),ns)
    return ns[name]

class Fake:
    STAGE_ACTIVE="Active";STAGE_TRANSITION="Transition";RUNNING="Running"
    _stage_acquisition_unlocked=extract("_stage_acquisition_unlocked")
    _stage_transition_unlocked=extract("_stage_transition_unlocked")
    _start_stage_unlocked=extract("_start_stage_unlocked")
    _complete_stage_unlocked=extract("_complete_stage_unlocked")
    def __init__(self):
        self.lock=threading.RLock()
        self.scraping_gpio=SimpleNamespace(cancel_pending=lambda:None)
        self.auto_advance_enabled=False;self.transition_timeout_s=30
        self.cameras={1:SimpleNamespace(id=1),2:SimpleNamespace(id=2)}
        self.scales={"s":SimpleNamespace(id="scale_1")}
        self.bronkhorst={};self.wago={};self.plugin_sensors={};self.atlas=object()
        self.sensor_calibration={"froth_interface":{"status":"passed"}}
        self.stage_acquisition_overrides={}
        self.experiment={"stages":[{"uid":"a","type":"conditioning","duration":0,"metadata":{"transition":{"auto_advance":True,"timeout_s":7},
            "acquisition":{"mode":"custom","enabled":{"video/1":True,"video/2":False,"sensor/scale_1":False,"atlas":True,
                "virtual/froth_interface":False}}}},
            {"uid":"b","type":"flotation","duration":60,"metadata":{}}]}
        self.current_stage_index=0;self.stage_attempt=1;self.stage_state=self.STAGE_TRANSITION;self.state=self.RUNNING
        self.stage_started_monotonic=None;self.events=[];self.vision=None
    @property
    def current_stage(self):return self.experiment["stages"][self.current_stage_index]
    @property
    def next_stage(self):return self.experiment["stages"][self.current_stage_index+1] if self.current_stage_index+1<len(self.experiment["stages"]) else None
    def stage_policy(self,stage): return {"camera":stage.get("type")!="conditioning","sensors":True,"scraping":stage.get("type")=="flotation"}
    def apply_stage_setpoints(self,stage): pass
    def _reconcile_stage_acquisition_unlocked(self,stage): self.events.append("reconcile")
    def _scraping_required(self,stage):return False
    def _scraping_interval(self,stage):return 5
    def _touch_unlocked(self,event,data=None):self.events.append(event)
    def _sync_execution_state_unlocked(self,*args,**kwargs):pass
    def _append_event_unlocked(self,event,data):self.events.append(event)
    def _stop_camera_recording_unlocked(self,ignore_errors=False,keep_ids=None):self.video_keep=keep_ids
    def _stop_sensor_recording_unlocked(self,keep_ids=None):self.sensor_keep=keep_ids
    def _finish_experiment_unlocked(self):self.events.append("done")

class StageTests(unittest.TestCase):
    def test_manual_stage_never_schedules_deadline(self):
        run=Fake();run._start_stage_unlocked(run.current_stage)
        self.assertIsNone(run.stage_deadline)
        self.assertIsNotNone(run.stage_started_monotonic)
        self.assertIn("STAGE_STARTED",run.events)

    def test_manual_completion_is_not_marked_early_and_uses_stage_timeout(self):
        run=Fake();run._start_stage_unlocked(run.current_stage)
        run._complete_stage_unlocked(early=True)
        self.assertIn("STAGE_COMPLETED",run.events)
        self.assertNotIn("STAGE_FINISHED_EARLY",run.events)
        self.assertAlmostEqual(run.transition_deadline-time.monotonic(),7,delta=.3)

    def test_video_defaults_are_type_based_and_physical_recorders_default_on(self):
        run=Fake();first=run._stage_acquisition_unlocked(run.current_stage)
        self.assertEqual(first,{"video":[1],"physical":["atlas"],"hifie":False})
        second=run._stage_acquisition_unlocked(run.next_stage)
        self.assertEqual(second["video"],[1,2])
        self.assertIn("scale_1",second["physical"])
        self.assertTrue(second["hifie"])
        run.stage_acquisition_overrides["1"]={"video/1":False,"sensor/scale_1":False}
        second=run._stage_acquisition_unlocked(run.next_stage)
        self.assertEqual(second["video"],[2])
        self.assertNotIn("scale_1",second["physical"])

if __name__=="__main__":unittest.main()
