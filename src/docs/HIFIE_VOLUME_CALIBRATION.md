# HIFIE level-to-volume calibration — implementation design

## Scope and separation
- **HIFIE** detects the froth surface and pulp–froth interface in calibrated ArUco coordinates.
- **Cells** owns physical references, cell geometry and volume calibration (V(h)).
- **Data acquisition** stores the raw interface channel, frozen sensor reference, absolute ArUco Y (when known), selected output reference, geometry/model revision and calculated quantity. It must remain possible to recalculate stored heights after calibrating a cell.
- Idle HIFIE calibration is permitted only for an explicitly selected camera–cell association and must never mutate experiment state. Live diagnostics do not activate continuous production measurements.

## Physical coordinate and quantity contract
The ArUco image-plane Y coordinate increases downwards. Let the physical cell-bottom coordinate be `y_bottom_cm` and an interface coordinate `y_interface_cm`. Then

```text
h_cm = y_bottom_cm - y_interface_cm
V(0) = 0
A_effective(h) = dV/dh
V(h) = integral[0,h] A_effective(z) dz
```

A missing/uncalibrated bottom means **height relative to the selected existing reference only**, never an inferred bottom volume. Negative or above-rim heights are invalid for volume conversion rather than silently made positive. The physical unit is cm for height, cm² for area and L for volume (1000 cm³/L).

The estimated volume below **pulp–froth interface** is the bulk slurry-region volume; it is not automatically water volume in a slurry. Volume below **froth surface** includes froth/gas and cannot be identified as liquid volume. Net water/solid/gas volumes require independent phase fraction information. Label derived observations accordingly.

## Sources in priority order
1. An **approved experimental volume calibration** attached to the cell.
2. A constant-area geometric estimate: cylindrical cross-section `A=πD²/4`, rectangular `A=width×depth`, dimensions converted mm→cm.
3. No volume estimate. Preserve heights, timestamps, camera-cell association, channel and reference for later conversion.

The current implementation supports (2) and (3). Experimental calibration (1) is the next module.

## Proposed cell calibration record
Store as `local_storage/vision/volume_curves/<cell_id>.json` so updates do not increment the ArUco/cell-geometry revision or invalidate an otherwise matching HIFIE detector benchmark.

```json
{
  "schema_version": 1,
  "cell_id": "cell_a",
  "revision": 1,
  "bottom_reference": {"id": "cell_bottom", "y_cm": 20.0, "reference_revision": 5},
  "model": "piecewise_linear",
  "points": [
    {"height_cm": 0.0, "volume_l": 0.0, "source": "fixed_origin"},
    {"height_cm": 6.0, "volume_l": 0.42, "source": "known_fill"},
    {"height_cm": 13.0, "volume_l": 1.18, "source": "known_fill"}
  ],
  "updated_at": "ISO8601",
  "notes": ""
}
```

The immutable anchor `(h,V)=(0,0)` must be inserted automatically. Operators may enter a measured height manually or acquire an HIFIE height while adding a known volume; capture the measurement provenance and uncertainty if known.

## Fitting and extrapolation
- Validate finite heights and nonnegative volumes, strictly increasing heights, and monotone nondecreasing volume; do not silently sort/rewrite physically conflicting measurements.
- One positive-volume point + origin: constant effective area `A_eff=1000×V1/h1`.
- Two or more positive-volume points: **piecewise-linear volume interpolation**, hence a piecewise-constant effective area `A_eff,i=1000×(V_i+1-V_i)/(h_i+1-h_i)`. This maps varying cross-sectional area without assuming a global constant.
- Below the first nonzero point, interpolate to the `(0,0)` anchor.
- Above the highest measured point, linearly extrapolate with the slope of the final interval, explicitly mark `extrapolated=true` and constrain evaluation to physically defined cell height.
- If no measured curve exists, use the geometric constant-area fallback. Do not infer area from the nominal *working volume* without a corresponding known fill height.
- If three or more independent points justify smoothing, optionally evaluate shape-preserving monotone PCHIP; keep piecewise-linear as the default because it cannot overshoot between monotone calibration points.
- Editing the cell bottom or reference definition invalidates the curve's physical registration until explicitly revalidated; keep the original points and readings for audit and reprojection.

## Proposed Cells UI
Add a **Volume vs height** card next to physical named references:
1. Show bottom reference and geometry source/status; if bottom unknown, guide the operator to define it first.
2. Chart `V(h)` with origin, calibrated points, geometric comparison, interpolated curve, extrapolated region and effective-area slopes.
3. Add a calibration row from **known volume (L)** + **height (cm)**, optionally populated from current HIFIE after the camera-cell association is confirmed. Permit edit/remove and explicit Confirm.
4. Display calibration revision, range, units, outliers, and whether the model is geometric, measured, or unavailable.

Future API (separate from detector configuration): `GET/PUT /api/vision/cells/{cell_id}/volume-curve`, validation and optimistic revision checking on PUT. An estimate response should include `volume_l`, `height_cm`, `source`, `curve_revision`, `extrapolated`, and `validity_reason`. Saved observations retain the chosen curve revision and raw height so subsequent recalculation is possible.

## Hardware / workflow tests
- HIFIE channel reference conversion for up/down datum and negative readings.
- Null areas and missing bottom must never produce a volume.
- Rectangular/cylindrical geometry in mm, cm and liters.
- One-point and multi-point curves, interpolation, bounded extrapolation, conflicting/duplicate data, and changed bottom references.
- Idle standalone calibration must not start a run, continuous operational worker or sensor recording.
- Frozen-frame preview must be independent from Live mode; leaving the modal must release the preview even after failed diagnostics stop.

## Implemented in Cells (November 25, 2026)

- The three mandatory named physical references are `outlet_level`, `cell_top` and `cell_bottom`. Their coordinates can be unset; their identities cannot be deleted or repurposed. The automatic ArUco reference also remains fixed. Older cells receive missing references without removing saved custom points.
- `cell.geometry` stores nominal dimensions. `dimension_measurements` stores named point pairs for width, depth and collection height; cell height comes from the fixed top/bottom pair. The computed `resolved_dimensions` prefers measured distances, then derived positions, then nominal parameters. The resolved geometric cross-section is not an experimentally calibrated effective area.
- Experimental V(h) curves are stored independently at `vision/volume_calibrations/<cell_id>.json`. A fill measurement can use any calibrated named reference; the system translates its height to the known Cell bottom, inserts the fixed origin `(0 cm, 0 L)` and fits a monotonic piecewise-linear curve through the known fills.
- Above the final known fill, V(h) is extrapolated linearly using the last measured slope. Each segment's slope estimates the local effective cross-sectional area, in cm². The result carries `extrapolated` and `volume_calibration_revision` provenance.
- Changing named physical references invalidates the existing V(h) curve without erasing its original fill points. Reconfirming/re-saving the curve uses the revised positions. Editing nominal dimensions does not alter a measured calibration.
- HIFIE volume capture now prioritizes a valid experimental V(h) curve; its fallback is resolved cylindrical/rectangular geometry, and it otherwise records heights only. The volume under an interface is bulk region volume, **not automatically water volume** in a gas/solids suspension.

The derived area is based on the known fill-volume relation; it should not be mistaken for a spatially uniform area where the piecewise slopes differ.
