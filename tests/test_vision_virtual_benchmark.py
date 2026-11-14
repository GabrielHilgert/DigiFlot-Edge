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
        self.preview_owner_id = None
        self.preview_owner_until = 0.
        self.sensor_calibration = {"froth_interface":{"status":"pending"}}
        self.lock = threading.RLock()
        self.execution_locked = False
        self.recording = False
        self.run_directory = None
        self.run_started_monotonic = None
        self.current_stage = {"id": "stage_1"}
        self.stage_attempt = 1
    def start_preview(self, camera_id, owner_id=None):
        camera = self.cameras[int(camera_id)]
        if camera.state == camera.IDLE:
            camera.start_preview()
        self.preview_camera_id = camera.id
        self.preview_owner_id = owner_id
        self.preview_owner_until = time.monotonic() + 35.
        return {"camera_id": camera.id}
    def stop_preview(self):
        if self.preview_camera_id is not None:
            self.cameras[self.preview_camera_id].stop_preview()
            self.preview_camera_id = None
            self.preview_owner_id = None
            self.preview_owner_until = 0.
    def get_camera(self, camera_id):
        return self.cameras[int(camera_id)]
    @property
    def status(self):
        return {"state": self.state, "sensor_calibration": self.sensor_calibration}
    def camera_summaries(self):
        return [{"id":1,"name":"Side"}]
    def _touch_unlocked(self, *args, **kwargs):
        pass
    def _mark_calibration_changed_unlocked(self, *args, **kwargs):
        pass


