# DigiFlot Edge

DigiFlot Edge is the local Raspberry Pi application for laboratory flotation experiments. It runs the experiment, acquires camera and instrument data, maintains calibrated flotation-cell geometry, and synchronizes definitions and execution records with DigiFlot Server. **An experiment can continue when the Server is unavailable.**

## Start here

| Task | Documentation |
| --- | --- |
| Install or update the Raspberry Pi | [Deployment and maintenance](src/docs/DEPLOYMENT_MAINTENANCE.md) |
| Understand components and stored files | [System architecture](src/docs/SYSTEM_ARCHITECTURE.md) |
| Prepare and execute stages | [Stages and measurements](src/docs/EXPERIMENTS_STAGES_MEASUREMENTS.md) |
| Register a cell, camera, or HIFIE | [Cells and sensors](src/docs/CELLS_SENSORS_HIFIE.md) |
| Understand offline Server synchronization | [Server integration](src/docs/SERVER_INTEGRATION.md) |
| Call or extend the local API | [HTTP API reference](src/docs/HTTP_API_REFERENCE.md) |
| Diagnose a failure or run tests | [Troubleshooting and validation](src/docs/TROUBLESHOOTING.md) |

The [complete documentation index](src/docs/README.md) links the older, more specialized design notes.

## Installation

For a new Raspberry Pi installation, download and run the managed installer (inspect the script before running it):

```bash
curl -fsSL https://raw.githubusercontent.com/GabrielHilgert/DigiFlot-Edge/main/src/install.sh -o install.sh
chmod +x install.sh
./install.sh
```

The installed tree is `/opt/digiflot-edge`. The FastAPI process is managed by `digiflot.service`, normally at `http://127.0.0.1:8000`. The service account owns the installation and hardware access. Existing installations should use `sudo digiflot-update`, **not** the installer. Do not update during an active or preparing experiment.

```bash
digiflot-status
sudo digiflot-update
journalctl -u digiflot -f
```

## Repository layout

- `src/app.py` — FastAPI startup, page routes, API registration, execution lock.
- `src/lib/digiflot.py` — experiment/stage state machine and recording orchestration.
- `src/lib/server_sync.py` / `src/lib/server.py` — offline cache, outbox and Server HTTP client.
- `src/lib/vision/` and `src/lib/virtual_sensors/` — cell calibration and HIFIE.
- `src/lib/camera.py`, `atlasScientific.py`, `scale.py`, `wago.py`, `bronkhorst.py`, `plugins.py` — data acquisition.
- `src/api/` — local endpoints; `src/ui/` — Jinja/JavaScript/CSS interface.
- `src/deploy/` — managed update, systemd and browser maintenance.
- `tests/` and `.github/workflows/edge-checks.yml` — hardware-free regression checks.

## Design rules

- Server owns recipe definitions and execution history; Edge owns equipment, local cell inventory, calibration and raw recordings.
- Runtime changes and measurements must not silently modify the immutable Server recipe snapshot or its `spec_hash`.
- A camera has one owner/configuration at a time. Share an existing `lores` stream with HIFIE rather than opening independent Picamera2 streams.
- `duration = 0` denotes a manually finished stage, **not** a zero-length acquisition.
- Configuring a sensor as inactive for one stage stops its writer; it must not switch off safety-relevant hardware.
- A missing mandatory measurement blocks starting the next stage unless the operator explicitly records a waiver.

## Implementation status

This reference describes the code on `main` as inspected on 2026-11-23. Automated tests do **not** replace a trial with the physical cameras, power meter and laboratory hardware. See [known limitations](src/docs/TROUBLESHOOTING.md#known-implementation-limitations).
