# Troubleshooting, safe maintenance and validation

This guide describes the 2026-11-23 `main` implementation. It is not a substitute for checking a physically connected flotation cell.

## Before any maintenance

- Finish or abort the current experiment cleanly; do not interrupt camera or recorder tasks to perform routine updates.
- Preserve the complete run directory before destructive recovery. Do not edit `events.jsonl`, `measurements.jsonl` or `server_sync.json` by hand.
- Managed update/restart/sync commands refuse active or preparing runs unless explicitly overridden. Avoid `--force` except for a deliberate recovery.
- Do not print device tokens, Server credentials or session secrets in support logs.

## Commands

```bash
digiflot-status
sudo digiflot-update
sudo digiflot-restart
journalctl -u digiflot -n 200 --no-pager
journalctl -u digiflot -f
systemctl status digiflot
curl -i http://127.0.0.1:8000/health
curl -sS http://127.0.0.1:8000/api/digiflot/system/health
curl -sS http://127.0.0.1:8000/api/server/status
```

New installations use `src/install.sh`; the updater is for already installed systems. Browser and backend can restart independently.

## Symptoms and first checks

| Symptom | Likely area | Operator action |
| --- | --- | --- |
| Camera unavailable after calibrating HIFIE | Camera ownership, Preview/Recording switch, stale tab lease | Close the calibration modal, release its preview via UI, inspect `/api/digiflot/state`; do not start parallel streams |
| `Retake frame` or a frozen frame stalls preview | Competing capture/lores acquisition | Use a single managed preview and a raw snapshot; inspect camera ownership in logs |
| HIFIE visible but not running | No valid camera–cell benchmark or stage acquisition disabled | Review cell, camera, crop, ROI, rate and benchmark, then stage HIFIE flag |
| No video in a Custom stage | Expected default | Video defaults off; enable `video/all` or the individual camera |
| `Start now` is disabled after a manual stage | Missing required saved measurements | Open Data acquisition and capture each required variable, or choose audited Ignore and continue |
| Automatic transition does not start | Gate blocked, `auto_advance=false`, pause/recovery or timeout not elapsed | Review transition panel and state before changing recipe |
| Sensor TSV split into multiple files | Channel toggled by stages | Expected segmented acquisition; retain all segments |
| Storage shown as Open-ended | At least one manual stage | Review estimated disk autonomy; total cannot be guaranteed |
| Server stale/offline | Sync worker, token, route or Server status | Inspect `/api/server/status`; local run remains authoritative |
| Cell photo not visible on Server | Photo digest pending, inventory not uploaded or missing image | Inspect Edge photo, Server inventory timestamp, refresh only when connected |

## Run a regression suite

The automated workflow is `.github/workflows/edge-checks.yml`. It checks JavaScript, shell scripts, hardware-free Python drivers/vision/orchestration and persistence regressions. Typical focused commands from repository root:

```bash
PYTHONPATH=src python -m unittest discover -s tests -p 'test_manual_stage_measurement_gate.py' -v
PYTHONPATH=src python -m unittest discover -s tests -p 'test_stage_acquisition.py' -v
PYTHONPATH=src python -m unittest discover -s tests -p 'test_stage_channel_selection.py' -v
PYTHONPATH=src python -m unittest discover -s tests -p 'test_cell_inventory.py' -v
node --check src/ui/js/run.js
node tests/test_run_dom.js
```

These tests are designed to avoid hardware; a development machine may need the Python dependencies in `src/requirements.txt`. Consult CI for the complete order and environment.

## Hardware acceptance checklist

1. **Pre-run:** Save a cell, add/remove photo, verify geometry and photo revisions are independent; retrieve the Server inventory after synchronization.
2. **Camera lease:** Preview Camera 1 while Camera 2 records; confirm the Camera 1 preview and HIFIE `lores` stream remain active.
3. **HIFIE:** Approve the benchmark for the selected cell; run a stage with HIFIE active but main video disabled; deactivate and reactivate without stale preview ownership.
4. **Physical acquisition:** Toggle WAGO, Bronkhorst, Atlas and a scale between stages; verify no file is overwritten.
5. **Manual stage:** Use `duration=0` with two required variables. Finish without observations; verify automatic and manual next-stage start are blocked.
6. **Capture:** Record one measurement; verify remaining variable listed. Record second; verify the configured transition timer starts then, not before.
7. **Waiver:** Repeat with missing variables; choose Ignore and continue, verify `STAGE_REQUIRED_MEASUREMENTS_IGNORED` in `events.jsonl` and persisted waiver in `runtime.json`.
8. **Power/restart recovery:** Simulate a controlled restart in a disposable run; restore stage index, attempt, measurement gate and acquired data.
9. **Network outage:** Run with Server unavailable, then reconnect; check the recipe revision/hash and execution/client location history.
10. **Disk:** Run an open-ended stage in a test environment; verify live capacity protection and no fictitious fixed duration.

## Known implementation limitations

- **Inventory contract mismatch:** `src/lib/cell_inventory.py` constructs `cameras` and `virtual_calibration`, but `src/lib/server_sync.py` currently publishes/hashes only `schema_version`, `cells` and `sensors`. The Server may lack the individually listed camera channels and calibration status. This is a code-level gap, not a browser-cache issue.
- Required manual-stage variables are **not yet automatically materialized** as individual form entries. The Run shortcut fills the first pending variable's name; the operator uses the existing Data acquisition form.
- The mandatory-measurement gate operates **between** manual stages; it does not block completion of a last stage without a following stage.
- Server execution sync includes a measurement **summary**. The full append-only measurement and camera files remain on the Edge.
- Automated CI validates software without proving live hardware camera timing, calibration quality, electrical safety or instrument accuracy.

## Documentation maintenance

For a new route or schema, update [HTTP API](HTTP_API_REFERENCE.md), [Stage contract](EXPERIMENTS_STAGES_MEASUREMENTS.md) and [Server integration](SERVER_INTEGRATION.md) as appropriate, then add a regression test. Do not delete older specialized design documents without replacing their experimental diagnostics.
