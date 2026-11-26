"""Require measurements captured in the current manual stage attempt before advancing."""
import ast, threading, unittest
from pathlib import Path
from types import SimpleNamespace

SOURCE=Path(__file__).resolve().parents[1]/"src/lib/digiflot.py"
TREE=ast.parse(SOURCE.read_text())
OWNER=next(n for n in TREE.body if isinstance(n,ast.ClassDef) and n.name=="DigiFlot")
def method(name):
    fn=next(n for n in OWNER.body if isinstance(n,ast.FunctionDef) and n.name==name)
    ns={"deepcopy":__import__("copy").deepcopy,"_utc_now":lambda:"2026-11-23T18:00:00Z"}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),str(SOURCE),"exec"),ns)
    return ns[name]

class Run:
    RECOVERY_REQUIRED="RecoveryRequired"
    _stage_measurement_variables_unlocked=method("_stage_measurement_variables_unlocked")
    STAGE_TRANSITION="Transition";STAGE_ACTIVE="Active";RUNNING="Running";READY="Ready";PAUSED="Paused"
    _stage_measurement_gate_unlocked=method("_stage_measurement_gate_unlocked")
    start_next_stage=method("start_next_stage")
    ignore_stage_measurement_requirements=method("ignore_stage_measurement_requirements")
    def __init__(self):
        self.lock=threading.RLock();self.state=self.RUNNING;self.stage_state=self.STAGE_TRANSITION
        self.current_stage_index=0;self.stage_attempt=1;self.started=[]
        self.experiment={"stages":[
            {"uid":"stage-A","name":"Manual conditioning","type":"conditioning","duration":0,
             "metadata":{"variables":{"viscosity":{"label":"Viscosity","unit":"Pa s","required_measurement":True},
                                       "density":{"label":"Density","unit":"g/L","required_measurement":True}}}},
            {"uid":"stage-B","name":"Flotation","type":"flotation","duration":80,"metadata":{}}]}
        self.measurements=[];self.stage_measurement_waivers=[];self.stage_history=[
            {"stage_index":0,"attempt":1,"started_at":"2026-11-23T18:00:00Z","completion":"STAGE_COMPLETED"}]
        self.events=[];self.transition_deadline=None
    @property
    def status(self):return {"state":self.state,"stage_index":self.current_stage_index}
    @property
    def current_stage(self):return self.experiment["stages"][self.current_stage_index]
    @property
    def next_stage(self):
        i=self.current_stage_index+1
        return self.experiment["stages"][i] if i<len(self.experiment["stages"]) else None
    def _measurement_variable_id(self,v):
        import re,unicodedata
        v=unicodedata.normalize("NFKD",str(v or "")).encode("ascii","ignore").decode("ascii").strip().lower()
        return re.sub(r"[^a-z0-9]+","_",v).strip("_")
    def _start_stage_unlocked(self,stage,new_attempt=False):self.started.append(stage["uid"])
    def _touch_unlocked(self,event,data=None):self.events.append((event,data))
    def _sync_execution_state_unlocked(self):pass

class ManualMeasurementTests(unittest.TestCase):
    def test_stage_variables_are_predefined_and_attempt_scoped(self):
        run=Run()
        run.stage_state="Active"
        run.measurements=[{"variable_id":"viscosity","stage_index":0,"stage_attempt":0,"value":7.},
                          {"variable_id":"density","stage_index":0,"stage_attempt":1,"value":5.,
                           "unit":"g/L"}]
        data=run._stage_measurement_variables_unlocked()
        self.assertEqual([x["name"] for x in data["items"]],["Viscosity","Density"])
        self.assertTrue(all(x["required"] for x in data["items"]))
        self.assertEqual(data["items"][0]["points"],0)
        self.assertEqual(data["items"][1]["points"],1)
        self.assertEqual(data["items"][1]["unit"],"g/L")

    def test_missing_required_variables_prevent_manual_and_automatic_advance(self):
        run=Run();gate=run._stage_measurement_gate_unlocked()
        self.assertTrue(gate["blocked"])
        self.assertEqual([x["id"] for x in gate["missing"]],["viscosity","density"])
        with self.assertRaisesRegex(RuntimeError,"Viscosity, Density"):
            run.start_next_stage()
        self.assertEqual(run.current_stage_index,0)

    def test_only_measurements_from_same_attempt_count(self):
        run=Run()
        run.measurements=[
            {"variable_id":"viscosity","stage_index":0,"stage_attempt":0,"stage_state":"Active"},
            {"variable_id":"density","stage_index":1,"stage_attempt":1,"stage_state":"Active"},
            {"variable_id":"viscosity","stage_index":0,"stage_attempt":1,"stage_state":"Active"}]
        self.assertEqual([x["id"] for x in run._stage_measurement_gate_unlocked()["missing"]],["density"])
        run.measurements.append({"variable_id":"density","stage_index":0,"stage_attempt":1,
                                 "stage_state":"Transition"})
        self.assertFalse(run._stage_measurement_gate_unlocked()["blocked"])
        run.start_next_stage()
        self.assertEqual(run.started,["stage-B"])

    def test_saved_label_is_valid_if_identifier_differs(self):
        run=Run();run.experiment["stages"][0]["metadata"]["variables"]={
            "specific_gravity":{"label":"Relative density","required_measurement":True}}
        run.measurements=[{"variable_id":"relative_density","stage_index":0,"stage_attempt":1,
                           "stage_state":"Transition"}]
        self.assertFalse(run._stage_measurement_gate_unlocked()["blocked"])

    def test_ignore_is_explicit_and_audited(self):
        run=Run();run.ignore_stage_measurement_requirements("Operator accepted incomplete sampling")
        self.assertEqual(run.started,["stage-B"])
        self.assertEqual(len(run.stage_measurement_waivers),1)
        self.assertEqual(len(run.stage_measurement_waivers[0]["missing"]),2)
        self.assertEqual(run.events[0][0],"STAGE_REQUIRED_MEASUREMENTS_IGNORED")
        self.assertEqual(run.stage_measurement_waivers[0]["reason"],"Operator accepted incomplete sampling")

    def test_skip_does_not_require_an_additional_waiver(self):
        run=Run();run.stage_history[-1]["completion"]="STAGE_SKIPPED"
        self.assertFalse(run._stage_measurement_gate_unlocked()["blocked"])

    def test_final_manual_stage_never_blocks(self):
        run=Run();run.current_stage_index=1
        run.experiment["stages"][1]["duration"]=0
        run.experiment["stages"][1]["metadata"]={"variables":{"mass":{"required_measurement":True}}}
        self.assertFalse(run._stage_measurement_gate_unlocked()["blocked"])

if __name__=="__main__":unittest.main()
