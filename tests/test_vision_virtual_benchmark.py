"""Camera-independent regression checks for mandatory benchmark and frozen run snapshots."""
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from lib.vision.aruco import DEFAULT_LAYOUT, calibrate, source_geometry
from lib.vision.service import VisionService
from test_vision_aruco import synthetic_ruler


class FakeCamera:
    IDLE, PREVIEW, RECORDING = "Idle", "Preview", "Recording"
    def __init__(self):
        self.id = 1
        self.name = "Side"
        self.state = self.IDLE
        self.analysis_enabled = False
        self.analysis_target_size = None
        self.frame_size = (900, 920)
        self.frame_rate = 30
        self.crop_region = None
        self.format = "YUV420"
        self.exposure_time_us = 12000
        self.analogue_gain = 1.
        self.started = self.stopped = False
        self.image = synthetic_ruler()
    @property
    def recording(self):
        return self.state == self.RECORDING
    def full_sensor_crop(self):
        return (0, 0, 900, 920)
    def start_recording(self, output_base):
        self.started = True
        self.state = self.RECORDING
    def stop_recording(self):
        self.stopped = True
        self.state = self.IDLE
    def recording_metrics(self):
        return {"actual_fps": 30., "frame_count": 100}
    def capture_analysis_frame(self, grayscale=False, raw_yuv=False):
        return self.image.copy(), source_geometry([900, 920], self.full_sensor_crop())


class FakeRun:
    SENSOR_CALIBRATION = "SensorCalibration"
    def __init__(self):
        self.cameras = {1: FakeCamera()}
        self.state = self.SENSOR_CALIBRATION
        self.virtual_camera_id = 1
        self.cell_profile = {}
        self.preview_camera_id = None
        self.sensor_calibration = {"froth_interface":{"status":"pending"}}
        self.lock = threading.RLock()
        self.execution_locked = False
        self.recording = False
        self.run_directory = None
    def get_camera(self, camera_id):
        return self.cameras[int(camera_id)]
    def camera_summaries(self):
        return [{"id":1,"name":"Side"}]
    def _touch_unlocked(self, *args, **kwargs):
        pass


class VirtualBenchmarkTests(unittest.TestCase):
    def test_test_is_required_and_stale_profiles_cannot_start(self):
        with tempfile.TemporaryDirectory() as root:
            run = FakeRun()
            vision = VisionService(run, root)
            run.vision = vision
            cell = vision.registry.save_cell({"name": "Bench cell"})
            run.cell_profile = {"physical_cell_id": cell["id"]}
            geometry = source_geometry([900,920],[0,0,900,920])
            cal = calibrate(run.cameras[1].image, DEFAULT_LAYOUT, frame_geometry=geometry)
            vision.registry.save_association(1, cell["id"], cal)
            vision.registry.save_analysis_roi(1, cell["id"], [2,2,10,10])
            self.assertFalse(vision.virtual_test_passed())
            with self.assertRaises(RuntimeError):
                vision.freeze_run_config(Path(root) / "run")
            vision.save_virtual_profile({"resolution_px":128, "sampling_interval_s": 1.})
            reading = {"valid":True, "froth_surface_cm":4., "pulp_froth_interface_cm":7.,
                       "froth_thickness_cm":3., "froth_surface_row_px":20,
                       "pulp_froth_row_px":50}
            with patch("lib.vision.service.detect_interface", return_value=reading):
                result = vision.benchmark_virtual_sensor(samples=12)
            self.assertTrue(result["passed"], result)
            self.assertEqual(result["mode"], "paced_main_encoder_and_lores")
            self.assertGreaterEqual(result["main_recording_fps"], result["min_recording_fps"])
            self.assertTrue(run.cameras[1].started and run.cameras[1].stopped)
            self.assertEqual(run.cameras[1].state, run.cameras[1].IDLE)
            self.assertTrue(vision.virtual_test_passed())
            run_dir = Path(root) / "run"
            run_dir.mkdir()
            snap = vision.freeze_run_config(run_dir)
            self.assertEqual(snap["cell_id"], cell["id"])
            self.assertTrue((run_dir / "virtual_sensors" / "froth_interface.json").is_file())
            run2 = FakeRun()
            restored = VisionService(run2, root)
            self.assertTrue(restored.restore_run_config(run_dir))
            self.assertEqual(restored._run_virtual["config"], snap["config"])
            vision.save_virtual_profile({"resolution_px":256})
            self.assertFalse(vision.virtual_test_passed())
            self.assertEqual(run.sensor_calibration["froth_interface"]["status"],"pending")


if __name__ == "__main__":
    unittest.main()
