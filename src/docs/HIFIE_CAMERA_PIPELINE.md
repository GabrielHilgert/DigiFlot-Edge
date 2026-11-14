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
