"""Hardware-free stress checks for dual camera + virtual Froth Interface benchmarks."""
import ast
import tempfile
import threading
from types import SimpleNamespace
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from lib.performance import PerformanceManager


class FakeCamera:
    def __init__(self, camera_id):
        self.id, self.name = camera_id, f"Camera {camera_id}"
        self.hardware_info = {"Model": "Fake Pi HQ"}
        self.frame_size, self.crop_region = [640, 480], None
        self.format, self.recording_output_type = "RGB888", "mjpeg"
        self.config, self.frame_rate = {"frame_rate": 30.}, 30.
        self.analysis_enabled, self.analysis_target_size = False, None
        self.recording, self.ffmpeg = False, None

    def refresh_from_config(self):
        self.frame_rate = float(self.config["frame_rate"])

    def validate_config(self, config):
        if config["frame_rate"] <= 0:
            raise ValueError("Invalid rate")

    def start_recording(self, _):
        self.recording = True
        self.started = time.monotonic()

    def stop_recording(self):
        self.recording = False

    def recording_metrics(self):
        return {"actual_fps": self.frame_rate, "write_rate_mbps": 1.,
                "last_frame_age_s": 0., "frame_count": 200}


class FakeVision:
    def __init__(self, source):
        self.source = source
        self._benchmarking = False
        self._map_key, self._roi_map = None, None
        self.measured = 0
        self.available = True

    def performance_workload(self):
        if not self.available:
            return None
        return {"camera": self.source, "camera_id": self.source.id, "cell_id": "cell_a",
                "signature": "frozen-signature", "lores_size": [320, 240],
                "config": {"sampling_interval_s": .2, "method": "dual_entropy_hybrid"}}

    def performance_detection(self, workload):
        assert self._benchmarking and workload["camera"].recording
        self.measured += 1
        return {"valid": True, "latency_ms": 5., "sensor_timestamp_ns": self.measured,
                "captured_timestamp_ns": time.time_ns()}


class FakeDigiFlot:
    IDLE = "Idle"

    def __init__(self):
        self.state, self.recording, self.preview_camera_id = self.IDLE, False, None
        self.cameras = {0: FakeCamera(0), 1: FakeCamera(1)}
        self.vision = FakeVision(self.cameras[0])


def system_sample(cpu_free=32., mem_free=45.):
    return {"timestamp": "2026-11-13T10:00:00+00:00", "temperature_c": 49.,
            "load1": 1., "throttled": {"current": False},
            "disk": {"free_gb": 90., "total_gb": 100.},
            "cpu": {"used_pct": 100-cpu_free, "free_pct": cpu_free},
            "memory": {"used_pct": 100-mem_free, "free_pct": mem_free}}


class PerformanceVirtualTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.fake = FakeDigiFlot()
        with patch.object(PerformanceManager, "sample_system", return_value=system_sample()):
            self.manager = PerformanceManager({"performance": {"sample_interval_s": .1}},
                                              Path(self.temp.name))
        self.manager.sample_system = lambda: system_sample()
        self.addCleanup(self.manager.abort_benchmark)

    def test_both_camera_encoders_run_with_virtual_sensor_and_are_restored(self):
        self.manager.start_benchmark(self.fake, rates=[20], duration_s=.65, include_virtual=True)
        self.manager.benchmark_thread.join(timeout=5)
        self.assertEqual(self.manager.state, self.manager.COMPLETED, self.manager.last_error)
        self.assertEqual(len(self.manager.results), 1)
        result = self.manager.results[0]
        self.assertTrue(result["virtual_sensor"]["included"])
        self.assertGreaterEqual(result["virtual_sensor"]["samples"], 2)
        self.assertGreaterEqual(self.fake.vision.measured, 2)
        self.assertEqual(result["virtual_sensor"]["configuration"]["camera_id"], 0)
        self.assertEqual(result["classification"], "PASS")
        self.assertFalse(self.fake.vision._benchmarking)
        self.assertFalse(self.fake.cameras[0].analysis_enabled)
        self.assertIsNone(self.fake.cameras[0].analysis_target_size)
        self.assertTrue(all(not cam.recording and cam.frame_rate == 30.
                            for cam in self.fake.cameras.values()))
        self.assertEqual(self.manager.profile["hardware_signature"]["virtual_sensor"]["signature"],
                         "frozen-signature")

    def test_virtual_sensor_must_be_selected_not_silently_omitted(self):
        self.fake.vision.available = False
        with self.assertRaisesRegex(ValueError, "No saved"):
            self.manager.start_benchmark(self.fake, rates=[20], duration_s=.4, include_virtual=True)
        self.manager.start_benchmark(self.fake, rates=[20], duration_s=.3, include_virtual=False)
        self.manager.benchmark_thread.join(timeout=5)
        self.assertFalse(self.manager.results[0]["virtual_sensor"]["included"])

    def test_low_headroom_is_measured_as_exposure_not_future_failure_probability(self):
        self.manager.sample_system = lambda: system_sample(cpu_free=8., mem_free=40.)
        self.manager.start_benchmark(self.fake, rates=[20], duration_s=.45, include_virtual=True)
        self.manager.benchmark_thread.join(timeout=5)
        result = self.manager.results[0]
        self.assertEqual(result["classification"], "MARGINAL")
        self.assertEqual(result["headroom_risk"]["observed_pct"], 100.)
        self.assertGreater(result["headroom_risk"]["upper_bound_95_pct"], 0)
        self.assertEqual(result["cpu_free_min_pct"], 8.)
        self.assertGreater(result["headroom_risk"]["samples"], 0)

    def test_scrape_notifications_do_not_change_hardware_events(self):
        # Exercise the actual method without importing Pi-only picamera2 modules in CI.
        path = Path(__file__).resolve().parents[1] / "src/lib/digiflot.py"
        module = ast.parse(path.read_text(encoding="utf-8"))
        owner = next(node for node in module.body if isinstance(node, ast.ClassDef)
                     and node.name == "DigiFlot")
        method = next(node for node in owner.body if isinstance(node, ast.FunctionDef)
                      and node.name == "set_scraping_alerts")
        namespace = {}
        exec(compile(ast.fix_missing_locations(ast.Module(body=[method], type_ignores=[])),
                     str(path), "exec"), namespace)
        toggle = namespace["set_scraping_alerts"]
        run = SimpleNamespace()
        run.lock = threading.RLock()
        run.scraping_alerts_enabled = True
        run.config = {"orchestration": {}}
        run.save_config = lambda: None
        events = []
        run._touch_unlocked = lambda name, info=None: events.append((name, info))
        run._status_unlocked = lambda: {"scraping": {"alerts_enabled": run.scraping_alerts_enabled}}
        self.assertFalse(toggle(run, False)["scraping"]["alerts_enabled"])
        self.assertEqual(run.config["orchestration"]["scraping_alerts_enabled"], False)
        self.assertEqual(events[0][0], "SCRAPING_ALERTS_CHANGED")
        self.assertEqual(len(events), 1)
        run.set_scraping_alerts(False)
        self.assertEqual(len(events), 1)
        with self.assertRaises(ValueError):
            run.set_scraping_alerts("false")


if __name__ == "__main__":
    unittest.main()
