# DigiFlot Edge documentation

This index is the entry point for operators, maintainers and contributors. It reflects the implementation on `main` reviewed 2026-11-23.

## Current operational and integration documentation

| Document | Audience | Covers |
| --- | --- | --- |
| [System architecture](SYSTEM_ARCHITECTURE.md) | Developer | Components, ownership, state and local files |
| [Experiments, stages and measurements](EXPERIMENTS_STAGES_MEASUREMENTS.md) | Operator/developer | Stage duration, acquisition, automatic advance, required measurements and waivers |
| [Cells, sensors and HIFIE](CELLS_SENSORS_HIFIE.md) | Operator/developer | Geometry, images, virtual sensor and camera ownership |
| [Server integration](SERVER_INTEGRATION.md) | Developer/operator | v1/v2, cache, outbox, inventory and sync recovery |
| [Local HTTP API](HTTP_API_REFERENCE.md) | Developer | Routes and example payloads |
| [Troubleshooting and validation](TROUBLESHOOTING.md) | Operator/maintainer | Recovery, logs and acceptance checklist |
| [Deployment maintenance](DEPLOYMENT_MAINTENANCE.md) | Maintainer | Installation migration, updates, service and browser |

## Specialized design notes (retained)

- [Cell Vision and ArUco](CELL_VISION.md): detailed geometry, reference datums, ROI and calibration diagnostics.
- [HIFIE camera pipeline](HIFIE_CAMERA_PIPELINE.md): shared `lores`, tuning and camera lifecycle.
- [Execution state machine](DIGIFLOT_STATE_MACHINE.md): state diagrams and transitions.
- [Scraping timing and GPIO](SCRAPING_CONTROL.md): monotonic scheduling, output and alerts.
- [Example experiment](Example_experiment.json): historical reference. The stage metadata extensions in the current stage guide are additive.

The specialized documents were written at different implementation dates. For the **newer** stage-acquisition and measurement contracts, use the current stage guide. The live Python source is authoritative when a historical note differs.

## When modifying behavior

1. Update the relevant API/recipe contract on both Server and Edge, if the change crosses systems.
2. Update this index and the current operational guide.
3. Add no-hardware regressions in `tests/`; run the existing GitHub Actions suite.
4. Verify camera ownership, active-execution locks, resume behavior, outbox ordering, and backwards compatibility with older recipes.
5. Record any capability not yet implemented in the known limitations section. Do not document proposed behavior as working.
