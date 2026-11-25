# Flotation cells, physical sensors, cameras and HIFIE

**Sources:** `src/lib/vision/registry.py`, `src/lib/vision/service.py`, `src/lib/cell_inventory.py`, `src/lib/camera.py`, `src/ui/js/cells.js`. Reviewed 2026-11-23.

## Ownership model

```text
Edge device
  |-- Flotation cells (registered dimensions, references and optional photographs)
  |-- Cameras (hardware configuration and video writers)
  |-- Physical sensors (Atlas, scales, Bronkhorst, WAGO, plugins)
  |-- Virtual sensors (HIFIE, dependent on camera and cell calibration context)
  +-- Camera-cell associations and saved benchmark evidence
```

**Cells do not own sensors.** The Server UI may group/annotate channels by selected cell, but the hardware belongs to the Edge. A virtual sensor can be advertised as a device capability while its calibration compatibility is evaluated for a specific camera, cell and detector configuration.

## Registering a flotation cell

1. Open **Cells** on the Edge. Create or select a cell in the first registry card.
2. Enter name, nominal working volume and geometry (prismatic/rectangular, cylindrical or custom as supported by the form).
3. Define physical references and optional ArUco marker layout.
4. Save geometry. Calibrate a camera–cell association and its analysis/detection ROI separately.
5. Optionally select a camera and **Capture photo** to save a cropped WebP thumbnail. The default static monochrome thumbnail appears if no photo exists.
6. Use the information icon to view the dimensional illustration (`Height`, `Width`, `Side`, `h_collection`); it is not a calibration result or an actual photo.

The cell registry is stored in `local_storage/vision/cells/`; photographs are stored independently under `local_storage/vision/cell_thumbnails/`. A photo edit increments its **own** thumbnail revision and does **not** change geometry, reference revisions, ArUco calibration or the Server experiment `spec_hash`.

Cell definition changes are blocked during an active execution by the local API. The operator should prepare and verify cells while the system is idle.

## Geometry, reference and detector contexts

- Camera profile: device-specific calibration, crop and geometry.
- Cell geometry: dimensions and working-volume metadata.
- Camera–cell association: rectification, ArUco detection and analysis ROI.
- Physical reference: bottom, top, custom or named ArUco-based datum.
- HIFIE profile: detector parameters, sampling interval and Detection ROI.
- Successful benchmark: persisted evidence for the **exact** approved combination.

A previously passed HIFIE configuration may be reused when the camera/crop/ROI/rate/algorithm combination still matches. A saved calibration for a different cell is not automatically valid. For detailed ROI/reference semantics, see [Cell Vision](CELL_VISION.md).

## HIFIE | Froth Interface Detection

HIFIE estimates the froth-interface position using image-derived information. It is a **virtual sensor**, not a camera-video recorder. The implementation uses a managed camera `lores` stream, rectification/ROI and a temporal detector. Its operational configuration is frozen for the run.

- Recording full video and computing HIFIE are independent acquisition choices.
- HIFIE can run with video recording disabled, provided the source camera and approved configuration are available.
- When both need one camera, use its shared `lores`; never open two conflicting Picamera2 configurations.
- An operational HIFIE worker may temporarily own a preview. It must release only its own preview on shutdown, not a browser-tab preview or another camera's encoder.
- If a stage deselects HIFIE, the worker stops processing without deleting its approved profile.

**Caution:** Approval is a suitability check, not proof that the measurement remains accurate under every experimental condition. Inspect the diagnostics and physical reference during setup.

See [HIFIE camera pipeline](HIFIE_CAMERA_PIPELINE.md) for tuning, benchmarks and cleanup rules.

## Physical sensor families

| Family | Source | Typical acquisition | Stage channel |
| --- | --- | --- | --- |
| Camera(s) | `camera.py` | Video and optional `lores` | `video/<camera-id>` or `video/all` |
| Atlas Scientific | `atlasScientific.py` | pH and other configured Atlas sensors | `atlas` |
| Scale | `scale.py` | Mass | `sensor/<scale-id>` |
| Bronkhorst | `bronkhorst.py` | Flow and optional setpoint control | `sensor/<id>` |
| WAGO | `wago.py` | Configured electrical/process measurements | `sensor/<id>` |
| Plugin sensor | `plugins.py` | Driver-defined values | `sensor/<id>` |
| HIFIE | `vision/service.py` | Virtual froth-interface estimate | `virtual/froth_interface` |

A stage selection controls **recording**, not sensor power, setpoint control, or safety systems. Physical recording defaults to enabled for all stage types. Segmented writers avoid overwriting data when a channel is re-enabled later in the same run.

## Server inventory

The Edge inventory builder reads cell definitions, cameras and configured sensors without fetching camera frames or sensor readings. The Server stores a read-only inventory and can display cell photos and short sensor labels. A manual **Sync now** request and automatic metadata reconciliation are available.

