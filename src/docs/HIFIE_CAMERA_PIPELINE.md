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
  introduced by this design. The operational HIFIE worker is started only
  after calibration approval or restoration of a frozen run configuration.

The detector's requested `resolution_px` is a **processing target**. Map
compilation clamps the remapped ROI to available lores pixels. An extremely
narrow ROI might need a larger `preview.lores_width`; that is a *camera*
setting, not an automatic sensor-side reconfiguration. Test bandwidth/CPU
before increasing it on Raspberry Pi 5.

## Calibration lifecycle

1. Selecting the camera/cell only prepares the camera-owned configuration.
   The operational HIFIE recording stream remains disabled.
2. Opening HIFIE calibration displays the full editor immediately. A single
   reference capture starts camera preview on demand. Failed captures are
   recoverable with **Capture / Retry camera**, without reloading the browser.
3. The full-plane snapshot and live diagnostics use the **same camera-owned
   lores stream**, but never create a sensor measurement worker before approval.
   The plane snapshot uses a short locked camera acquisition, then rectifies
   outside the run controller lock. Multiple plane requests are serialized.
4. Live diagnostics are independent on-demand camera requests at a low rate:
   each request captures one frame and processes the detector in preview-only
   mode. An in-progress reference capture returns a waiting state rather than
   blocking the UI. It does not update operational measurements.
   The periodic HIFIE worker starts only after Confirm; reopen/skip, abort,
   completion and reset stop that worker.
5. A calibration benchmark is different: it temporarily stops Preview and
   enters Recording. Only this explicit transition changes Picamera2 mode.
6. Starting an experiment freezes the approved sensor configuration and
   enables recording lores; resetting the run disables it again. Global passing
   profiles remain stored for reuse by a later experiment.
7. The modal cancels the browser request on close, and an 18-second timeout
   releases its client-side loading state. Server-side capture/rectification
   is not presumed canceled when HTTP is aborted. Cleanup is serialized with
   the plane capture, releases only its own preview lease, and leaves an
   approved operational stream running after Confirm.


## Interactive calibration and temporal stabilization

The HIFIE modal has Camera & Geometry, Detector & Diagnostics, and Validation
steps. The reference/ROI view comes first and collapses after a successful
capture; advanced method controls remain available but do not block initial
camera access. Opening the calibration captures one camera frame for the full
rectified plane **and** a frozen detector ROI. Dragging sliders or selecting
**Fit filters** recomputes exclusively from that frozen reference image. The
endpoints do not start Picamera2, capture another frame, require live diagnostics,
change the camera-owned lores stream, save a profile, or alter the approved run.
Only the tab that captured the frozen image may use it. The reference remains
stable until **New reference** captures another one or the modal closes.
**Reference image** returns from optional live diagnostics to the same frozen
image. A concurrent slider preview finishes before the Fit begins; operations
always show a status rather than failing silently.

Changing `resolution_px` in the slider previews the corresponding kernel
scales on cached pixels. The full ROI geometry remap happens after **Save**;
the preview explicitly reports this approximation. Changing the physical
Detection ROI requires saving and explicitly capturing **New reference**
to remap that ROI from a new single camera image; no live diagnostic session
is needed.

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
