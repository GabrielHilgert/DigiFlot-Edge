"""Interactive tuning uses a captured ROI; it never touches camera or stored calibration."""
import tempfile
import time
import unittest
from unittest.mock import patch

import numpy as np

from lib.vision.aruco import DEFAULT_LAYOUT, calibrate, source_geometry
from lib.vision.service import VisionService
from lib.virtual_sensors.interface import normalized_config
from test_vision_virtual_benchmark import FakeRun


class TuningTests(unittest.TestCase):
    def make_service(self, root):
        run=FakeRun()
        vision=VisionService(run,root)
        cell=vision.registry.save_cell({"name":"Interactive tuning"})
        run.cell_profile={"physical_cell_id":cell["id"]}
        cal=calibrate(run.cameras[1].image, DEFAULT_LAYOUT,
                      frame_geometry=source_geometry([900,920],[0,0,900,920]))
        vision.registry.save_association(1,cell["id"],cal)
        roi=[2.,2.,12.,12.]
        vision.registry.save_analysis_roi(1,cell["id"],roi)
        config=normalized_config({"method":"mean_derivative","entropy_radius":3,
                                  "entropy_bins":12,"resolution_px":100,
                                  "detection_roi_cm":roi,"min_row":4})
        vision.registry.save_virtual_profile(1,cell["id"],config)
        rng=np.random.default_rng(1)
        image=rng.integers(35,210,(100,100,3),dtype=np.uint8)
        image[40:65]=90
        vision._reference_frame={"image":image,"roi":roi,"density":10.,
                              "reference":{"mode":"cell_bottom","direction":"up","y_cm":12.},
                              "camera_id":"1","cell_id":str(cell["id"]),
                              "calibration_id":cal["id"] if "id" in cal else
                                  vision.registry.association(1,cell["id"])["calibration_id"],
                              "timestamp_ns":time.time_ns(),"received_at":time.monotonic()}
        vision._diagnostic_until=time.monotonic()+20.
        vision._reference_owner_id="tab-a"
        return vision,config

    def test_reference_is_frozen_from_initial_plane_without_live_diagnostics(self):
        with tempfile.TemporaryDirectory() as root:
            vision,config=self.make_service(root)
            vision._reference_frame=None
            vision._reference_owner_id=None
            vision._diagnostic_until=0.
            with patch.object(vision,"_rectify_captured",
                              return_value={"jpeg_base64":"mock","size":[200,200],"plane":{}}):
                plane=vision.virtual_detection_roi_preview(owner_id="tab-a")
            self.assertTrue(plane["reference_ready"], plane)
            frozen=vision._reference_frame
            self.assertIsNotNone(frozen)
            self.assertEqual(vision._reference_owner_id,"tab-a")
            self.assertTrue(frozen["image"].shape[0]>0)
            self.assertEqual(frozen["roi"],[2.,2.,12.,12.])
            with patch.object(vision,"_capture",side_effect=AssertionError("No second camera capture")):
                first=vision.preview_virtual_tuning({"config":config},"tab-a")
                second=vision.preview_virtual_tuning({"config":{**config,"entropy_bins":20}},"tab-a")
            self.assertTrue(first["cached_frame"])
            self.assertTrue(second["cached_frame"])
            self.assertIs(vision._reference_frame,frozen, "Sliders must never replace the reference frame")

    def test_sliders_recompute_without_camera_or_profile_mutation(self):
        with tempfile.TemporaryDirectory() as root:
            vision,config=self.make_service(root)
            original=vision._virtual_context()[3]["config"]
            draft={**config,"entropy_bins":16,"temporal_filter":"ema","temporal_strength":.7}
            with patch.object(vision,"_capture",side_effect=AssertionError("Camera capture forbidden")):
                value=vision.preview_virtual_tuning({"config":draft,
                    "reference_rows_px":[25.,72.]},"tab-a")
            self.assertTrue(value["processing_only"])
            self.assertTrue(value["cached_frame"])
            self.assertFalse(value["requires_camera_reconfiguration"])
            diag=value["diagnostic"]
            self.assertEqual(diag["image_size"],[100,100])
            self.assertEqual(diag["reference_rows_px"],[25.,72.])
            self.assertEqual(vision._virtual_context()[3]["config"],original)

    def test_refit_is_bounded_opt_in_and_unsaved(self):
        with tempfile.TemporaryDirectory() as root:
            vision,config=self.make_service(root)
            with patch.object(vision,"_capture",side_effect=AssertionError("Camera capture forbidden")):
                fit=vision.fit_virtual_tuning({"config":config,
                        "reference_rows_px":[27.,70.]},"tab-a")
            self.assertFalse(fit["applied"])
            self.assertFalse(fit["thresholds_included"])
            self.assertLessEqual(fit["evaluations"],7)
            self.assertTrue(set(fit["suggested"]).issubset({"entropy_radius","entropy_bins","sigma"}))
            self.assertEqual(vision._virtual_context()[3]["config"],config)

    def test_ownership_and_roi_are_enforced(self):
        with tempfile.TemporaryDirectory() as root:
            vision,config=self.make_service(root)
            with self.assertRaisesRegex(RuntimeError,"this tab"):
                vision.preview_virtual_tuning({"config":config},"tab-b")
            altered={**config,"detection_roi_cm":[3.,2.,12.,12.]}
            with self.assertRaisesRegex(ValueError,"Save the new Detection ROI"):
                vision.preview_virtual_tuning({"config":altered},"tab-a")
            with self.assertRaisesRegex(ValueError,"Mark at least one reference"):
                vision.fit_virtual_tuning({"config":config},"tab-a")
            vision._diagnostic_until=0.
            # Frozen references are independent of the live diagnostic lease.
            self.assertTrue(vision.preview_virtual_tuning({"config":config},"tab-a")["cached_frame"])
            vision.release_virtual_reference("tab-b")
            self.assertTrue(vision.preview_virtual_tuning({"config":config},"tab-a")["cached_frame"])
            vision.release_virtual_reference("tab-a")
            with self.assertRaisesRegex(ValueError,"Capture a reference image"):
                vision.preview_virtual_tuning({"config":config},"tab-a")


if __name__=="__main__":
    unittest.main()
