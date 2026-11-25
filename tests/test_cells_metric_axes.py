"""Physical axis projection and cross-camera known-length calibration regressions."""
import math
import tempfile
import unittest

from lib.vision.cell_metrics import normalize_dimension_pairs, resolve_cell_dimensions, projected_distance_cm
from lib.vision.reference import default_reference_points
from lib.vision.registry import VisionRegistry


class AxisAndRelativeTests(unittest.TestCase):
    def test_horizontal_vertical_direct_do_not_require_aligned_references(self):
        points=default_reference_points()
        points["points"].extend([
            {"id":"pA","name":"A","type":"custom","position_cm":[2,3],"source":"measured","direction":"up"},
            {"id":"pB","name":"B","type":"custom","position_cm":[8,11],"source":"measured","direction":"up"}])
        mapping={"pairs":{"width_mm":{"from_id":"pA","to_id":"pB","axis":"horizontal"},
            "depth_mm":{"from_id":"pA","to_id":"pB","axis":"vertical"},
            "collection_height_mm":{"from_id":"pA","to_id":"pB","axis":"direct"}}}
        normalized=normalize_dimension_pairs(mapping,points)
        measured=resolve_cell_dimensions({"geometry":{"shape":"rectangular"},
            "reference_points":points}, {"pairs":normalized})["dimensions"]
        self.assertAlmostEqual(measured["width_mm"]["value_mm"],60)
        self.assertAlmostEqual(measured["depth_mm"]["value_mm"],80)
        self.assertAlmostEqual(measured["collection_height_mm"]["value_mm"],100)
        self.assertAlmostEqual(projected_distance_cm([2,3],[8,11],"direct"),10)
        old=normalize_dimension_pairs({"pairs":{"width_mm":{"from_id":"pA","to_id":"pB"}}},points)
        self.assertEqual(old["width_mm"]["axis"],"direct")
        with self.assertRaisesRegex(ValueError,"axis"):
            normalize_dimension_pairs({"pairs":{"width_mm":{"from_id":"pA","to_id":"pB","axis":"z"}}},points)

    def test_height_uses_explicit_named_pair_when_supplied(self):
        points=default_reference_points()
        for p in points["points"]:
            if p["id"]=="cell_top":p.update(position_cm=[0,0],source="measured")
            if p["id"]=="cell_bottom":p.update(position_cm=[0,20],source="measured")
        points["points"].extend([
            {"id":"a","name":"A","type":"custom","position_cm":[0,3],"source":"measured","direction":"up"},
            {"id":"b","name":"B","type":"custom","position_cm":[8,16],"source":"measured","direction":"up"}])
        mapping={"pairs":{"height_mm":{"from_id":"a","to_id":"b","axis":"vertical"}}}
        result=resolve_cell_dimensions({"reference_points":points},mapping)
        self.assertAlmostEqual(result["dimensions"]["height_mm"]["value_mm"],130)
        self.assertEqual(result["dimensions"]["height_mm"]["references"],["a","b"])
        self.assertAlmostEqual(resolve_cell_dimensions({"reference_points":points})["dimensions"]["height_mm"]["value_mm"],200)

    def test_known_source_metric_pair_and_target_axis_are_distinct(self):
        with tempfile.TemporaryDirectory() as path:
            registry=VisionRegistry(path)
            cell=registry.save_cell({"name":"4L","geometry":{"shape":"rectangular",
                "width_mm":100,"depth_mm":80,"height_mm":160}})
            eye=[[1,0,0],[0,1,0],[0,0,1]]
            source=registry.save_association(1,cell["id"],{"H":eye,"H_inv":eye,
                "frame":{"size":[800,600],"sensor_crop":[0,0,800,600]},
                "rms_px":.2,"size":[800,600]})
            payload={"source_camera_id":1,"source_calibration_id":source["calibration_id"],
                "source_camera_revision":0,"source_points_cm":[[2,3],[14,8]],
                "source_axis":"horizontal","reference_field":"width_mm",
                "target_field":"depth_mm","frame_size":[800,600],
                "reference_pair":[[.1,.2],[.5,.5]],"reference_axis":"horizontal",
                "target_pair":[[.2,.3],[.4,.7]],"target_axis":"vertical",
                "image_space":"undistorted","capture_camera_id":2,"camera_revision":0}
            result=registry.save_relative_calibration(2,cell["id"],payload)
            self.assertEqual(result["source_mode"],"calibrated_pair")
            self.assertAlmostEqual(result["reference_mm"],120)
            self.assertAlmostEqual(result["target_mm"],90)
            resolved=registry.get_cell(cell["id"])
            self.assertTrue(resolved["relative_measurements"][0]["valid"])
            self.assertEqual(resolved["resolved_dimensions"]["dimensions"]["depth_mm"]["source"],"relative_estimate")
            self.assertIsNone(registry.association(2,cell["id"]))
            self.assertEqual(registry.association(1,cell["id"])["calibration_id"],source["calibration_id"])
            with self.assertRaisesRegex(RuntimeError,"source image changed"):
                registry.save_relative_calibration(2,cell["id"],{**payload,"source_calibration_id":"wrong"})


if __name__=="__main__":unittest.main()