**Current protocol limitation:** although `build_inventory()` constructs `cameras` and `virtual_calibration`, `ServerSync._reconcile_inventory_v2()` currently builds its published core from only `schema_version`, `cells` and `sensors`. The Server therefore cannot reliably obtain individual camera IDs or HIFIE compatibility from the published inventory until this publishing contract is expanded. The Server stage editor still offers a generic `video/all` control. Do not interpret missing per-camera details as a hardware fault solely from this inventory UI.

See [Server integration](SERVER_INTEGRATION.md) and [known limitations](TROUBLESHOOTING.md#known-implementation-limitations).

## Photo handling

The Edge exposes thumbnail GET/PUT/DELETE. The Server accepts separately uploaded **WebP** bytes (maximum **180 KiB**), scoped to the authenticated device; thumbnails are not transported inline in a recipe or a run snapshot. A missing photo uses the static placeholder. Do not use this thumbnail as a quantitative geometric reference.

## Verification checklist

- Register a prismatic cell, save dimensions and retrieve it after restart.
- Change only its photo; verify geometry/ArUco revisions do not change.
- Calibrate a camera–cell pair and approve an HIFIE benchmark.
- Select a different cell; verify the previous approval is not silently reused.
- Enable HIFIE with main video off; verify `lores` keeps running.
- Start video on Camera 2 while Camera 1 supplies HIFIE; verify Camera 1 is not stopped.
- Deactivate HIFIE; verify its worker-owned preview is released without closing a tab-owned preview.

## Visual Cells workspace — November 2026

The editor keeps existing API and DOM IDs but moves the actual elements into a new workspace: Cell registry first; full-width camera canvas with raw/undistorted/rectified views and zoom/pan; then independent Measurements, Physical references, Camera calibration, Cell geometry and Volume calibration panels. Icons are drawn from the existing offline DigiFlot icon library.

### Ownership and camera models

- The last confirmed ArUco camera–cell association is the default when compatible. Rectified preview does not require marker re-detection.
- Revalidate saved ArUco is explicitly confirmed and accepts only unchanged optics and ArUco ruler geometry. It creates a new history revision with the old homography, preserving earlier files. Operators must only revalidate if the physical ruler did not move.
- Each physical reference belongs to the cell. Camera-specific raw/undistorted observations are saved separately under local_storage/vision/reference_observations/<cell>/<camera>.json. These use normalized pixel coordinates, frame size and optical revision, and do not overwrite existing ArUco centimetre coordinates.
- Relative calibration for a camera without markers uses a saved calibrated source camera and a known physical cell dimension. On the destination camera the operator marks two endpoints spanning that known dimension and two spanning another dimension. Target length is estimated as reference_mm multiplied by target_px/reference_px. The result is only an approximate common-plane scale, not a homography; optical correction is applied where available. Relative records are stored separately under local_storage/vision/relative_calibrations/ and never overwrite ArUco latest.json.
- Metric measured dimensions outrank reference-derived values, which outrank relative camera estimates, which outrank nominal fallbacks. Changing optical or source geometry revisions invalidates relative estimates without deleting saved evidence.
- Single-frame Undistorted uses existing optical parameters in OpenCV. Clicked pairs and reference observations are bound to a specific camera image and optical revision.

### Cell lifecycle safety

- Rename and name-only edits preserve cell ID and the geometric revision.
- Archive is reversible, stored separately under local_storage/vision/cell_lifecycle/, and hides inactive cells without deleting calibration data. Archived entries may be listed explicitly.
- Permanent Delete is restricted to archived, unreferenced draft cells. References, measurements, photos, camera associations, HIFIE evidence and active vision selections block permanent deletion.

### Operational constraints

The visual workspace does not start experiments, recording or continuous HIFIE processing. Existing ArUco/ROI endpoints and files are unchanged. Points captured in Raw/Undistorted mode are camera observations, while points captured in Rectified mode are ArUco-local physical coordinates and require an explicit save.

### Measurement workspace refinements (25 November 2026)

- The camera workspace retains its full-width image, but **Camera calibration** now opens as an accordion in that same card. Its separate nested disclosures are **Optical profile**, **Relative camera calibration**, and **ArUco / planar calibration & ROI**. The four lower cards form a compact two-column layout.
- Each physical dimension has a measurement axis: horizontal (absolute X difference), vertical (absolute Y difference), or direct (Euclidean). Previously saved dimension mappings without an axis keep direct-distance semantics when migrated; no existing result is silently reinterpreted.
- In the Measurements card, Point A and Point B are selected from existing named physical references. Clicking near existing reference markers on the calibrated canvas fills those fields; saving writes only the mapping and chosen axis and creates **no additional physical reference points**. Place new references explicitly through Physical references if none exist.
- Raw camera mode displays a clean image. The legacy **Raw camera + saved grid** command remains available in the ArUco disclosure; physical points appear as discrete markers rather than full-width reference lines.
- Relative calibration now explicitly uses **three image operations**. (1) Select a known length on the **source camera's saved rectified metric plane**; pressing Pick known length changes the active camera to that source. This yields a calibrated length in mm, with horizontal/vertical/direct projection. (2) Switch to the destination camera and mark the same known length there in pixels. (3) Mark the target dimension in pixels on the same destination image. The estimated target dimension is the physical source length multiplied by target pixels / matching known-length pixels. The user can set independent projection modes for the source metric length and the two destination pixel lengths.
- A camera change between physical selection and saving is checked against the captured camera ID, optics revision, and source ArUco calibration ID. Relative estimates remain in their separate records and do not modify the source homography, existing named physical cm coordinates, or HIFIE calibration.
- The ratio is not a full perspective model. It assumes that the two measured distances on the destination image have compatible spatial scale after any available lens correction.

### Visual points, cross-section outlines and relative calibration without visible markers (25 November 2026)

- Pick known length attempts the saved metric source plane. If ArUco is unavailable or the source frame cannot be acquired, it uses an independently known cell dimension (measured or nominal, never an estimate from another relative calibration). The top destination camera needs no rectification; pixel lengths are measured in raw or optically corrected camera images. Results remain explicitly approximate and source provenance is persisted.
- The Select / Add point tools open a point editor when clicking a saved reference or an empty camera location. Only Save creates a reference; Reposition moves an existing point. The Measurements picker reuses saved references and offers naming a point when no marker is nearby. Pixel-only camera observations remain separate from ArUco-local cm.
- Reference presentation is compact: mandatory cell datums at the top, custom points in a collapsed group, and the original full editor in Advanced reference properties.
- Rectangle, Square and Circle are independent shape objects, not physical reference points. Each is drawn by selecting two image corners, then linking a width or depth dimension to the horizontal or vertical image side. Estimated cross-section area and approximate capacity (area times height) are reported independently of nominal cross-section, calibrated effective area and measured V(h).
- Shape records use the vision/geometric_shapes/<cell_id>.json folder with optimistic revision checks, camera optics revision, image-space and correction metadata. Stored outlines block permanent deletion of the cell; no ArUco, HIFIE, or volume data are overwritten.
- Relative scaling and image-outline estimation assume compatible lengths on the same physical plane. Uncorrected lens distortion, perspective and uncertain alignment can add significant error.

### Camera-first guided optical metrology — updated 25 November 2026

The full-width camera canvas is now the primary editing surface. Directly below it, **Optical measurements & cross-sectional area** contains reference-based dimensions, relative camera scale and visual XY cross-section outlines. Camera optical profile and ArUco/analysis ROI remain in a separate Camera calibration disclosure. Physical references, nominal cell geometry and experimental V(h) remain cell-owned and persist independently.

- A central camera view controller selects the intended camera for each marking task. The image preference is **Rectified** when a current ArUco association exists, otherwise **Undistorted** if optical parameters exist, and **Raw** only when corrected views cannot be acquired. A shape edit reopens its recorded image space and rejects incompatible optics; this avoids silently moving saved pixels across coordinate systems.
- A live marker status strip above the canvas says what to select next and shows the current point count. Markers are visible from the first click and are numbered in the cross-section editor. Stop picking, Undo point and Close polygon are explicit actions. Pixel selections from an incompatible camera/image space are cleared; metric centimetre measurements from a calibrated source remain separate.
- A rectangle or square can be drawn from two axis-aligned diagonal corners; from three consecutive corners to infer the fourth as a parallelogram; or from four *side midpoints* marked in order around the perimeter, approximating four corners. A circle uses a diameter pair. A polygon uses 3–32 consecutive vertices and is explicitly closed. The form editor stores only independent shape points, not additional Named Physical References.
- When the outline has edges, the operator chooses which edge corresponds to an existing physical Width or Depth. Polygon / rotated rectangle area is estimated by multiplying pixel polygon area by the square of the physical-length-to-pixel-edge ratio. Old two-corner outlines retain horizontal/vertical anchor semantics. The resulting area is a separate approximate transverse-section estimate, not the calibrated effective area and not experimental V(h).
- A top camera with no ArUco can still be used with an independently known source dimension. If the destination *does* have a current rectified view, relative calibration can measure its pixel ratio on that view as well, tied to the exact saved calibration ID. No existing homography or HIFIE config is replaced.
- Optical correction, remaining perspective and nonplanarity are explicit sources of geometric measurement uncertainty. Midpoints in the four-face method are assumed to approximate the actual centers of each side; this method does not infer a general projective quadrilateral from arbitrary side points.

Regression coverage: src/tests is not used; tests/test_cells_geometric_shapes.py covers non-destructive storage, rotated and polygon geometry; tests/test_cells_metrology_ui.js checks the camera and progressive editor wiring.
