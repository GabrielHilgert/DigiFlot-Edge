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

## Froth-interface calibration diagnostics

The current detector lives in `src/lib/virtual_sensors/interface_detection.py` (numerical algorithms);
`interface.py` validates settings, converts rows to local centimetres, and optionally exposes
intermediate arrays. The word *legacy* does not designate a separate sensor or preview mode.
Existing per-camera/per-cell profiles remain unchanged, including stored
`dual_entropy_hybrid` choices, and the stored experiment snapshot is authoritative.

`Run calibration test` verifies the requested acquisition period with temporary
main+lores recording. Its output includes one temporal series per measured sample
(upper/lower positions, thickness, validity and elapsed time), and a single fully
diagnostic frame. This temporal plot is **test data**, not persisted as experiment
measurements. The last benchmark sample captures the normal detector's already
computed entropy map and internal row profiles; image compression and plotting
are excluded from the timed acceptance criteria.

Opening the virtual calibration editor starts a **short-lived diagnostic lease**
via `POST /api/vision/virtual-sensors/froth-interface/diagnostics` with
`{"enabled":true,"last_revision":0}`; polling renews the lease. `{"enabled":false}`
stops it. Diagnostic images update at most every five seconds, on the same
rectified ROI and from the **same lores frame** as the virtual sensor. An optional
single background encoding thread creates two compact JPEGs (rectified source
and entropy map) plus normalized profiles for browser-side plots, transparent
physical grid, and measured boundary overlays. No separate Picamera2 request,
second detector pass, per-frame disk plot, or extra main recording is required.
The lease expires if the browser stops polling; if calibration is not yet
confirmed, its diagnostic-only preview is then closed.

The hybrid detector uses a striped upper boundary and a global lower
boundary. Its diagnostic row plot shows upper vote and lower score (and entropy
profile); the grayscale mean-derivative method shows row entropy and its
derivative. The selection-criteria and curve-simplification parameters are
retained in the saved configuration, but the present hybrid detector does not
use the heuristic simplification branch. The diagnostic may be turned off
without stopping virtual sensor acquisition, real-time plots or experimental
TSV storage.

## Independent virtual Detection ROI and height datum

**Cells ROI** remains an optional camera-cell processing reference. The Froth Interface
sensor can use a different **Detection ROI**, saved with its detector parameters in
`virtual_sensors/froth_interface/<camera>__<cell>.json`. Open **Calibrate Sensors**,
load the full rectified camera plane, drag to select the sensor's physical region,
and click **Save settings** (or **Run calibration test**, which saves first).
The selection is in the *unchanged* ArUco local coordinate system, and the sensor
compiles cropped remapping maps and negotiates lores geometry directly for this
new region. It does not rewrite the Cells ROI, and the existing Cells ROI is the
fallback when a profile has not selected its own Detection ROI. A geometry association
is still mandatory; an ROI selection may be made before the virtual calibration
benchmark and may extend beyond the markers if covered by the camera image.

`height_reference_offset_cm` is a configurable **output datum offset**, initially
10 cm for new or normalized saved profiles. It is added to the measured
`froth_surface_cm` and `pulp_froth_interface_cm`; pixel rows, ArUco geometry,
inverse maps and `froth_thickness_cm` are unchanged. The offset and Detection ROI
are saved in the run's immutable virtual-sensor config snapshot and changing either
invalidates the mandatory benchmark. Old experiment snapshots without the datum
field are restored with an offset of 0 cm, maintaining historical results. The
Sensors card's primary reading is `froth_thickness_cm`, with the two positions
shown as secondary values and plotted as independent live series.
