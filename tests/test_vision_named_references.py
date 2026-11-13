"""Versioned named physical points and exact-frame browser monitor."""
import json
import tempfile
import unittest

import cv2
import numpy as np

from lib.vision.registry import VisionRegistry
from lib.vision.reference import default_reference_points, normalize_reference_points, resolve_vertical_reference
from lib.vision.service import encode_monitor_frame
from lib.virtual_sensors.interface import normalized_config, config_signature


class NamedReferenceTests(unittest.TestCase):
    def setUp(self):
        self.layout={"dictionary":"DICT_4X4_50","marker_ids":[0,1,2],
                     "marker_size_cm":2.,"span_cm":14.}

    def test_outlet_is_initial_named_default_and_unplaced(self):
        data=default_reference_points()
        self.assertEqual(data["default_reference_id"], "outlet_level")
        self.assertIsNone(data["points"][0]["position_cm"])
        self.assertEqual(data["points"][1]["id"], "aruco_reference")
        with self.assertRaisesRegex(ValueError,"no physical position"):
            resolve_vertical_reference({"reference_id":"outlet_level"},{"reference_points":data})

    def test_unlimited_named_points_and_camera_independent_coordinates(self):
        with tempfile.TemporaryDirectory() as folder:
            registry=VisionRegistry(folder)
            cell=registry.save_cell({"name":"Test flotation cell"})
            original=registry.reference_points(cell["id"])
            self.assertEqual(original["default_reference_id"],"outlet_level")
            positions=[[1.5,6.],[3.,8.]]
            points=original["points"]+[
                {"id":"new_"+str(i),"name":"Level "+str(i),"type":"custom",
                 "source":"image_selection","position_cm":[float(i),float(i+1)],
                 "direction":"up"} for i in range(18)]
            points[0]={**points[0],"position_cm":positions[0],"source":"image_selection"}
            saved=registry.save_reference_points(cell["id"],{
                "default_reference_id":"outlet_level","points":points})
            self.assertEqual(len(saved["points"]),20)
            self.assertEqual(saved["revision"],1)
            self.assertEqual(registry.save_reference_points(cell["id"],saved)["revision"],1)
            association={"reference_points":saved,"calibration":{"layout":self.layout}}
            datum=resolve_vertical_reference({"reference_id":"outlet_level"},association)
            self.assertEqual(datum["y_cm"],6.)
            self.assertEqual(datum["direction"],"up")
            self.assertEqual(datum["name"],"Outlet level")
            self.assertEqual(datum["reference_revision"],1)
            sig=config_signature(normalized_config({"reference_id":"outlet_level"}),association)
            changed=registry.save_reference_points(cell["id"],{
                "default_reference_id":"outlet_level",
                "points":[{**p,"position_cm":[1.5,7.]} if p["id"]=="outlet_level" else p for p in saved["points"]]})
            self.assertNotEqual(sig,config_signature(normalized_config({"reference_id":"outlet_level"}),
                               {**association,"reference_points":changed}))
            json.dumps(registry.get_cell(cell["id"]))
            with self.assertRaisesRegex(ValueError,"unique"):
                normalize_reference_points({"default_reference_id":"outlet_level",
                    "points":[points[0],points[0]]})

    def test_top_depth_and_automatic_marker(self):
        library=default_reference_points()
        library["points"].append({"id":"rim","name":"Top rim","type":"top",
                                  "position_cm":[2.,-8.],"source":"measured","direction":"down"})
        assoc={"reference_points":library,"calibration":{"layout":self.layout}}
        self.assertEqual(resolve_vertical_reference({"reference_id":"rim"},assoc)["y_cm"],-8.)
        self.assertEqual(resolve_vertical_reference({"reference_id":"aruco_reference"},assoc)["y_cm"],14.)

    def test_monitor_uses_original_detector_rows_and_scales_image_only(self):
        image=np.full((120,160),110,dtype=np.uint8)
        cv2.line(image,(0,37),(159,37),240,3)
        sample={"froth_surface_row_px":37,"pulp_froth_row_px":89,"valid":True,
                "camera_id":1,"cell_id":"cell_test"}
        result=encode_monitor_frame(image,sample,1700000000000000000,requested_width=96)
        self.assertEqual(result["source_size"],[160,120])
        self.assertEqual(result["output_size"],[96,72])
        self.assertEqual(result["froth_row_px"],37)
        self.assertEqual(result["pulp_row_px"],89)
        import base64
        decoded=cv2.imdecode(np.frombuffer(base64.b64decode(result["jpeg_base64"]),
                            dtype=np.uint8),cv2.IMREAD_GRAYSCALE)
        self.assertEqual(decoded.shape,(72,96))


if __name__=="__main__":
    unittest.main()
