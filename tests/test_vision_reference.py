"""Physical datum semantics independent of camera crops and ArUco calibration history."""
import tempfile
import unittest

from lib.vision.reference import aruco_bottom_y_cm, normalize_cell_reference, resolve_vertical_reference
from lib.vision.registry import VisionRegistry
from lib.virtual_sensors.interface import config_signature, normalized_config


class VerticalReferenceTests(unittest.TestCase):
    def setUp(self):
        self.layout = {"dictionary":"DICT_4X4_50","marker_ids":[0,1,2],
                       "marker_size_cm":2.0,"span_cm":14.0}
        self.association = {"calibration":{"layout":self.layout},
                            "cell_snapshot":{"geometry":{"height_mm":200.},"marker_layout":self.layout},
                            "cell_vertical_reference":{"mode":"aruco_bottom","cell_top_y_cm":None,
                                                       "cell_bottom_y_cm":None,"revision":0}}

    def test_bottommost_marker_is_not_padded_calibration_boundary(self):
        self.assertEqual(aruco_bottom_y_cm(self.layout),14.)
        self.assertEqual(resolve_vertical_reference(normalized_config(),self.association)["y_cm"],14.)

    def test_reference_modes_and_out_of_view_cell_bottom(self):
        config = normalized_config({"vertical_reference_mode":"cell_bottom",
                                    "vertical_reference_y_cm":95.,
                                    "vertical_reference_confirmed":True})
        resolved=resolve_vertical_reference(config,self.association)
        self.assertEqual(resolved["y_cm"],95.)
        self.assertEqual(resolved["direction"],"up")
        top=resolve_vertical_reference(normalized_config({
            "vertical_reference_mode":"cell_top","vertical_reference_y_cm":-8.}),self.association)
        self.assertEqual(top["y_cm"],-8.)
        self.assertEqual(top["direction"],"down")
        with self.assertRaisesRegex(ValueError, "requires a physical Y position"):
            resolve_vertical_reference(normalized_config({
                "vertical_reference_mode":"cell_bottom"}),self.association)

    def test_cell_height_derives_bottom_without_camera_visibility(self):
        assoc=dict(self.association)
        assoc["cell_vertical_reference"]={"mode":"cell_bottom","cell_top_y_cm":-5.,
                                           "cell_bottom_y_cm":None,"revision":2}
        resolved=resolve_vertical_reference(normalized_config(),assoc)
        self.assertAlmostEqual(resolved["y_cm"],15.)
        self.assertEqual(resolved["source"],"cell")

    def test_reference_changes_do_not_invalidate_aruco_association(self):
        with tempfile.TemporaryDirectory() as root:
            store=VisionRegistry(root)
            cell=store.save_cell({"name":"Cell 1","geometry":{"height_mm":300}})
            marker_data={"H":[[1,0,0],[0,1,0],[0,0,1]],
                         "H_inv":[[1,0,0],[0,1,0],[0,0,1]],
                         "frame":{"size":[900,900],"sensor_crop":[0,0,900,900]},
                         "rms_px":0.,"layout":self.layout}
            store.save_association(1,cell["id"],marker_data)
            previous=store.association(1,cell["id"])
            config=normalized_config({"vertical_reference_confirmed":True})
            sig=config_signature(config,previous)
            updated=store.save_cell_vertical_reference(cell["id"],{
                "mode":"cell_bottom","cell_top_y_cm":-4.,"cell_bottom_y_cm":26.})
            self.assertEqual(updated["revision"],1)
            current=store.association(1,cell["id"])
            self.assertEqual(previous["calibration_id"],current["calibration_id"])
            self.assertEqual(previous["cell_revision"],current["cell_revision"])
            self.assertNotEqual(sig,config_signature(config,current))
            self.assertEqual(store.get_cell(cell["id"])["vertical_reference"]["cell_bottom_y_cm"],26.)
            self.assertEqual(resolve_vertical_reference(config,current)["y_cm"],26.)
            self.assertEqual(store.save_cell_vertical_reference(cell["id"],updated)["revision"],1)


if __name__ == "__main__":
    unittest.main()
