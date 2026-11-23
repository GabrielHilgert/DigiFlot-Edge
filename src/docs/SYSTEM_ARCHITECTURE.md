# Edge system architecture

**Scope:** implementation as of 2026-11-23. Entry point: `src/app.py`; orchestration: `src/lib/digiflot.py`.

## Boundaries

```text
Browser (Run / Cells / Cameras / Sensors / Results / Settings)
  | HTTP + SSE / WebSocket
FastAPI (src/app.py, src/api/*)
  |--- DigiFlot controller: experiment and stage state, setpoints, locks
  |       |--- cameras and physical sensor writers
  |       |--- VisionService and HIFIE virtual worker
  |       |--- StorageEstimator / disk and performance monitoring
  |       |--- event, measurement, runtime and snapshot persistence
  |--- ServerSync worker ----HTTP/session----> DigiFlot Server
  |       |--- cached recipes/catalog
  |       |--- execution outbox and location manifest
  |       |--- inventory and thumbnail publication
  |--- ResultsMediaManager: idle-only WebSocket/FFmpeg playback
```

A FastAPI lifespan builds `DigiFlot`, attaches `VisionService`, restores prior virtual calibration where appropriate, then starts the non-blocking `ServerSync` worker. The Server is not required for local application startup.

## Core modules

| Component | Source | Responsibility |
| --- | --- | --- |
| HTTP startup/locking | `src/app.py` | Lifespan, page routes, route guard |
| Main controller | `src/lib/digiflot.py` | Global state, stage state, calibration, writers, measurements and events |
| Camera | `src/lib/camera.py` | Picamera2, preview/recording and main/lores resources |
| Cell registry | `src/lib/vision/registry.py` | Cell definitions, revisions, datums, associations, detector profiles and photos |
| Vision service | `src/lib/vision/service.py` | Calibrated views, HIFIE benchmark and virtual acquisition lifecycle |
| Detection | `src/lib/virtual_sensors/` | Froth-interface estimation and temporal stabilization |
| Sensor adapters | `src/lib/{scale,atlasScientific,bronkhorst,wago,plugins}.py` | Physical values, calibration and output writers |
| Storage and performance | `src/lib/storage_estimator.py`, `performance.py` | Estimate capacity, monitor disk/load and detect risks |
| Server client/cache | `src/lib/server.py`, `server_sync.py` | Login, recipe retrieval, inventory and offline replay |
| Results playback | `src/api/results_media.py` | Idle-only on-demand MJPEG/WebSocket |

## Controller and stage state

Global states include `Idle`, `CellSelection`, `CameraCalibration`, `SensorCalibration`, `Ready`, `Running`, `Paused`, `RecoveryRequired`, `Completed` and `Aborted`. The stage substate distinguishes waiting, active and transition. The seven UI workflow steps are **not** separate state machines.

The control loop uses monotonic deadlines for timed stages, transition timeouts and scraping. A manual stage (`duration: 0`) has no stage deadline. A required-measurement gate can hold a transition after a manual stage finishes. See [Stages and measurements](EXPERIMENTS_STAGES_MEASUREMENTS.md) and [legacy state-machine diagrams](DIGIFLOT_STATE_MACHINE.md).

## Persistence and provenance

The installed repository is `/opt/digiflot-edge`; runtime files are outside the tracked sources in `local_storage/`:

| Location | Contents |
| --- | --- |
| `local_storage/vision/cells/` | Registered flotation cells and geometry revisions |
| `local_storage/vision/associations/` | Camera–cell transforms, ROI and calibration history |
| `local_storage/vision/cell_thumbnails/` | Independent WebP cell photographs |
| `local_storage/_server_cache/` | Catalog, cached recipes, sync and inventory state |
| `local_storage/<run>/experiment.json` | Executed local recipe |
| `local_storage/<run>/config_snapshot.json` | Configuration snapshot |
| `local_storage/<run>/effective_setup_snapshot.json` | Frozen physical/virtual setup at run start |
| `local_storage/<run>/runtime.json` | Recoverable state, stage history, overrides and waivers |
| `local_storage/<run>/events.jsonl` | Ordered append-only execution events |
| `local_storage/<run>/measurements.jsonl` | Append-only operator/sensor-captured observations |
| `local_storage/<run>/server_sync.json` | Persistent Server execution claim/outbox state |
| `local_storage/<run>/sensors/` | Segmented physical sensor recordings |

The exact camera output layout follows the active recorder configuration. Do not edit run files while an experiment is active; preserve the directory and JSONL records as a unit when archiving it.

## Concurrency boundaries

- The controller lock protects state changes and transitions.
- Camera preview owners use tab-identification/heartbeat. Do not start a second Picamera2 stream to inspect a running camera.
- The HIFIE worker may use the camera's shared low-resolution stream without requiring video to be written.
- Sensor writers are reconciled at stage start/transition. Repeated start calls must not truncate old data.
- Background Server sync reads metadata and writes local outbox state; it must not sample sensors or acquire images.
- Results video playback is restricted to idle operation and does not compete with active acquisition.

## Related Server model

Server owns users, devices, campaigns, experiments, DoE and execution history. The legacy Server field `Experiment.cell_id` is a **device ID**, not the flotation-cell registry ID. The selected physical cell is an optional execution-target metadata choice. See [Server integration](SERVER_INTEGRATION.md).
