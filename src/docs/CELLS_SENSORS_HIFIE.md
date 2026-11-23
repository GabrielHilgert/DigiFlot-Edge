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
