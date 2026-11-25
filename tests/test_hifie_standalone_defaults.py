"""Idle HIFIE defaults must use the last experimental cell/camera, never start capture."""
import ast
import unittest
from pathlib import Path
from types import SimpleNamespace

SERVICE = Path(__file__).resolve().parents[1] / "src/lib/vision/service.py"
OWNER = next(x for x in ast.parse(SERVICE.read_text()).body if isinstance(x, ast.ClassDef) and x.name == "VisionService")


def method(name):
    node = next(x for x in OWNER.body if isinstance(x, ast.FunctionDef) and x.name == name)
    namespace = {}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[])), str(SERVICE), "exec"), namespace)
    return namespace[name]


class FakeRegistry:
    def __init__(self):
        self.pair = {"last_used_cell_id": "cellA", "last_used_camera_id": 2}
        self.associations = {(1, "cellA"): {"cell_revision": 5, "camera_revision": 3},
                             (2, "cellA"): {"cell_revision": 5, "camera_revision": 3}}
    def settings(self): return self.pair
    def get_cell(self, ident):
        if ident != "cellA": raise KeyError(ident)
        return {"id": "cellA", "revision": 5}
    def association(self, camera, cell): return self.associations.get((camera, cell))
    def camera_profile(self, camera): return {"revision": 3}


class StandaloneDefaultTests(unittest.TestCase):
    def setUp(self):
        self.registry = FakeRegistry()
        self.vision = SimpleNamespace(registry=self.registry,
                                      digiflot=SimpleNamespace(cameras={1: None, 2: None}))
        self.suggest = method("_suggest_standalone_hifie")

    def test_prefers_last_used_camera(self):
        self.assertEqual(self.suggest(self.vision), {"cell_id": "cellA", "camera_id": 2, "ready": True})

    def test_falls_back_to_other_calibrated_camera(self):
        self.registry.associations.pop((2, "cellA"))
        self.assertEqual(self.suggest(self.vision), {"cell_id": "cellA", "camera_id": 1, "ready": True})

    def test_uncalibrated_selection_is_not_auto_started(self):
        self.registry.associations.clear()
        self.assertEqual(self.suggest(self.vision), {"cell_id": "cellA", "camera_id": 2, "ready": False})

    def test_missing_cell_is_not_selected(self):
        self.registry.pair["last_used_cell_id"] = "deleted"
        self.assertIsNone(self.suggest(self.vision))


if __name__ == "__main__":
    unittest.main()
