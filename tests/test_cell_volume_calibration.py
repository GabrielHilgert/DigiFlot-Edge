"""Cell experimental V(h): anchored bottom, custom references and versioned updates."""
import math
import tempfile
import unittest

from lib.vision.cell_metrics import normalize_volume_curve, evaluate_volume_curve, volume_curve_is_current
from lib.vision.registry import VisionRegistry
from lib.vision.derived_measurements import derive_hifie_value


class VolumeCurveTests(unittest.TestCase):
    def setUp(self):
        self.cell = {"id":"cellA","revision":4,
            "geometry":{"shape":"custom"},
            "marker_layout":{"marker_ids":[0,1,2],"marker_size_cm":2.,"span_cm":14.},
            "reference_points_revision":3,
            "reference_points":{"revision":3,"default_reference_id":"outlet_level","points":[
                {"id":"outlet_level","name":"Outlet level","type":"custom","position_cm":[0.,2.],
                 "direction":"up","source":"measured"},
                {"id":"aruco_reference","name":"ArUco reference","type":"aruco","position_cm":None,
                 "direction":"up","source":"automatic"},
                {"id":"cell_top","name":"Cell top","type":"top","position_cm":[0.,-8.],
                 "direction":"down","source":"measured"},
                {"id":"cell_bottom","name":"Cell bottom","type":"bottom","position_cm":[0.,12.],
                 "direction":"up","source":"measured"}]},
            "resolved_dimensions":{"dimensions":{"height_mm":{"value_mm":200,"source":"measured"}}}}

    def test_custom_reference_and_origin(self):
        result=normalize_volume_curve(self.cell, {"datum_reference_id":"outlet_level","points":[
            {"height_cm":-4.,"volume_l":.3}, {"height_cm":1.,"volume_l":.7}]})
        self.assertEqual(result["points"][0], {"height_cm":0.,"volume_l":0.,"fixed_origin":True})
        self.assertEqual([x["height_cm"] for x in result["points"]],[0.,6.,11.])
        self.assertAlmostEqual(result["area_range_cm2"][0],50.)
        self.assertAlmostEqual(result["area_range_cm2"][1],80.)
        result.update(valid=True,revision=9)
        self.assertAlmostEqual(evaluate_volume_curve(result,8.)["volume_l"],.46)
        above=evaluate_volume_curve(result,14.)
        self.assertTrue(above["extrapolated"])
        self.assertAlmostEqual(above["volume_l"],.94)
        self.assertAlmostEqual(above["effective_area_cm2"],80.)

    def test_unknown_bottom_or_datum_not_silently_inferred(self):
        self.cell["reference_points"]["points"][3]["position_cm"]=None
        with self.assertRaisesRegex(ValueError,"Cell bottom"):
            normalize_volume_curve(self.cell,{"datum_reference_id":"outlet_level","points":[
                {"height_cm":4,"volume_l":1.}]})

    def test_monotonic_validation_and_cell_height(self):
        with self.assertRaisesRegex(ValueError,"nondecreasing"):
            normalize_volume_curve(self.cell,{"points":[{"height_cm":4,"volume_l":.5},
                                                        {"height_cm":8,"volume_l":.4}]})
        with self.assertRaisesRegex(ValueError,"inside"):
            normalize_volume_curve(self.cell,{"points":[{"height_cm":25,"volume_l":1.}]})

    def test_revision_invalidated_by_reference_edits(self):
        curve=normalize_volume_curve(self.cell,{"points":[{"height_cm":6,"volume_l":.3}]})
        self.assertTrue(volume_curve_is_current(self.cell,curve))
        self.cell["reference_points_revision"]+=1
        self.assertFalse(volume_curve_is_current(self.cell,curve))

    def test_registry_persists_separate_curve(self):
        with tempfile.TemporaryDirectory() as root:
            registry=VisionRegistry(root)
            record=registry.save_cell({"name":"Test","geometry":{"shape":"custom"}})
            pts=self.cell["reference_points"]
            registry.save_reference_points(record["id"],pts)
            saved=registry.save_volume_calibration(record["id"],{
                "datum_reference_id":"outlet_level","points":[{"height_cm":-4,"volume_l":.3}]})
            self.assertEqual(saved["revision"],1)
            cell=registry.get_cell(record["id"])
            self.assertTrue(cell["volume_calibration"]["valid"])
            self.assertEqual(cell["revision"],record["revision"])
            modified=registry.reference_points(record["id"])
            modified["points"][0]["position_cm"]=[0.,3.]
            registry.save_reference_points(record["id"],modified)
            self.assertFalse(registry.get_cell(record["id"])["volume_calibration"]["valid"])

    def test_hifie_prefers_curve_without_geometric_area(self):
        curve=normalize_volume_curve(self.cell,{"points":[{"height_cm":10.,"volume_l":.8}]})
        curve.update(valid=True,revision=2)
        self.cell["volume_calibration"]=curve
        self.cell["resolved_dimensions"]["geometric_area_cm2"]=None
        sensor={"reading_valid":True,"reference":{"direction":"up","y_cm":12.},
                "channels":{"pulp_froth_interface_cm":5.}}
        options={"references":[{"id":"current","name":"Current"},
                               {"id":"cell_bottom","name":"Bottom","direction":"up","y_cm":12.}]}
        observation=derive_hifie_value(sensor,self.cell,options,"pulp_froth_interface_cm",
                                       "cell_bottom","volume_l")
        self.assertAlmostEqual(observation["value"],.4)
        self.assertEqual(observation["metadata"]["volume_model"],"calibrated_volume_curve")
        self.assertEqual(observation["metadata"]["volume_calibration_revision"],2)


if __name__=="__main__":
    unittest.main()
