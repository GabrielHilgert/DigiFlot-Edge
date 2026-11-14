"""End-to-end local camera/cell association tests without Raspberry Pi hardware."""
import tempfile
import unittest
import threading
import numpy as np
from lib.vision.service import VisionService
from test_vision_aruco import synthetic_ruler


class FakeCamera:
    PREVIEW = 'Preview'
    RECORDING = 'Recording'
    def __init__(self):
        self.id=1;self.state=self.PREVIEW;self.analysis_enabled=False
        self.picam2=type('FakePi',(),{'sensor_resolution':(900,920)})()
    def capture_analysis_frame(self, grayscale=False):
        from lib.vision.aruco import source_geometry
        import cv2
        image = synthetic_ruler()
        if not grayscale:
            image = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
        return image, source_geometry([900,920],[0,0,900,920])


class FakeDigiFlot:
    def __init__(self):
        self.cameras={1:FakeCamera()};self.execution_locked=False;self.recording=False;self.run_directory=None
        self.lock=threading.RLock(); self.virtual_camera_id=None; self.cell_profile=None
    def _mark_calibration_changed_unlocked(self, *args): pass
    def get_camera(self, camera_id):
        return self.cameras[int(camera_id)]
    def camera_summaries(self):
        return [{'id':1,'name':'Side','state':self.cameras[1].state}]


class VisionServiceTests(unittest.TestCase):
    def test_detect_preview_confirm_and_reload(self):
        with tempfile.TemporaryDirectory() as root:
            system=FakeDigiFlot(); service=VisionService(system,root)
            cell=service.registry.save_cell({'name':'Cell A','marker_layout':{'marker_ids':[0,1,2]}})
            first=service.snapshot(1)
            self.assertTrue(first['jpeg_base64'])
            candidate=service.detect(1,cell['id'])
            self.assertIsNotNone(candidate['candidate_token'])
            self.assertEqual(candidate['detected_ids'],[0,1,2])
            self.assertIsNone(service.registry.association(1,cell['id']))
            saved=service.confirm(1,cell['id'],candidate['candidate_token'])
            self.assertEqual(saved['revision'],1)
            second=service.snapshot(1,cell['id'])
            self.assertEqual(second['calibration_id'],saved['calibration_id'])
            result=service.rectified_snapshot(1,cell['id'])
            self.assertTrue(result['jpeg_base64'])
            self.assertGreater(result['size'][0],0)
            self.assertGreater(result['size'][0], saved['calibration']['size'][0])
            self.assertIn('plane', result)
            selected = service.save_analysis_roi(1, cell['id'], {'roi_cm':[2, 2, 10, 10]})
            self.assertEqual(selected['revision'], 1)
            assoc = service.registry.association(1, cell['id'])
            self.assertEqual(assoc['analysis_roi_cm'], [2, 2, 10, 10])
            _, frame = system.cameras[1].capture_analysis_frame(grayscale=True)
            compiled = service._compiled_roi(system.cameras[1], cell['id'], assoc, frame)
            self.assertLessEqual(compiled['size'][0] * compiled['size'][1], 1_000_000)
            self.assertIs(compiled, service._compiled_roi(system.cameras[1], cell['id'], assoc, frame))
            service.save_settings({'camera_id':1,'cell_id':cell['id'],'enabled':True,'sampling_interval_s':1})
            # Persisted settings are only preferences. A new run must not
            # arm the HIFIE recording stream until calibration was confirmed
            # and its run configuration was frozen.
            self.assertFalse(system.cameras[1].analysis_enabled)
            system.recording=True
            with self.assertRaises(RuntimeError): service.save_camera_profile(1,{'roi_norm':[0,0,1,1]})

    def test_changed_profile_invalidates_pending_calibration(self):
        with tempfile.TemporaryDirectory() as root:
            service=VisionService(FakeDigiFlot(),root)
            cell=service.registry.save_cell({'name':'A'})
            candidate=service.detect(1,cell['id'])
            service.save_camera_profile(1,{'roi_norm':[.1,.1,.9,.9]})
            with self.assertRaises(ValueError): service.confirm(1,cell['id'],candidate['candidate_token'])

if __name__=='__main__': unittest.main()
