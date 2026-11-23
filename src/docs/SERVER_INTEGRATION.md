# Server synchronization, inventory and offline execution

**Sources:** `src/lib/server.py`, `src/lib/server_sync.py`, `src/lib/cell_inventory.py`. Reviewed 2026-11-23.

## Ownership and protocol

- **Server:** users, campaigns, DoE, experiment definitions/revisions, `spec_hash`, execution history and location references.
- **Edge:** registered cells and thumbnails, instruments, cameras, calibration, physical recordings, observed measurements and effective runtime settings.
- Recipe selection can be made offline if the recipe was cached previously. Sync runs asynchronously; a Server outage must not stop the run.

The Edge logs in through `POST /devices/login` with the device ID (legacy form field `cell_id`) and token. It reads `capabilities.device_api_version`. API v2 enables the hierarchical catalog, execution claim, outbox replay and optional inventory capabilities. Legacy mode remains supported when v2 is not advertised.

## Cache and worker cadence

Under `local_storage/_server_cache/`:

- `catalog.json`: last fetched User → Campaign → Experiment hierarchy.
- `experiments/`: recipe response and immutable execution template for each cached revision.
- `state.json`: connection and catalog bookkeeping.
- `inventory_state.json`: inventory revision/hash and uploaded photograph digests.

The existing sync worker refreshes the catalog on a nominal **300 s** interval. Its lightweight inventory check is nominally **60 s**. Configuration changes mark inventory dirty and can prompt an earlier check while connected. Network/offline probes and retry backoff avoid repeated expensive failures. These intervals are code defaults, not exact guarantees. The worker does **not** open a camera, capture a frame or sample instrument readings to build an inventory.

`POST /api/server/sync` on the Edge requests an immediate sync attempt; the call is asynchronous and reports HTTP 202. Check `GET /api/server/status` for the current state, pending count and last error.

## Inventory publication and photos

A connected v2 Server with `device_inventory_v1` exposes:

```text
GET    /devices/v2/inventory/control
PUT    /devices/v2/inventory
PUT    /devices/v2/cells/{cell_id}/thumbnail?revision=N
DELETE /devices/v2/cells/{cell_id}/thumbnail
```

The Edge builds and hashes a canonical metadata payload, sends it when the content changes or the Server requests refresh, and uploads WebP photos **separately** on digest change. The Server rejects stale revisions and mismatched same-revision payloads. A missing photo can be deleted independently. A full image is not resent every sync cycle.

**Verified limitation (2026-11-23):** `ServerSync._reconcile_inventory_v2` currently restricts the outgoing `core` to `schema_version,cells,sensors` although `build_inventory` also returns `cameras,virtual_calibration`. Consequently the current published hash excludes those two fields and Server UI may display no individual cameras/calibration status. This is a contract gap, not a reason to increase sync frequency. Update the publishing core and add end-to-end tests before claiming camera-level inventory parity.

## Recipe, execution and outbox

1. The Edge caches the v2 recipe and `execution_template`, including `experiment_id`, `experiment_revision`, `spec_hash` and `experiment_snapshot`.
2. When a run is created, it assigns a persistent `client_execution_id` in `server_sync.json`.
3. The Edge claims or replays the run with the original hash/snapshot and monotonic sequence.
4. During execution it records the runtime `execution_inputs`, `cell_profile`, `measurements_summary`, `effective_setup` and `sensors_used` as **mutable execution metadata**.
5. The Server stores event ordering by sequence; retries do not overwrite a newer status with an older one. The location record and file manifest reference locally stored data rather than silently uploading all raw files.

`effective_setup_snapshot.json` is frozen at run start. The outgoing `effective_setup` is a copy enriched with stage acquisition overrides, stage history and explicitly ignored measurement requirements; it does **not** rewrite the frozen file.

Important: `measurements_summary` is a summary, **not** the complete `measurements.jsonl`. For full observation audit, retain the Edge run directory. Final run-status sync and local file storage are separate operations.

## Offline safety

- Cached recipes remain usable during loss of connectivity.
- `server_sync.json` and outbox state persist across application restart.
- Terminal status and location manifest can be replayed when the Server returns.
- A missing or outdated recipe cache must not be presented as a new current revision.
- Network errors belong to sync diagnostics; they should not trigger camera restarts or loss of a local experiment.

## Diagnosis

```bash
curl -fsS http://127.0.0.1:8000/api/server/status
journalctl -u digiflot -n 150 --no-pager
```

If the Server has stale inventory: check Server availability and device credentials, inspect the Edge status `inventory_error`, use **Sync now** from the Server device page or the Edge sync endpoint, then verify the Server's `received_at` and `acknowledged_revision`. Do not repeatedly restart a running Edge.

For full Server route contracts and authentication, see the Server repository's `api/docs/EDGE_API_V2_CONTRACT.md` and `api/docs/DEVICE_INVENTORY.md`.
