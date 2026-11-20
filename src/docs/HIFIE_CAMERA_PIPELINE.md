# HIFIE camera pipeline

## One camera-owned lores stream

DigiFlot's Picamera2 driver (`src/lib/camera.py`) owns the acquisition
geometry. The camera is configured **before** it enters Preview or Recording,
but configuration by itself does **not** start the sensor or camera.

- `preview.size` remains the ordinary video-preview request.
- `preview.lores_width` optionally sets the shared YUV420 analysis width
  (1280 px by default; clamped to the actual native sensor width and at least
  the ordinary preview width). Its height follows native sensor aspect ratio.
- Picamera2 Preview has one `lores` stream, which supports the JPEG preview,
  Detection ROI plane, diagnostic frames and HIFIE inspection.
- During Recording, only a frozen/approved HIFIE run enables the optional
  `lores` alongside the existing main encoder. The width remains camera-owned;
  recording height is adjusted to the recording crop's aspect ratio.
- Changing Detection ROI, interface method, resolution or sampling interval
  changes processing and/or ROI remapping but **never** resizes the camera
  stream or restarts Picamera2.
- All `capture_analysis_frame()` operations use the camera's existing lock;
  no second camera worker, parallel stream, frame queue, or transcoding is
  introduced by this design. The VisionService's existing periodic worker is
  retained for explicitly requested diagnostics or approved sensor operation.

The detector's requested `resolution_px` is a **processing target**. Map
compilation clamps the remapped ROI to available lores pixels. An extremely
narrow ROI might need a larger `preview.lores_width`; that is a *camera*
setting, not an automatic sensor-side reconfiguration. Test bandwidth/CPU
before increasing it on Raspberry Pi 5.

## Calibration lifecycle

1. Selecting the camera/cell only prepares the camera-owned configuration.
   The operational HIFIE recording stream remains disabled.
2. Opening the HIFIE modal explicitly starts camera preview on demand.
3. The full-plane snapshot and live diagnostics use the **same lores stream**.
   The plane snapshot uses a short per-camera locked capture, then rectifies
   outside the run controller lock. Concurrent plane requests are serialized.
4. The existing worker computes diagnostic measurements only while an active
   calibration subscriber requests them, or when an approved HIFIE requires
   live readings. It never causes a Picamera2 resolution change.
5. A calibration benchmark is different: it temporarily stops Preview and
   enters Recording. Only this explicit transition changes Picamera2 mode.
6. Starting an experiment freezes the approved sensor configuration and
   enables recording lores; resetting the run disables it again. Global passing
   profiles remain stored for reuse by a later experiment.
7. The modal cancels the browser request on close, and a 25-second timeout
   releases its client-side loading state. Server-side capture/rectification
   is not presumed canceled when HTTP is aborted; pending requests are
   serialized and their late results are ignored.


## Interactive calibration and temporal stabilization

The HIFIE modal exposes method-dependent quick sliders before the Detection
ROI editor. Dragging a slider sends `POST /api/vision/virtual-sensors/froth-interface/tune-preview`
after a short debounce. The endpoint reruns the detector on the latest
**cached, already rectified ROI**. It does not start Picamera2, capture another
frame, change the camera-owned lores resolution, save any profile, or change
the approved run configuration. Only the owning calibration tab can use it.
The cache is bounded to one ROI frame and is accepted only while live
diagnostics are active and its camera, cell, calibration and ROI match.

Changing `resolution_px` in the slider previews the corresponding kernel
scales on cached pixels. The full ROI geometry remap happens after **Save**;
the preview explicitly reports this approximation. Changing the physical
Detection ROI requires saving and waiting for a matching cached diagnostic
frame before another parameter preview.

The optional causal temporal stage in
`src/lib/virtual_sensors/temporal.py` supports:

- `off` (default; preserves prior measurements exactly)
- `ema` (exponential smoothing of valid upper and lower rows)
- `median` (short rolling median of valid rows)
- `vote_prior` (Gaussian prior added to the striped/hybrid row vote curves,
  or an EMA fallback for nonvoting detectors).

`temporal_strength`, `temporal_radius_px`, and `temporal_window` control
the low-cost filter. The state contains only recent valid row pairs, is
reset when detector parameters/geometry change, and is separate for the
calibration benchmark and live detection. Diagnostics draw the preceding
rows as **dotted lines** over both Rectified ROI and Entropy map; measured
rows remain solid.

Operators can click the froth surface and/or pulp interface in either
diagnostic image to mark reference rows. The guided fit endpoint
`POST /api/vision/virtual-sensors/froth-interface/tune-fit` runs a bounded,
single-frame, conservative neighborhood search around the existing filter
parameters. Thresholds are excluded by default and added only when the
operator explicitly chooses **Include thresholds**. A proposal updates only
the UI draft: **Save** and an accepted benchmark or previously verified exact
configuration remain separate requirements. No fitting request writes
to the sensor profile or starts an experiment.

A single-frame fit is not evidence of temporal robustness. Validate
stability against a sequence of independent frames and rerun the
performance benchmark after changing the algorithm or acquisition rate.

## Colors

Both the sensor plot and the live horizontal HIFIE markers read the same CSS
variables: `--plot-froth-upper` (froth surface) and `--plot-pulp` (pulp
interface). The backend benchmark preview uses equivalent BGR values.

## Regression checks

`tests/test_vision_camera_lores.py` tests hardware-free camera geometry,
recording stream activation and acquisition flags. The existing vision
benchmark and modal/ROI tests cover compatibility and request serialization.
Validation with the real Pi camera remains necessary to verify pixel formats,
driver timing and two-camera throughput.