class VirtualBenchmarkTests(unittest.TestCase):
    def test_detection_roi_is_independent_of_cells_roi_and_used_by_maps(self):
        with tempfile.TemporaryDirectory() as root:
            run=FakeRun()
            vision=VisionService(run,root)
            cell=vision.registry.save_cell({"name":"ROI selection test"})
            run.cell_profile={"physical_cell_id":cell["id"]}
            geom=source_geometry([900,920],[0,0,900,920])
            calibration=calibrate(run.cameras[1].image,DEFAULT_LAYOUT,frame_geometry=geom)
            vision.registry.save_association(1,cell["id"],calibration)
            vision.registry.save_analysis_roi(1,cell["id"],[2,2,5,5])
            wanted=[5.,4.,12.,12.]
            profile=vision.save_virtual_profile({"method":"dual_entropy_hybrid",
                                                 "detection_roi_cm":wanted, "resolution_px":112})
            assoc=vision.registry.association(1,cell["id"])
            self.assertEqual(assoc["analysis_roi_cm"],[2,2,5,5])
            self.assertEqual(profile["config"]["detection_roi_cm"],wanted)
            maps=vision._compiled_roi(run.cameras[1],cell["id"],assoc,geom,profile["config"])
            self.assertEqual(maps["roi_cm"],wanted)
            self.assertGreater(maps["coverage"],.5)
            size=vision._desired_lores_size(run.cameras[1],assoc,profile["config"])
            self.assertGreater(size[0],0)
            self.assertGreater(size[1],0)

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
            vision.save_virtual_profile({"resolution_px":128, "sampling_interval_s": 1., "vertical_reference_confirmed": True})
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
            passing = vision.virtual_profile()["successful_presets"]
            self.assertEqual(len(passing), 1)
            self.assertEqual(passing[0]["config"]["resolution_px"], 128)
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
            # Editing a draft cannot erase the previous passing detector settings.
            self.assertEqual(vision.virtual_profile()["successful_presets"][0]["config"]["resolution_px"], 128)
            self.assertEqual(run.sensor_calibration["froth_interface"]["status"],"pending")



    def test_exact_passed_conditions_are_reusable_after_restart_without_benchmark(self):
        # Compile only the controller method: CI does not have Raspberry Pi Picamera2.
        import ast
        from copy import deepcopy
        source = Path(__file__).resolve().parents[1] / "src/lib/digiflot.py"
        tree = ast.parse(source.read_text(encoding="utf-8"))
        method = next(node for node in ast.walk(tree)
                      if isinstance(node, ast.FunctionDef) and node.name == "confirm_sensor_calibration")
        namespace = {"deepcopy": deepcopy, "_utc_now": lambda: "test-time"}
        exec(compile(ast.Module(body=[method], type_ignores=[]), str(source), "exec"), namespace)
        with tempfile.TemporaryDirectory() as root:
            run = FakeRun()
            vision = VisionService(run, root)
            run.vision = vision
            cell = vision.registry.save_cell({"name": "Passing benchmark reuse"})
            run.cell_profile = {"physical_cell_id": cell["id"]}
            geom = source_geometry([900,920], [0,0,900,920])
            cal = calibrate(run.cameras[1].image, DEFAULT_LAYOUT, frame_geometry=geom)
            vision.registry.save_association(1, cell["id"], cal)
            vision.registry.save_analysis_roi(1, cell["id"], [2,2,10,10])
            config = vision.save_virtual_profile({
                "resolution_px":128, "sampling_interval_s":.2,
                "detection_roi_cm":[2.,2.,10.,10.], "vertical_reference_confirmed":True})["config"]
            reading = {"valid":True, "froth_surface_cm":4., "pulp_froth_interface_cm":7.,
                       "froth_thickness_cm":3., "froth_surface_row_px":20, "pulp_froth_row_px":50}
            with patch("lib.vision.service.detect_interface", return_value=reading):
                successful = vision.benchmark_virtual_sensor(samples=12)
            self.assertTrue(successful["passed"], successful)
            self.assertFalse(successful.get("reused", False))
            self.assertFalse(vision.virtual_test_result().get("reused", False))

            # Simulate the exact restart behavior: only the registry persists.
            restarted = FakeRun()
            restarted.cell_profile = {"physical_cell_id":cell["id"]}
            new_vision = VisionService(restarted, root)
            restarted.vision = new_vision
            self.assertTrue(new_vision.virtual_test_passed())
            evidence = new_vision.virtual_test_result()
            self.assertTrue(evidence["reused"])
            self.assertTrue(evidence["current"])
            self.assertEqual(evidence["samples"], successful["samples"])
            self.assertEqual(evidence["source"], "saved")
            self.assertEqual(len(new_vision.virtual_profile()["successful_presets"]), 1)
            self.assertTrue(new_vision.virtual_profile()["successful_presets"][0]["reusable"])
            self.assertFalse(restarted.cameras[1].started, "Reusing evidence must not start a benchmark")

            # The normal controller approval path must accept the same evidence.
            restarted.sensor_calibration["froth_interface"]["mode"] = "virtual_interface"
            status = namespace["confirm_sensor_calibration"](restarted, "froth_interface")
            self.assertEqual(restarted.sensor_calibration["froth_interface"]["status"], "passed")
            self.assertTrue(restarted.sensor_calibration["froth_interface"]["benchmark"]["reused"])
            self.assertEqual(restarted.cameras[1].state, restarted.cameras[1].PREVIEW)
            self.assertTrue(status)

            new_vision.clear_virtual_test()
            restarted.cameras[1].stop_preview()
            restarted.preview_camera_id = None
            restarted.sensor_calibration["froth_interface"]["status"] = "pending"
            # Camera exposure, frame rate and software revisions are NOT the
            # detector settings: they must not make a new experiment require a test.
            restarted.cameras[1].exposure_time_us += 100
            self.assertTrue(new_vision.virtual_test_passed())
            restarted.cameras[1].exposure_time_us -= 100
            restarted.cameras[1].frame_rate += 1
            self.assertTrue(new_vision.virtual_test_passed())
            restarted.cameras[1].frame_rate -= 1
            with patch("lib.vision.service._virtual_implementation_fingerprint", return_value="new-algorithm"):
                self.assertTrue(new_vision.virtual_test_passed())
            # An ArUco recalibration that leaves sensor ROI/crop unchanged is reusable.
            recalibrated = calibrate(restarted.cameras[1].image, DEFAULT_LAYOUT,
                                     frame_geometry=source_geometry([900,920], [0,0,900,920]))
            new_vision.registry.save_association(1, cell["id"], recalibrated)
            self.assertTrue(new_vision.virtual_test_passed(), "New ArUco ID alone must not expire a passing sensor")
            new_vision.registry.save_analysis_roi(1, cell["id"], [2,2,10,10])
            self.assertTrue(new_vision.virtual_test_passed(), "An unchanged ROI revision must not expire validation")
            restarted.cameras[1].crop_region = (0, 2, 900, 918)
            self.assertFalse(new_vision.virtual_test_passed(), "Camera crop changes require a new test")
            restarted.cameras[1].crop_region = None
            self.assertTrue(new_vision.virtual_test_passed())

            newer = {**config, "entropy_radius":22}
            new_vision.save_virtual_profile(newer)
            self.assertFalse(new_vision.virtual_test_passed(), "Detector tuning change must require a new test")
            new_vision.save_virtual_profile(config)
            self.assertTrue(new_vision.virtual_test_passed(), "Restoring identical settings should reuse the passing test")
            changed_rate = {**config, "sampling_interval_s":.4}
            new_vision.save_virtual_profile(changed_rate)
            self.assertFalse(new_vision.virtual_test_passed(), "Sampling-rate change must require a new test")
            new_vision.save_virtual_profile(config)
            self.assertTrue(new_vision.virtual_test_passed())

    def test_parallel_roi_requests_share_one_camera_plane_queue(self):
        from concurrent.futures import ThreadPoolExecutor
        with tempfile.TemporaryDirectory() as root:
            run = FakeRun()
            vision = VisionService(run, root)
            cell = vision.registry.save_cell({"name": "ROI request serialization"})
            run.cell_profile = {"physical_cell_id": cell["id"]}
            geom = source_geometry([900,920], [0,0,900,920])
            cal = calibrate(run.cameras[1].image, DEFAULT_LAYOUT, frame_geometry=geom)
            vision.registry.save_association(1, cell["id"], cal)
            active, peak, calls = 0, 0, 0
            guard = threading.Lock()

            def slow_rectification(*args):
                nonlocal active, peak, calls
                with guard:
                    active += 1
                    peak = max(peak, active)
                    calls += 1
                time.sleep(0.04)
                with guard:
                    active -= 1
                return {"jpeg_base64": "fake", "size": [100, 100], "plane": {}}

            with patch.object(vision, "_rectify_captured", side_effect=slow_rectification):
                with ThreadPoolExecutor(max_workers=2) as executor:
                    futures = [executor.submit(vision.virtual_detection_roi_preview, "tab-a") for _ in range(2)]
                    frames = [future.result(timeout=10) for future in futures]
            self.assertEqual(len(frames), 2)
            self.assertEqual(calls, 2)
            self.assertEqual(peak, 1, "Parallel ROI requests must never rectify simultaneously")
            self.assertEqual(run.preview_owner_id, "tab-a")

    def test_diagnostic_lease_is_owned_and_full_plane_remap_releases_run_lock(self):
        with tempfile.TemporaryDirectory() as root:
            run = FakeRun()
            vision = VisionService(run, root)
            cell = vision.registry.save_cell({"name": "Diagnostic safety"})
            run.cell_profile = {"physical_cell_id": cell["id"]}
            geom = source_geometry([900,920], [0,0,900,920])
            cal = calibrate(run.cameras[1].image, DEFAULT_LAYOUT, frame_geometry=geom)
            vision.registry.save_association(1, cell["id"], cal)
            vision.registry.save_analysis_roi(1, cell["id"], [2,2,10,10])

            self.assertTrue(vision.diagnostic_preview(True, owner_id="tab-a")["enabled"])
            self.assertEqual(run.preview_owner_id, "tab-a")
            with self.assertRaises(RuntimeError):
                vision.diagnostic_preview(True, owner_id="tab-b")
            self.assertFalse(vision.diagnostic_preview(False, owner_id="tab-b")["enabled"])
            self.assertEqual(vision._diagnostic_owner_id, "tab-a")
            self.assertFalse(vision.diagnostic_preview(False, owner_id="tab-a")["enabled"])
            self.assertIsNone(vision._diagnostic_owner_id)

            def verify_no_lock(image, frame, profile, association):
                self.assertFalse(run.lock._is_owned(), "Full-plane remap must not hold DigiFlot.lock")
                return {"jpeg_base64": "", "size": [10,10], "plane": {}}
            with patch.object(vision, "_rectify_captured", side_effect=verify_no_lock):
                preview = vision.virtual_detection_roi_preview(owner_id="tab-a")
            self.assertEqual(preview["size"], [10,10])
            self.assertEqual(run.preview_owner_id, "tab-a")

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
            vision.save_virtual_profile({"resolution_px":128, "sampling_interval_s": .2, "vertical_reference_confirmed": True})
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
