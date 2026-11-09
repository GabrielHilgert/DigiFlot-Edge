# Cell Vision / ArUco (initial implementation)

The Cell Vision feature is **optional and off by default**. It does not replace the existing camera exposure calibration, nor does it modify the primary MJPEG/FFmpeg recorder.

## Concepts and persistence

The Edge keeps persistent files below `local_storage/vision/`, independently of the DigiFlot Server:

- `cameras/<camera_id>.json`: camera-owned intrinsic calibration or distortion preset and the ROI in full-sensor-normalized coordinates, plus a revision.
- `cells/<cell_id>.json`: physical cell, working volume, optional dimensions and local ArUco ruler layout.
- `associations/<camera_id>__<cell_id>/latest.json`: last confirmed calibration for this camera–cell pair.
- `associations/.../history/<calibration_id>.json`: immutable historical versions.
- `settings.json`: selected analysis camera, cell, on/off state and sampling interval.

The default local ruler uses `DICT_4X4_50`, marker IDs `[0,1,2]`, 2 cm marker sides and 14 cm between the ruler anchors. The reference is **local to the markers**; no absolute position of the camera or cell is needed.

## Daily workflow

1. Open **Cells** and select or register the physical cell.
2. Select the analysis camera, normally the lateral one; save its intrinsics/preset and camera ROI (drag on preview).
3. Start preview. The last **confirmed** camera–cell grid appears over the image when available.
4. Click **Detect ArUco** to compute a candidate using the present marker coordinates. This does **not** replace the last calibration.
5. Inspect the marker IDs, RMS and candidate grid, then select **Confirm new calibration** if appropriate.
6. Use **Test rectified image** to inspect the saved rectification.

If the camera or cell definition revision changes, the UI flags the saved association for review. The old association remains available; old versions are not overwritten.

## Acquisition

Only the selected camera can be configured for analysis, and the setting is disabled by default. When enabled **before** a recording starts, `camera.py` adds a `YUV420` `lores` stream to the video configuration. The `main` output and its `JpegEncoder`/FFmpeg path are unchanged.

A background worker samples the `lores` stream at the configured interval (initially 1 s) while the selected camera is recording. Frames are **not queued**. The worker performs initial ArUco detection and keeps a latest-status summary; it does not overwrite confirmed geometry automatically. Its errors are isolated from acquisition. A `vision_calibration_snapshot.json` is saved alongside the run when a confirmed association is available.

The interface-depth detector, continuous image-derived measurements, ChArUco/checkerboard wizard and second-camera analysis are **not enabled** in this initial implementation.

## Geometry and calibrated fields

A calibration stores the homography, inverse homography, rectified output size, local cm bounds and px/cm, detected marker corners, RMS/max reprojection errors and source frame metadata (size and sensor crop). The camera's optical profile is snapshotted with each confirmed association.

The camera ROI is stored in **full-sensor-normalized** coordinates. The old `roi_rect` from `test_crop_roi.py` refers to the **rectified output**, not the camera sensor; do not silently migrate it as a camera ROI.

The frame transform through sensor coordinates allows a homography computed in one stream resolution/crop to be visualized on another stream. Verify with the real camera whenever its crop, lens or focus changes; intrinsics imported from calibration JSON must include the resolution in which K was obtained.

## Validation

Local hardware-free regression suite:

```sh
PYTHONPATH=src python -m unittest discover -s tests -p 'test_vision_*.py' -v
node --check src/ui/js/cells.js
```

Before deploying enabled analysis in an actual experiment, perform a Pi 5 camera test comparing normal recording against recording with vision enabled. Verify frames/sec, ffmpeg write rate, temperature, CPU and the geometry of the `main`/ `lores` crop. Do not claim Raspberry Pi recording concurrency has been verified by CI.
