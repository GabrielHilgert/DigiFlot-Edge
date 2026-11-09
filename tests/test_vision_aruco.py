"""Hardware-free regression tests for the historical three-marker ArUco geometry."""
import tempfile
import unittest
from pathlib import Path
import cv2
import numpy as np
from lib.vision.aruco import (DEFAULT_LAYOUT, calibrate, detect_markers, frame_transform,
                              grid_overlay, project_rectified, rectification_maps, ruler_points, source_geometry)
from lib.vision.registry import VisionRegistry


def synthetic_ruler():
    """Generate OpenCV markers at the legacy L-ruler physical corner coordinates."""
    image = np.full((920, 900), 255, dtype=np.uint8)
    s, span = 2.0, 14.0
    marker = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
    local = np.array([[0, 0], [0, s], [-s, s], [-s, 0]], dtype=np.float32)
    anchors = [(0,[0,0]), (1,[0,span]), (1,[span,span])]
    physical_to_img = np.array([[0, 35, 140], [-35, 0, 720], [0, 0, 1]], np.float64)
    for mid,(corner_id,xy) in zip([0,1,2], anchors):
        world = np.asarray(xy, np.float32) - local[corner_id] + local
        destination = cv2.perspectiveTransform(world.reshape(-1,1,2), physical_to_img).reshape(-1,2)
        bits = cv2.aruco.generateImageMarker(marker, mid, 200)
        source = np.float32([[0,0],[199,0],[199,199],[0,199]])
        H = cv2.getPerspectiveTransform(source, destination.astype(np.float32))
        warped = cv2.warpPerspective(bits, H, (image.shape[1],image.shape[0]),borderValue=255)
        image = np.minimum(image, warped)
    return image


class VisionArUcoTests(unittest.TestCase):
    def test_original_ruler_calibration_and_reprojection(self):
        image = synthetic_ruler()
        detected = detect_markers(image)
        self.assertEqual(set(detected), {0, 1, 2})
        calibration = calibrate(image, DEFAULT_LAYOUT, frame_geometry=source_geometry([900,920], [0,0,900,920]))
        self.assertLess(calibration['rms_px'], 2)
        self.assertAlmostEqual(calibration['px_per_cm'], 35, delta=2)
        self.assertEqual(calibration['ids_detected'], [0, 1, 2])
        p = np.array(calibration['min_xy_cm'])
        scale = calibration['px_per_cm']
        corners = project_rectified([(0-p[0])*scale,(0-p[1])*scale], calibration)
        self.assertTrue(np.allclose(corners[0], detected[0][0], atol=3))
        annotated = grid_overlay(image, calibration)
        self.assertEqual(annotated.shape, (920,900,3))
        mx, my = rectification_maps(calibration)
        self.assertEqual(mx.shape, tuple(calibration['size'][::-1]))
        self.assertEqual(my.shape, mx.shape)

    def test_crop_reprojection(self):
        source = source_geometry([900, 920], [0,0,900,920])
        target = source_geometry([500,400], [200,100,500,400])
        M = frame_transform(source, target)
        pt = cv2.perspectiveTransform(np.array([[[200.,100.]]],np.float32), M)[0,0]
        self.assertTrue(np.allclose(pt,[0,0]))

    def test_missing_markers_fails_without_silent_fallback(self):
        with self.assertRaisesRegex(ValueError,'Missing required markers'):
            calibrate(np.full((400,600),255,np.uint8))

    def test_registry_history_and_camera_roi(self):
        with tempfile.TemporaryDirectory() as root:
            store = VisionRegistry(root)
            cell = store.save_cell({'name':'A','working_volume_l':2.5})
            self.assertEqual(store.get_cell(cell['id'])['name'],'A')
            profile = store.save_camera_profile(0, {'roi_norm':[.1,.2,.8,.9], 'optics':{'mode':'preset','preset':'leve'}})
            self.assertEqual(profile['revision'],1)
            cal = calibrate(synthetic_ruler(),frame_geometry=source_geometry([900,920]))
            first = store.save_association(0, cell['id'], cal)
            next_cal = store.save_association(0, cell['id'], cal)
            self.assertNotEqual(first['calibration_id'], next_cal['calibration_id'])
            self.assertEqual(store.association(0,cell['id'])['revision'],2)
            self.assertEqual(len(list((Path(root)/'vision'/'associations'/f"0__{cell['id']}"/'history').glob('*.json'))),2)
            with self.assertRaises(ValueError): store.save_camera_profile(0,{'roi_norm':[.9,.1,.2,.7]})
            with self.assertRaises(ValueError): store.get_cell('../nope')

if __name__ == '__main__': unittest.main()
