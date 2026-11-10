"""Camera-independent regression checks for mandatory benchmark and frozen run snapshots."""
import tempfile
import threading
import time
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
    def start_preview(self):
        if self.state != self.IDLE:
            raise RuntimeError("Camera busy")
        self.state = self.PREVIEW
    def stop_preview(self):
        if self.state == self.PREVIEW:
            self.state = self.IDLE
    def recording_metrics(self):
        return {"actual_fps": 30., "frame_count": 100}
    def capture_analysis_frame(self, grayscale=False, raw_yuv=False):
        frame = source_geometry([900, 920], self.full_sensor_crop())
        frame.update({"captured_timestamp_ns": time.time_ns(),
                      "captured_monotonic_ns": time.monotonic_ns(),
                      "sensor_timestamp_ns": time.monotonic_ns()})
        return self.image.copy(), frame


class FakeRun:
    SENSOR_CALIBRATION = "SensorCalibration"
    READY, RUNNING, PAUSED, COMPLETED = "Ready", "Running", "Paused", "Completed"
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
        self.run_started_monotonic = None
        self.current_stage = {"id": "stage_1"}
        self.stage_attempt = 1
    def stop_preview(self):
        if self.preview_camera_id is not None:
            self.cameras[self.preview_camera_id].stop_preview()
            self.preview_camera_id = None
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

    def test_calibrated_sensor_stays_live_in_ready_run_and_pause_and_writes_tsv(self):
        with tempfile.TemporaryDirectory() as root:
            run = FakeRun()
            vision = VisionService(run, root)
            run.vision = vision
            cell = vision.registry.save_cell({"name": "Runtime cell"})
            run.cell_profile = {"physical_cell_id": cell["id"]}
            geom = source_geometry([900,920], [0,0,900,920])
            cal = calibrate(run.cameras[1].image, DEFAULT_LAYOUT, frame_geometry=geom)
            vision.registry.save_association(1, cell["id"], cal)
            vision.registry.save_analysis_roi(1, cell["id"], [2,2,10,10])
            vision.save_virtual_profile({"resolution_px":128, "sampling_interval_s": .2})
            reading = {"valid":True, "froth_surface_cm":4., "pulp_froth_interface_cm":7.,
                       "froth_thickness_cm":3., "froth_surface_row_px":20,
                       "pulp_froth_row_px":50}
            with patch("lib.vision.service.detect_interface", return_value=reading):
                benchmark = vision.benchmark_virtual_sensor(samples=12)
                self.assertTrue(benchmark["passed"])
                run.sensor_calibration["froth_interface"]["status"] = "passed"
                self.assertTrue(vision.ensure_live_preview())
                self.assertEqual(run.cameras[1].state, run.cameras[1].PREVIEW)
                self.assertEqual(run.preview_camera_id, 1)
                vision.start()
                try:
                    deadline=time.monotonic()+3
                    while vision._virtual_sample_count < 2 and time.monotonic() < deadline:
                        time.sleep(.05)
                    self.assertGreaterEqual(vision._virtual_sample_count, 2)
                    self.assertEqual(vision.virtual_sensor_snapshot()["measurement_mode"], "preview")
                    self.assertIsNone(vision._run_virtual)
                    run.state = run.READY
                    self.assertEqual(vision._analysis_context()["config"]["resolution_px"], 128)
                    directory = Path(root)/"run"
                    directory.mkdir()
                    vision.freeze_run_config(directory)
                    run.run_directory = directory
                    run.run_started_monotonic = time.monotonic()
                    run.stop_preview()
                    run.cameras[1].state = run.cameras[1].RECORDING
                    run.state = run.RUNNING
                    deadline=time.monotonic()+3
                    output=directory/"sensors"/"froth_interface.tsv"
                    while (not output.exists() or output.stat().st_size < 150) and time.monotonic() < deadline:
                        time.sleep(.05)
                    self.assertTrue(output.exists(), vision.status())
                    content=output.read_text()
                    self.assertIn("pulp_froth_interface_cm", content)
                    self.assertIn("froth_surface_cm", content)
                    before=len(content.splitlines())
                    run.state=run.PAUSED
                    run.cameras[1].state=run.cameras[1].IDLE
                    self.assertTrue(vision.ensure_live_preview())
                    self.assertEqual(run.cameras[1].state, run.cameras[1].PREVIEW)
                    deadline=time.monotonic()+3
                    while len(output.read_text().splitlines()) <= before and time.monotonic() < deadline:
                        time.sleep(.05)
                    self.assertGreater(len(output.read_text().splitlines()),before)
                    self.assertEqual(vision.virtual_sensor_snapshot()["measurement_mode"],"experiment")
                finally:
                    vision.stop()



if __name__ == "__main__":
    unittest.main()
