"""Camera owns one stable lores configuration; sensor ROI cannot reconfigure it.

Methods are extracted from the real camera driver to test on CI without Picamera2.
"""
import ast
import unittest
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]


def read_method(path, class_name, method_name):
    tree = ast.parse((ROOT / path).read_text(encoding="utf-8"))
    parent = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == class_name)
    method = next(node for node in parent.body if isinstance(node, ast.FunctionDef) and node.name == method_name)
    namespace = {}
    exec(compile(ast.Module(body=[method], type_ignores=[]), str(ROOT / path), "exec"), namespace)
    return namespace[method_name]


class FakePi:
    def create_video_configuration(self, **kwargs):
        return kwargs


class CameraLoresTests(unittest.TestCase):
    def camera(self):
        return SimpleNamespace(
            preview_size=(640, 480), analysis_target_size=(1280, 960),
            frame_size=(2028, 1520), preview_frame_rate=10, frame_rate=30,
            crop_region=None, format="RGB888", analysis_enabled=False,
            picam2=FakePi(), select_sensor_mode=lambda **kwargs:{"size":(2028,1520),"bit_depth":10},
            _sensor_config_from_mode=lambda mode:{"output_size":tuple(mode["size"]),"bit_depth":mode["bit_depth"]},
        )

    def test_preview_lores_is_stable_and_camera_owned(self):
        camera = self.camera()
        preview = read_method("src/lib/camera.py", "Camera", "create_preview_configuration")
        cfg = preview(camera)
        self.assertEqual(cfg["lores"]["size"], (1280,960))
        self.assertEqual(cfg["main"]["size"], (1280,960))
        self.assertEqual(cfg["encode"], "lores")
        self.assertEqual(camera.analysis_target_size, (1280,960))

        # The ROI method no longer computes any crop-dependent lores sizes.
        desired = read_method("src/lib/vision/service.py", "VisionService", "_desired_lores_size")
        for roi in ([1,1,3,3], [1,1,50,50], None):
            self.assertEqual(desired(None, camera, {"analysis_roi_cm":roi}, {"resolution_px":64}), (1280,960))
        self.assertEqual(camera.analysis_target_size, (1280,960))

    def test_recording_lores_is_added_only_after_sensor_activation(self):
        camera = self.camera()
        size = read_method("src/lib/camera.py", "Camera", "recording_lores_size")
        record = read_method("src/lib/camera.py", "Camera", "create_recording_configuration")
        camera.recording_lores_size = lambda:size(camera)
        self.assertIsNone(record(camera)["lores"], "Uncalibrated HIFIE must not add a recording lores stream")
        camera.analysis_enabled = True
        self.assertEqual(record(camera)["lores"]["size"], (1280,960))
        camera.frame_size = (800,1200)
        self.assertEqual(record(camera)["lores"]["size"], (800,1200))
        self.assertEqual(camera.analysis_target_size, (1280,960),
                         "Recording crop must not change preview lores dimensions")

    def test_stored_sensor_preferences_do_not_arm_recording_before_freeze(self):
        sync = read_method("src/lib/vision/service.py", "VisionService", "_sync_camera_flags")
        camera = self.camera()
        camera.id = 0
        source = SimpleNamespace(
            registry=SimpleNamespace(settings=lambda:{"enabled":True,"camera_id":0}),
            digiflot=SimpleNamespace(cameras={0:camera}), _run_virtual=None)
        sync(source)
        self.assertFalse(camera.analysis_enabled)
        source._run_virtual = {"camera_id":0,"config":{}}
        sync(source)
        self.assertTrue(camera.analysis_enabled)
        source._run_virtual = None
        sync(source)
        self.assertFalse(camera.analysis_enabled)


if __name__ == "__main__":
    unittest.main()
