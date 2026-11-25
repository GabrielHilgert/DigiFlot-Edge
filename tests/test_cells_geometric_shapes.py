"""Visual cross-section geometry is independent of ArUco, volume and named references."""
import math
import tempfile
import unittest

from lib.vision.registry import VisionRegistry
from lib.vision.shapes import estimate_area, normalize_shapes


class ShapeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.registry=VisionRegistry(self.temp.name)
        self.cell=self.registry.save_cell({"name":"4L", "geometry":{"shape":"rectangular",
            "height_mm":200,"width_mm":160,"depth_mm":100}})
        eye=[[1,0,0],[0,1,0],[0,0,1]]
        self.assoc=self.registry.save_association(1,self.cell["id"],{"H":eye,"H_inv":eye,
            "frame":{"size":[800,600],"sensor_crop":[0,0,800,600]},
            "size":[800,600],"rms_px":.2})

    def item(self,kind="rectangle",anchor="horizontal"):
        return {"id":"shape_a","name":"Inner section","kind":kind,"plane":"XY",
            "camera_id":"2","camera_revision":0,"image_space":"undistorted",
            "frame_size":[800,600],"bounds_norm":[[.2,.2],[.6,.6]],
            "anchor_field":"width_mm","anchor_axis":anchor}

    def test_rectangle_area_linked_to_existing_width(self):
        saved=self.registry.save_geometric_shapes(self.cell["id"],{"items":[self.item()],"expected_revision":0})
        self.assertEqual(saved["revision"],1)
        self.assertEqual(self.registry.save_geometric_shapes(self.cell["id"],{"items":saved["items"]})["revision"],1)
        cell=self.registry.get_cell(self.cell["id"])
        # Pixel dimensions: 320 x 240; known width 16 cm -> inferred depth 12 cm.
        self.assertAlmostEqual(cell["visual_area_estimates"][0]["area_cm2"],192)
        self.assertAlmostEqual(cell["resolved_dimensions"]["visual_area_cm2"],192)
        self.assertEqual(cell["resolved_dimensions"]["geometric_area_cm2"],160)
        self.assertEqual(self.registry.association(1,self.cell["id"])["calibration_id"],self.assoc["calibration_id"])
        self.assertEqual(cell["reference_points_revision"],0)
        self.assertFalse(cell["volume_calibration"]["valid"])
        self.registry.save_camera_profile(2,{"roi_norm":[.1,.1,.9,.9]})
        changed=self.registry.get_cell(self.cell["id"])
        self.assertFalse(changed["visual_area_estimates"][0]["valid"])
        self.assertIsNone(changed["resolved_dimensions"]["visual_area_cm2"])

    def test_square_circle_and_vertical_anchor(self):
        known={"width_mm":{"value_mm":160,"source":"measured"}}
        square=estimate_area(self.item("square"),known,0)
        circle=estimate_area(self.item("circle"),known,0)
        rectangle=estimate_area(self.item("rectangle","vertical"),known,0)
        self.assertAlmostEqual(square["area_cm2"],256)
        self.assertAlmostEqual(circle["area_cm2"],math.pi*64)
        self.assertAlmostEqual(rectangle["area_cm2"],256*320/240)

    def test_validation_preserves_other_saved_calibrations(self):
        saved=self.registry.save_geometric_shapes(self.cell["id"],{"items":[self.item()]})
        self.registry.archive_cell(self.cell["id"])
        with self.assertRaises(RuntimeError):self.registry.delete_empty_cell(self.cell["id"])
        with self.assertRaisesRegex(RuntimeError,"another tab"):
            self.registry.save_geometric_shapes(self.cell["id"],{
                "items":[self.item("circle")],"expected_revision":0})
        for altered in [{**self.item(),"plane":"XZ"},
                        {**self.item(),"bounds_norm":[[0,0],[0,0]]},
                        {**self.item(),"anchor_axis":"radial"}]:
            with self.assertRaises(ValueError):
                normalize_shapes({"items":[altered]})
        self.assertEqual(saved["revision"],1)


if __name__=="__main__":unittest.main()
