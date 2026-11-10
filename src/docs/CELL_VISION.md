# Cell Vision / ArUco (initial implementation)

The Cell Vision feature is **optional and off by default**. It does not replace the existing camera exposure calibration, nor does it modify the primary MJPEG/FFmpeg recorder.

## Concepts and persistence

The Edge keeps persistent files below `local_storage/vision/`, independently of the DigiFlot Server:

- `cameras/<camera_id>.json`: camera-owned intrinsic calibration or distortion preset and the ROI in full-sensor-normalized coordinates, plus a revision.
- `cells/<cell_id>.json`: physical cell, working volume, optional dimensions and local ArUco ruler layout.
- `associations/<camera_id>__<cell_id>/latest.json`: last confirmed calibration for this camera–cell pair.
- `associations/.../history/<calibration_id>.json`: immutable historical versions.
- `associations/<camera_id>__<cell_id>/analysis_roi.json`: independent, revisioned physical analysis ROI in local centimetres. It survives new marker calibrations.
- `settings.json`: selected analysis camera, cell, on/off state and sampling interval.

The default local ruler uses `DICT_4X4_50`, marker IDs `[0,1,2]`, 2 cm marker sides and 14 cm between the ruler anchors. The reference is **local to the markers**; no absolute position of the camera or cell is needed.

## Daily workflow

1. Open **Cells** and select or register the physical cell.
2. Select the analysis camera, normally the lateral one, and save its optics/preset. Raw-camera dragging changes the optional **sensor ROI**, not the physical analysis ROI.
3. Start preview. The last confirmed camera–cell grid appears over the raw image when available.
4. Click **Detect ArUco** and review the candidate. This does not replace the previous calibration. Confirm it to save the marker reference.
5. Click **Rectified plane (full view)**. The markers establish the coordinate system, not the output rectangle: the complete valid camera field is projected onto that plane for configuration only.
6. Drag on the rectified preview to select the **analysis ROI**, then click **Save analysis ROI**. This ROI is stored in centimetres relative to the physical markers and stays visible after refresh.
7. Use **Raw camera + saved grid** to return to the sensor view. The analysis ROI remains independently stored for the same camera–cell pair.

If the camera or cell definition revision changes, the UI flags the saved association for review. The old association remains available; old versions are not overwritten.

## Acquisition

Only the selected camera can be configured for analysis, and the setting is disabled by default. When enabled **before** a recording starts, `camera.py` adds a `YUV420` `lores` stream to the video configuration. The `main` output and its `JpegEncoder`/FFmpeg path are unchanged.

A background worker samples the `lores` stream at the configured interval (initially 1 s) while the selected camera is recording. Frames are **not queued**. It copies only the Y (luminance) plane from YUV420, avoiding the per-frame BGR conversion. If an analysis ROI is saved, its inverse optical/perspective map is compiled once for the active camera crop and reused on subsequent frames. The source is cropped to the mapped bounding box **before** applying `cv2.remap` with fixed-point maps from `cv2.convertMaps`. Output is capped by the lores dimensions and 1 megapixel. No full-plane rectification occurs in the recording loop. If no ROI is selected, the worker retains the initial grayscale ArUco detection behavior. The latest-status summary reports processing time and ROI coverage; errors are isolated from acquisition. The worker does not overwrite confirmed geometry automatically. A `vision_calibration_snapshot.json` containing the calibration and ROI selection is saved alongside the run when a confirmed association exists.

The interface-depth detector, continuous image-derived measurements, ChArUco/checkerboard wizard and second-camera analysis are **not enabled** in this initial implementation.

## Geometry and calibrated fields

A calibration stores the homography, inverse homography, original marker-bounded rectification size, local cm bounds and px/cm, marker corners, reprojection errors, and source frame metadata (size/crop). The camera's optical profile is snapshotted with each confirmed association. **Marker bounds are not processing bounds.** The setup preview derives a larger plane extent by projecting the camera border, then applies the same ROI mapping engine to the displayed plane. This projection is physically exact only for objects on the ArUco reference plane. The analysis ROI is saved independently in that plane's centimetre coordinates; previous calibrations and saved ROI selections remain compatible.

The camera ROI is stored in **full-sensor-normalized** coordinates. The old `roi_rect` from `test_crop_roi.py` refers to the **rectified output**, not the camera sensor; do not silently migrate it as a camera ROI.

The frame transform through sensor coordinates allows a homography computed in one stream resolution/crop to be visualized on another stream. Verify with the real camera whenever its crop, lens or focus changes; intrinsics imported from calibration JSON must include the resolution in which K was obtained.

## Validation

Local hardware-free regression suite:

```sh
PYTHONPATH=src python -m unittest discover -s tests -p 'test_vision_*.py' -v
node --check src/ui/js/cells.js
```

Before deploying enabled analysis in an actual experiment, perform a Pi 5 camera test comparing normal recording against recording with vision enabled. Verify frames/sec, ffmpeg write rate, temperature, CPU and the geometry of the `main`/ `lores` crop. Do not claim Raspberry Pi recording concurrency has been verified by CI.

## Runtime validation checklist

1. Open the full rectified preview and verify that camera borders beyond the markers are visible, without unstable perspective extrapolation.
2. Select a smaller physical ROI, save it, refresh Cells and confirm it is still displayed. Repeat after re-detecting ArUco markers.
3. With Vision disabled, compare baseline recording FPS and throughput. Then enable Vision (1 s sampling) and confirm the main encoder retains its original output resolution and stable frame rate.
4. Verify that `/api/vision/status` reports `roi_processed=true`, `roi_size`, `roi_coverage`, and `processing_ms`. Processing failures must not interrupt the main recorder.
5. If lens/focus/crop changes, recalibrate before interpreting the ROI's coordinates physically. Neither an optical preset nor planar homography can correct out-of-plane foam displacement.
