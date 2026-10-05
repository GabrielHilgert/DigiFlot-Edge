from __future__ import annotations

import hashlib
import json
import os
import shutil
import socket
import threading
import time
import uuid

from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import requests


TERMINAL_EXECUTION_STATES = {"completed", "aborted", "failed"}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _atomic_write_json(path: Path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("w", encoding="utf-8") as file:
        json.dump(payload, file, indent=2, ensure_ascii=False, default=str)
        file.flush()
        os.fsync(file.fileno())
    os.replace(temporary, path)


def _read_json(path: Path, default=None):
    try:
        with Path(path).open("r", encoding="utf-8") as file:
            return json.load(file)
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return deepcopy(default)


def _is_derived_camera_cache(directory: Path, path: Path) -> bool:
    try:
        relative = Path(path).resolve().relative_to(Path(directory).resolve())
    except ValueError:
        return False
    parts = relative.parts
    return len(parts) >= 3 and parts[0] == "cameras" and parts[2] == "cache"


def _directory_size(directory: Path) -> int:
    total = 0
    try:
        for path in Path(directory).rglob("*"):
            if path.is_file() and not _is_derived_camera_cache(directory, path):
                try:
                    total += path.stat().st_size
                except OSError:
                    pass
    except OSError:
        pass
    return total


class ServerSync:
    """Persistent, offline-safe synchronization between one Edge and Server.

    The synchronization model is deliberately state-based rather than a queue
    of HTTP requests. Every execution stores its latest truth in
    ``server_sync.json``. The Server receives that truth at-least-once and uses
    client IDs + sequence numbers for idempotency/order.
    """

    NETWORK_BACKOFF = (5, 20, 60, 300, 900, 1800, 3600, 7200, 14400)
    SERVER_BACKOFF = (30, 120, 600, 1800)
    CATALOG_REFRESH_S = 300
    DEEP_OFFLINE_PROBE_S = 300
    LOCAL_NETWORK_CHECK_S = 30

    def __init__(self, server, local_storage_dir: Path):
        self.server = server
        self.local_storage_dir = Path(local_storage_dir)
        self.cache_dir = self.local_storage_dir / "_server_cache"
        self.recipes_dir = self.cache_dir / "experiments"
        self.catalog_path = self.cache_dir / "catalog.json"
        self.state_path = self.cache_dir / "state.json"

        self.lock = threading.RLock()
        self.stop_event = threading.Event()
        self.wake_event = threading.Event()
        self.thread = None
        self._force_requested = True

        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.recipes_dir.mkdir(parents=True, exist_ok=True)

        saved = _read_json(self.state_path, {}) or {}
        self.mode = str(saved.get("mode") or "unknown")
        self.connection_state = "offline"
        self.last_error = saved.get("last_error")
        self.last_success_at = saved.get("last_success_at")
        self.last_catalog_sync_at = saved.get("last_catalog_sync_at")
        self.catalog_hash = saved.get("catalog_hash")
        self.failure_count = int(saved.get("failure_count") or 0)
        self.auth_blocked = False
        self.syncing = False

        self.next_http_at = time.monotonic()
        self.next_probe_at = time.monotonic() + self.DEEP_OFFLINE_PROBE_S
        self._last_network_signature = self._network_signature()

    # ------------------------------------------------------------------
    # Lifecycle / status
    # ------------------------------------------------------------------

    def start(self):
        with self.lock:
            if self.thread is not None and self.thread.is_alive():
                return
            self.stop_event.clear()
            self.thread = threading.Thread(
                target=self._worker,
                name="digiflot-server-sync",
                daemon=True,
            )
            self.thread.start()

    def stop(self, timeout=3.0):
        self.stop_event.set()
        self.wake_event.set()
        thread = self.thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=timeout)

    def force_sync(self):
        with self.lock:
            self._force_requested = True
            self.auth_blocked = False
            self.next_http_at = time.monotonic()
        self.wake_event.set()

    def notify_pending(self):
        """Wake the worker without bypassing a deep-offline circuit breaker."""
        self.wake_event.set()

    def status_payload(self):
        with self.lock:
            pending, errors = self._pending_counts_unlocked()
            cached = self._cached_recipe_count_unlocked()
            now = time.monotonic()
            next_check = None
            if not self.auth_blocked and self.next_http_at != float("inf"):
                next_check = max(0, int(round(self.next_http_at - now)))
            return {
                "state": "syncing" if self.syncing else self.connection_state,
                "mode": self.mode,
                "api_version": int(getattr(self.server, "api_version", 1) or 1),
                "last_error": self.last_error,
                "last_success_at": self.last_success_at,
                "last_catalog_sync_at": self.last_catalog_sync_at,
                "catalog_hash": self.catalog_hash,
                "pending_executions": pending,
                "sync_errors": errors,
                "cached_experiments": cached,
                "next_check_seconds": next_check,
                "auth_blocked": self.auth_blocked,
            }

    def _persist_state_unlocked(self):
        _atomic_write_json(self.state_path, {
            "mode": self.mode,
            "connection_state": self.connection_state,
            "last_error": self.last_error,
            "last_success_at": self.last_success_at,
            "last_catalog_sync_at": self.last_catalog_sync_at,
            "catalog_hash": self.catalog_hash,
            "failure_count": self.failure_count,
            "saved_at": _utc_now(),
        })

    # ------------------------------------------------------------------
    # Catalog / recipe cache
    # ------------------------------------------------------------------

    def catalog_payload(self):
        catalog = _read_json(self.catalog_path, None)
        if not isinstance(catalog, dict):
            catalog = {
                "api_version": 2 if self.mode == "v2" else 1,
                "catalog_hash": None,
                "generated_at": None,
                "counts": {"users": 0, "campaigns": 0, "experiments": 0},
                "users": [],
            }
        catalog = deepcopy(catalog)
        for user in catalog.get("users") or []:
            for campaign in user.get("campaigns") or []:
                for experiment in campaign.get("experiments") or []:
                    experiment["available_offline"] = self._recipe_cached_for_entry(experiment)
        return catalog

    def get_experiment(self, experiment_id: int):
        experiment_id = int(experiment_id)
        entry = self._catalog_experiment(experiment_id)
        cached = self._read_cached_recipe(experiment_id, entry)
        if cached is not None:
            return self._recipe_for_edge(cached)

        # Cache miss: only try a direct fetch when the circuit currently
        # believes the Server is reachable. Otherwise fail fast and keep the
        # operator-facing UI responsive offline.
        if self.connection_state in {"connected", "syncing"} and not self.auth_blocked:
            try:
                if self.mode == "v2" or int(getattr(self.server, "api_version", 1) or 1) >= 2:
                    payload = self.server.get_experiment_v2(experiment_id)
                    self._write_recipe_cache(payload)
                else:
                    recipe = self.server.get_experiment(experiment_id)
                    payload = self._legacy_recipe_payload(recipe)
                    self._write_recipe_cache(payload)
                return self._recipe_for_edge(payload)
            except Exception as error:
                self._register_failure(error)

        self.notify_pending()
        raise RuntimeError("This experiment recipe is not cached locally and the central Server is unavailable.")

    def _catalog_experiment(self, experiment_id):
        catalog = _read_json(self.catalog_path, {}) or {}
        for user in catalog.get("users") or []:
            for campaign in user.get("campaigns") or []:
                for experiment in campaign.get("experiments") or []:
                    if int(experiment.get("id") or -1) == int(experiment_id):
                        result = deepcopy(experiment)
                        result["_owner"] = {"id": user.get("id"), "name": user.get("name")}
                        result["_campaign"] = {
                            "id": campaign.get("id"),
                            "name": campaign.get("name"),
                            "kind": campaign.get("kind"),
                        }
                        return result
        return None

    def _recipe_path(self, experiment_id, revision=1):
        return self.recipes_dir / str(int(experiment_id)) / f"{int(revision or 1)}.json"

    def _recipe_cached_for_entry(self, entry):
        if not isinstance(entry, dict) or entry.get("id") is None:
            return False
        path = self._recipe_path(entry["id"], entry.get("revision") or 1)
        payload = _read_json(path, None)
        if not isinstance(payload, dict):
            return False
        expected = entry.get("spec_hash")
        return not expected or not payload.get("spec_hash") or str(payload.get("spec_hash")) == str(expected)

    def _read_cached_recipe(self, experiment_id, entry=None):
        revision = (entry or {}).get("revision") or 1
        payload = _read_json(self._recipe_path(experiment_id, revision), None)
        if isinstance(payload, dict):
            expected = (entry or {}).get("spec_hash")
            if not expected or not payload.get("spec_hash") or str(expected) == str(payload.get("spec_hash")):
                return payload

        # An old catalog may not know the latest revision. Prefer the newest
        # cached recipe rather than losing offline access entirely.
        directory = self.recipes_dir / str(int(experiment_id))
        if directory.is_dir():
            candidates = sorted(directory.glob("*.json"), key=lambda p: p.name, reverse=True)
            for path in candidates:
                payload = _read_json(path, None)
                if isinstance(payload, dict):
                    return payload
        return None

    def _write_recipe_cache(self, payload):
        if not isinstance(payload, dict):
            return
        experiment = payload.get("experiment") or {}
        recipe = payload.get("recipe") or payload
        experiment_id = experiment.get("id", recipe.get("id") if isinstance(recipe, dict) else None)
        if experiment_id is None:
            return
        revision = experiment.get("revision") or recipe.get("revision") or 1
        _atomic_write_json(self._recipe_path(experiment_id, revision), payload)

    def _recipe_for_edge(self, payload):
        payload = deepcopy(payload or {})
        recipe = deepcopy(payload.get("recipe") or {})
        if not isinstance(recipe, dict):
            raise RuntimeError("Cached experiment recipe is invalid.")
        recipe["source"] = "Server"
        recipe["_server"] = {
            "api_version": int(payload.get("api_version") or 1),
            "experiment": deepcopy(payload.get("experiment") or {}),
            "context": deepcopy(payload.get("context") or {}),
            "spec_hash": payload.get("spec_hash"),
            "execution_template": deepcopy(payload.get("execution_template")),
            "cached_at": payload.get("cached_at"),
        }
        return recipe

    def _legacy_recipe_payload(self, recipe):
        recipe = deepcopy(recipe or {})
        user_id = recipe.get("user_id")
        return {
            "api_version": 1,
            "experiment": {
                "id": recipe.get("id"),
                "name": recipe.get("name"),
                "revision": 1,
                "creation_time": recipe.get("creation_time"),
                "last_modified": recipe.get("last_modified"),
            },
            "context": {
                "owner": {"id": user_id, "name": f"User {user_id}" if user_id is not None else "Server"},
                "campaign": None,
                "origin": {"type": "manual"},
                "template": {"is_template": False, "design_count": 0, "designs": []},
            },
            "recipe": recipe,
            "spec_hash": None,
            "execution_template": None,
            "cached_at": _utc_now(),
        }

    # ------------------------------------------------------------------
    # Execution persistence
    # ------------------------------------------------------------------

    def ensure_execution(self, run_directory: Path, experiment: dict, status="preparing"):
        run_directory = Path(run_directory)
        server_meta = (experiment or {}).get("_server") or {}
        execution_template = server_meta.get("execution_template")
        if not isinstance(execution_template, dict):
            return None

        path = run_directory / "server_sync.json"
        with self.lock:
            current = _read_json(path, None)
            if isinstance(current, dict) and current.get("client_execution_id"):
                return current

            now = _utc_now()
            context = deepcopy(server_meta.get("context") or execution_template.get("campaign_context") or {})
            record = {
                "client_execution_id": f"edge-{uuid.uuid4()}",
                "server_execution_id": None,
                "client_location_id": f"edge-location-{uuid.uuid4()}",
                "sequence": 1,
                "sync_status": "pending",
                "status": str(status),
                "reported_offline": self.connection_state != "connected",
                "edge_created_at": now,
                "started_at": None,
                "finished_at": None,
                "last_sync_attempt": None,
                "last_sync_error": None,
                "experiment_id": execution_template.get("experiment_id"),
                "experiment_revision": execution_template.get("experiment_revision") or 1,
                "spec_hash": execution_template.get("spec_hash"),
                "experiment_snapshot": deepcopy(execution_template.get("experiment_snapshot") or {}),
                "campaign_context": deepcopy(execution_template.get("campaign_context") or context),
                "display_context": context,
                "location": {
                    "client_location_id": None,  # filled below after ID is known
                    "storage_type": "edge_local",
                    "storage_id": run_directory.name,
                    "path": str(run_directory.resolve()),
                    "uri": None,
                    "status": "available",
                    "size_bytes": None,
                    "manifest": None,
                },
            }
            record["location"]["client_location_id"] = record["client_location_id"]
            _atomic_write_json(path, record)

        self.notify_pending()
        return record

    def update_execution(self, run_directory: Path, status: str, *, occurred_at=None):
        run_directory = Path(run_directory)
        path = run_directory / "server_sync.json"
        with self.lock:
            record = _read_json(path, None)
            if not isinstance(record, dict):
                return None

            status = str(status).strip().lower()
            previous = str(record.get("status") or "").lower()
            if status != previous:
                record["sequence"] = int(record.get("sequence") or 0) + 1
            record["status"] = status
            record["sync_status"] = "pending"
            record["last_sync_error"] = None
            occurred_at = occurred_at or _utc_now()

            if status == "running" and not record.get("started_at"):
                record["started_at"] = occurred_at
            if status in TERMINAL_EXECUTION_STATES:
                record["finished_at"] = occurred_at
                location = record.setdefault("location", {})
                location["size_bytes"] = _directory_size(run_directory)
                location["manifest"] = self._manifest(run_directory)

            _atomic_write_json(path, record)

        self.notify_pending()
        return record

    def _manifest(self, run_directory: Path):
        files = []
        try:
            for path in sorted(Path(run_directory).rglob("*")):
                if (
                    not path.is_file()
                    or path.name == "server_sync.json"
                    or _is_derived_camera_cache(run_directory, path)
                ):
                    continue
                try:
                    stat = path.stat()
                except OSError:
                    continue
                files.append({
                    "path": path.relative_to(run_directory).as_posix(),
                    "size_bytes": stat.st_size,
                    "mtime_ns": stat.st_mtime_ns,
                })
        except OSError:
            pass
        return {"generated_at": _utc_now(), "files": files}

    def _execution_records(self, *, pending_only=True):
        records = []
        self.local_storage_dir.mkdir(parents=True, exist_ok=True)
        for directory in self.local_storage_dir.iterdir():
            if not directory.is_dir() or directory.name.startswith("_"):
                continue
            path = directory / "server_sync.json"
            record = _read_json(path, None)
            if not isinstance(record, dict) or not record.get("client_execution_id"):
                continue
            if pending_only and record.get("sync_status") == "synced":
                continue
            records.append((directory, path, record))
        return records

    def _sync_payload(self, record):
        location = deepcopy(record.get("location") or {})
        return {
            "client_execution_id": record.get("client_execution_id"),
            "experiment_id": record.get("experiment_id"),
            "experiment_revision": record.get("experiment_revision") or 1,
            "spec_hash": record.get("spec_hash"),
            "experiment_snapshot": deepcopy(record.get("experiment_snapshot") or {}),
            "campaign_context": deepcopy(record.get("campaign_context") or {}),
            "reported_offline": bool(record.get("reported_offline")),
            "sequence": int(record.get("sequence") or 0),
            "status": record.get("status"),
            "edge_created_at": record.get("edge_created_at"),
            "started_at": record.get("started_at"),
            "finished_at": record.get("finished_at"),
            "locations": [location] if location.get("client_location_id") else [],
        }

    # ------------------------------------------------------------------
    # Worker / retry strategy
    # ------------------------------------------------------------------

    def _worker(self):
        while not self.stop_event.is_set():
            now = time.monotonic()
            forced = False
            with self.lock:
                if self._force_requested:
                    forced = True
                    self._force_requested = False

            network_signature = self._network_signature()
            if self._network_returned(self._last_network_signature, network_signature):
                forced = True
            self._last_network_signature = network_signature

            should_http = forced or (not self.auth_blocked and now >= self.next_http_at)
            if not should_http and now >= self.next_probe_at:
                self.next_probe_at = now + self.DEEP_OFFLINE_PROBE_S
                if self._server_port_reachable():
                    should_http = True

            if should_http:
                self._attempt_sync(force_catalog=forced)
                continue

            wait_candidates = [self.LOCAL_NETWORK_CHECK_S]
            if not self.auth_blocked and self.next_http_at != float("inf"):
                wait_candidates.append(max(0.25, self.next_http_at - now))
            wait_candidates.append(max(0.25, self.next_probe_at - now))
            timeout = max(0.25, min(wait_candidates))
            self.wake_event.wait(timeout=timeout)
            self.wake_event.clear()

    def _attempt_sync(self, *, force_catalog=False):
        with self.lock:
            self.syncing = True
            self.connection_state = "syncing"

        try:
            login = self.server.login()
            api_version = int((login.get("capabilities") or {}).get("device_api_version") or 1) if isinstance(login, dict) else 1
            self.mode = "v2" if api_version >= 2 else "legacy"
            self.auth_blocked = False

            # The optional endpoint may not exist yet (including on a legacy
            # Server). This is deliberately best-effort: 404/5xx/schema errors
            # and network failures never change the outcome of synchronization.
            self.server.report_device_ip(self._local_ip_for_server())

            if self.mode == "v2":
                self._sync_pending_v2()
                due_catalog = force_catalog or self._catalog_due()
                if due_catalog:
                    self._refresh_catalog_v2()
            else:
                self._refresh_catalog_legacy()

            with self.lock:
                self.connection_state = "connected"
                self.last_error = None
                self.last_success_at = _utc_now()
                self.failure_count = 0
                self.next_http_at = time.monotonic() + self.CATALOG_REFRESH_S
                self.next_probe_at = time.monotonic() + self.DEEP_OFFLINE_PROBE_S
                self._persist_state_unlocked()

        except Exception as error:
            self._register_failure(error)
        finally:
            with self.lock:
                self.syncing = False

    def _catalog_due(self):
        if not self.catalog_path.is_file() or not self.last_catalog_sync_at:
            return True
        try:
            stamp = datetime.fromisoformat(str(self.last_catalog_sync_at).replace("Z", "+00:00"))
            return (datetime.now(timezone.utc) - stamp).total_seconds() >= self.CATALOG_REFRESH_S
        except Exception:
            return True

    def _refresh_catalog_v2(self):
        catalog = self.server.get_catalog()
        if not isinstance(catalog, dict):
            raise RuntimeError("Server returned an invalid API-v2 catalog.")

        _atomic_write_json(self.catalog_path, catalog)
        self.catalog_hash = catalog.get("catalog_hash")
        self.last_catalog_sync_at = _utc_now()

        # Pre-cache every available recipe so losing the Server later does not
        # stop the operator from running experiments that were already visible.
        for user in catalog.get("users") or []:
            for campaign in user.get("campaigns") or []:
                for entry in campaign.get("experiments") or []:
                    if self._recipe_cached_for_entry(entry):
                        continue
                    payload = self.server.get_experiment_v2(int(entry["id"]))
                    payload = dict(payload or {})
                    payload["cached_at"] = _utc_now()
                    self._write_recipe_cache(payload)

    def _refresh_catalog_legacy(self):
        experiments = self.server.get_available_experiments() or []
        if not isinstance(experiments, list):
            raise RuntimeError("Legacy Server returned an invalid experiment list.")

        entries = []
        for experiment in experiments:
            if not isinstance(experiment, dict):
                continue
            entry = {
                "id": experiment.get("id"),
                "name": experiment.get("name") or f"Experiment {experiment.get('id')}",
                "revision": 1,
                "origin": "manual",
                "experimental_design_id": None,
                "design_name": None,
                "design_method": None,
                "design_revision": None,
                "run_order": None,
                "is_template": False,
                "template_for_design_count": 0,
                "template_for_design_ids": [],
                "execution_count": 0,
                "last_execution_at": None,
                "last_execution_status": None,
                "spec_hash": None,
                "creation_time": experiment.get("creation_time"),
                "last_modified": experiment.get("last_modified"),
            }
            entries.append(entry)
            if not self._recipe_cached_for_entry(entry):
                recipe = self.server.get_experiment(int(entry["id"]))
                payload = self._legacy_recipe_payload(recipe)
                self._write_recipe_cache(payload)

        catalog = {
            "api_version": 1,
            "catalog_hash": hashlib.sha256(json.dumps(entries, sort_keys=True, default=str).encode()).hexdigest(),
            "generated_at": _utc_now(),
            "device": {"id": self.server.id, "name": self.server.name},
            "counts": {"users": 1 if entries else 0, "campaigns": 0, "experiments": len(entries)},
            "users": ([{
                "id": None,
                "name": "Server",
                "counts": {"campaigns": 0, "experiments": len(entries)},
                "campaigns": [{
                    "id": None,
                    "name": "Unassigned",
                    "status": None,
                    "kind": "unassigned",
                    "counts": {"experiments": len(entries), "templates": 0, "executed": 0},
                    "experiments": entries,
                }],
            }] if entries else []),
        }
        _atomic_write_json(self.catalog_path, catalog)
        self.catalog_hash = catalog["catalog_hash"]
        self.last_catalog_sync_at = _utc_now()

    def _sync_pending_v2(self):
        records = self._execution_records(pending_only=True)
        if not records:
            return

        for offset in range(0, len(records), 250):
            batch = records[offset:offset + 250]
            sent_sequences = [int(record.get("sequence") or 0) for _, _, record in batch]
            response = self.server.sync_executions([self._sync_payload(record) for _, _, record in batch])
            results = response.get("results") if isinstance(response, dict) else None
            if not isinstance(results, list):
                raise RuntimeError("Server returned an invalid execution sync response.")

            for index, (directory, path, original) in enumerate(batch):
                result = results[index] if index < len(results) and isinstance(results[index], dict) else {"ok": False, "error": "Missing result"}
                current = _read_json(path, original) or original
                current["last_sync_attempt"] = _utc_now()

                if result.get("ok"):
                    execution = result.get("execution") or {}
                    current["server_execution_id"] = execution.get("execution_id", current.get("server_execution_id"))
                    current["last_sync_error"] = None
                    # Do not mark synced if the runtime advanced while this HTTP
                    # request was in flight; the new sequence still needs replay.
                    if int(current.get("sequence") or 0) == sent_sequences[index]:
                        current["sync_status"] = "synced"
                    else:
                        current["sync_status"] = "pending"
                else:
                    code = int(result.get("status_code") or 0)
                    current["last_sync_error"] = str(result.get("error") or "Synchronization failed")
                    current["sync_status"] = "error" if code in {400, 404, 409, 422} else "pending"

                _atomic_write_json(path, current)

    def _register_failure(self, error):
        response = getattr(error, "response", None)
        status_code = getattr(response, "status_code", None)
        with self.lock:
            self.last_error = str(error)
            self.failure_count += 1
            now = time.monotonic()

            if status_code in {401, 403}:
                self.connection_state = "auth_error"
                self.auth_blocked = True
                self.next_http_at = float("inf")
            elif status_code is not None and int(status_code) >= 500:
                self.connection_state = "error"
                delay = self.SERVER_BACKOFF[min(self.failure_count - 1, len(self.SERVER_BACKOFF) - 1)]
                self.next_http_at = now + self._jitter(delay)
            elif isinstance(error, (requests.ConnectionError, requests.Timeout)) or status_code is None:
                self.connection_state = "offline"
                delay = self.NETWORK_BACKOFF[min(self.failure_count - 1, len(self.NETWORK_BACKOFF) - 1)]
                self.next_http_at = now + self._jitter(delay)
            else:
                self.connection_state = "error"
                delay = self.SERVER_BACKOFF[min(self.failure_count - 1, len(self.SERVER_BACKOFF) - 1)]
                self.next_http_at = now + self._jitter(delay)

            self.next_probe_at = min(self.next_probe_at, now + self.DEEP_OFFLINE_PROBE_S)
            self._persist_state_unlocked()

    def _jitter(self, seconds):
        # Stable per-device phase; avoids many Edges polling at exactly once
        # without requiring non-deterministic retry behavior.
        seed = hashlib.sha256(str(self.server.id).encode()).digest()[0] / 255.0
        factor = 0.9 + 0.2 * seed
        return max(1.0, float(seconds) * factor)

    def _server_port_reachable(self):
        parsed = urlparse(str(self.server.ip or ""))
        host = parsed.hostname
        if not host:
            return False
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        try:
            with socket.create_connection((host, port), timeout=1.0):
                return True
        except OSError:
            return False

    def _local_ip_for_server(self):
        parsed = urlparse(str(self.server.ip or ""))
        host = parsed.hostname
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        if not host:
            return None
        try:
            infos = socket.getaddrinfo(host, port, type=socket.SOCK_DGRAM)
            family, _, _, _, sockaddr = infos[0]
            with socket.socket(family, socket.SOCK_DGRAM) as sock:
                sock.connect(sockaddr)
                return sock.getsockname()[0]
        except OSError:
            return None

    @staticmethod
    def _network_signature():
        root = Path("/sys/class/net")
        if not root.is_dir():
            return ()
        result = []
        for item in sorted(root.iterdir(), key=lambda p: p.name):
            if item.name == "lo":
                continue
            try:
                state = (item / "operstate").read_text(encoding="utf-8").strip()
            except OSError:
                continue
            result.append((item.name, state))
        return tuple(result)

    @staticmethod
    def _network_returned(previous, current):
        previous_up = any(state == "up" for _, state in previous or ())
        current_up = any(state == "up" for _, state in current or ())
        return current_up and not previous_up

    def _pending_counts_unlocked(self):
        pending = 0
        errors = 0
        for _, _, record in self._execution_records(pending_only=False):
            status = record.get("sync_status")
            if status == "error":
                errors += 1
            elif status != "synced":
                pending += 1
        return pending, errors

    def _cached_recipe_count_unlocked(self):
        return sum(1 for path in self.recipes_dir.rglob("*.json") if path.is_file())
