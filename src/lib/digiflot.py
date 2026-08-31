import json
import os
import re
import threading
import time
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from threading import Condition, RLock

from picamera2 import Picamera2

from lib.atlasScientific import AtlasScientific
from lib.camera import Camera
from lib.scale import Scale
try:
    from lib.performance import PerformanceManager
except Exception:
    PerformanceManager = None


CURRENT_CONFIG_PATH = Path.cwd() / "config.json"
DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.json"
DEFAULT_LOCAL_STORAGE_DIR = Path(__file__).resolve().parent.parent.parent / "local_storage"


def load_config():
    if CURRENT_CONFIG_PATH.exists():
        path = CURRENT_CONFIG_PATH
    elif DEFAULT_CONFIG_PATH.exists():
        path = DEFAULT_CONFIG_PATH
    else:
        raise FileNotFoundError("config.json not found.")

    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def _atomic_write_json(path: Path, data: dict):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")

    with temporary.open("w", encoding="utf-8") as file:
        json.dump(data, file, indent=4, ensure_ascii=False)
        file.write("\n")
        file.flush()
        os.fsync(file.fileno())

    os.replace(temporary, path)


def _safe_path_name(value: str):
    value = str(value).strip()
    value = re.sub(r"[^A-Za-z0-9._-]+", "_", value)
    return value or "item"


def _utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


class DigiFlot:
    """Runtime controller and experiment orchestrator for one DigiFlot cell."""

    IDLE = "Idle"
    CAMERA_CALIBRATION = "CameraCalibration"
    SENSOR_CALIBRATION = "SensorCalibration"
    READY = "Ready"
    RUNNING = "Running"
    PAUSED = "Paused"
    COMPLETED = "Completed"
    ABORTED = "Aborted"
    ERROR = "Error"
    RECOVERY_REQUIRED = "RecoveryRequired"

    STAGE_NONE = "None"
    STAGE_WAITING = "Waiting"
    STAGE_ACTIVE = "Active"
    STAGE_TRANSITION = "Transition"

    EXECUTION_LOCK_STATES = {RUNNING, PAUSED, RECOVERY_REQUIRED}

    STAGE_POLICIES = {
        "conditioning": {
            "camera": False,
            "sensors": True,
            "scraping": False,
        },
        "flotation": {
            "camera": True,
            "sensors": True,
            "scraping": True,
        },
        "custom": {
            "camera": True,
            "sensors": True,
            "scraping": True,
        },
    }

    def __init__(self, config: dict, local_storage_dir: Path | None = None):
        self.config = config
        self.local_storage_dir = Path(local_storage_dir or DEFAULT_LOCAL_STORAGE_DIR)
        self.output_directory = Path(config.get("output_directory", "./output"))

        orchestration = config.setdefault("orchestration", {})
        self.auto_advance_enabled = bool(
            orchestration.get("auto_advance_enabled", True)
        )
        self.transition_timeout_s = float(
            orchestration.get("transition_timeout_s", 30.0)
        )
        self.scraping_interval_s = float(
            orchestration.get(
                "scraping_interval",
                orchestration.get("scraping_interval_s", 5.0),
            )
        )
        self.scraping_method = str(
            orchestration.get("scraping_method", "audio")
        ).lower()

        self.lock = RLock()
        self.condition = Condition(self.lock)
        self.stop_event = threading.Event()
        self.control_thread = None

        self.cameras = {}
        self.missing_camera_ids = []
        self._load_cameras()

        self.scales = {}
        self.atlas = None
        self._load_sensors()

        # Optional subsystem. Its failure must never prevent DigiFlot startup.
        self.performance = None
        if PerformanceManager is not None:
            try:
                self.performance = PerformanceManager(
                    self.config,
                    self.local_storage_dir,
                )
            except Exception as error:
                print(f"Performance manager unavailable: {error}")

        self.state = self.IDLE
        self.stage_state = self.STAGE_NONE
        self.preview_camera_id = None

        self.storage_id = None
        self.run_directory = None
        self.experiment = None
        self.current_stage_index = None

        self.run_started_at = None
        self.run_started_monotonic = None
        self.stage_started_at = None
        self.stage_started_monotonic = None
        self.stage_deadline = None
        self.transition_started_at = None
        self.transition_started_monotonic = None
        self.transition_deadline = None

        self.pause_started_at = None
        self.pause_started_monotonic = None
        self.paused_stage_state = None

        self.next_scraping_deadline = None
        self.scraping_sequence = 0
        self.last_scraping_at = None

        self.camera_calibration = {}
        self.sensor_calibration = {}
        self.active_camera_segments = {}
        self.camera_segment_count = {}

        self.stage_attempt = 0
        self.recovery_context = None
        self.warnings = []
        self.device_failure_keys = set()

        self.revision = 0
        self.event_sequence = 0
        self.last_error = None

    # ------------------------------------------------------------------
    # Startup / shutdown
    # ------------------------------------------------------------------

    def _load_cameras(self):
        camera_info = Picamera2.global_camera_info()
        info_by_id = {
            int(camera["Num"]): camera
            for camera in camera_info
        }

        configured_ids = []
        for camera_config in self.config.get("cameras", []):
            camera_id = int(camera_config["id"])
            configured_ids.append(camera_id)

            if camera_id not in info_by_id:
                self.missing_camera_ids.append(camera_id)
                print(f"Camera ID {camera_id} not detected. Skipping.")
                continue

            self.cameras[camera_id] = Camera(
                camera_config,
                self.config.get("output", {}),
                hardware_info=info_by_id[camera_id],
            )


    def _load_sensors(self):
        sensor_config = self.config.get("sensors", {})

        scale_configs = sensor_config.get(
            "scales",
            self.config.get("scales", []),
        )
        for scale_config in scale_configs:
            scale = Scale.from_config(scale_config)
            scale.set_context_provider(self.acquisition_context)
            self.scales[scale.id] = scale

        atlas_config = sensor_config.get(
            "atlas_scientific",
            self.config.get("atlas_scientific"),
        )
        if atlas_config:
            self.atlas = AtlasScientific.from_config(atlas_config)
            self.atlas.set_context_provider(self.acquisition_context)

    def start(self):
        for scale in self.scales.values():
            try:
                scale.start()
            except Exception as error:
                scale.error = str(error)

        if self.atlas is not None:
            try:
                self.atlas.start()
            except Exception as error:
                self.atlas.error = str(error)

        self._discover_incomplete_run()

        self.stop_event.clear()
        self.control_thread = threading.Thread(
            target=self._control_loop,
            daemon=True,
            name="digiflot-orchestrator",
        )
        self.control_thread.start()
        return self.status

    def close(self):
        self.stop_event.set()
        with self.condition:
            self.condition.notify_all()

        if self.control_thread is not None:
            self.control_thread.join(timeout=3.0)
        self.control_thread = None

        errors = []
        with self.lock:
            try:
                self._stop_camera_recording_unlocked(ignore_errors=True)
            except Exception as error:
                errors.append(("recording", error))

            try:
                self.stop_preview()
            except Exception as error:
                errors.append(("preview", error))

            try:
                self._stop_sensor_recording_unlocked()
            except Exception as error:
                errors.append(("sensors", error))

        for scale in self.scales.values():
            try:
                scale.stop()
            except Exception as error:
                errors.append((scale.name, error))

        if self.atlas is not None:
            try:
                self.atlas.stop()
            except Exception as error:
                errors.append((self.atlas.name, error))

        if self.performance is not None:
            try:
                self.performance.abort_benchmark()
                benchmark_thread = getattr(self.performance, "benchmark_thread", None)
                if benchmark_thread is not None and benchmark_thread is not threading.current_thread():
                    benchmark_thread.join(timeout=5.0)
                self.performance.stop_experiment_telemetry()
            except Exception as error:
                errors.append(("performance", error))

        for camera in self.cameras.values():
            try:
                camera.close()
            except Exception as error:
                errors.append((camera.name, error))

        if errors:
            raise RuntimeError(
                "Failed to close DigiFlot: "
                + ", ".join(f"{name}: {error}" for name, error in errors)
            )

    # ------------------------------------------------------------------
    # Status / state snapshots
    # ------------------------------------------------------------------

    @property
    def execution_locked(self):
        return self.state in self.EXECUTION_LOCK_STATES

    @property
    def recording(self):
        return any(camera.recording for camera in self.cameras.values())

    @property
    def current_stage(self):
        if self.experiment is None or self.current_stage_index is None:
            return None

        stages = self.experiment.get("stages", [])
        if not 0 <= self.current_stage_index < len(stages):
            return None
        return stages[self.current_stage_index]

    @property
    def next_stage(self):
        if self.experiment is None:
            return None

        stages = self.experiment.get("stages", [])
        if self.current_stage_index is None:
            return stages[0] if stages else None

        index = self.current_stage_index + 1
        return stages[index] if index < len(stages) else None

    @property
    def status(self):
        with self.lock:
            return self._status_unlocked()

    def _status_unlocked(self):
        now = time.monotonic()
        effective_now = (
            self.pause_started_monotonic
            if self.state == self.PAUSED and self.pause_started_monotonic is not None
            else now
        )

        stage_elapsed = None
        stage_remaining = None
        transition_remaining = None
        next_scraping_in = None

        if self.stage_started_monotonic is not None:
            stage_elapsed = max(0.0, effective_now - self.stage_started_monotonic)

        if self.stage_deadline is not None:
            stage_remaining = max(0.0, self.stage_deadline - effective_now)

        if self.transition_deadline is not None:
            transition_remaining = max(0.0, self.transition_deadline - effective_now)

        if self.next_scraping_deadline is not None:
            next_scraping_in = max(0.0, self.next_scraping_deadline - effective_now)

        run_elapsed = None
        if self.run_started_monotonic is not None:
            run_elapsed = max(0.0, now - self.run_started_monotonic)

        return {
            "revision": self.revision,
            "state": self.state,
            "stage_state": self.stage_state,
            "navigation_locked": self.execution_locked,
            "orchestration": {
                "auto_advance_enabled": self.auto_advance_enabled,
                "transition_timeout_s": self.transition_timeout_s,
                "scraping_interval": self.scraping_interval_s,
                "scraping_method": self.scraping_method,
            },
            "storage_id": self.storage_id,
            "run_directory": str(self.run_directory) if self.run_directory else None,
            "experiment": self._experiment_summary_unlocked(),
            "current_stage_index": self.current_stage_index,
            "current_stage": self._stage_view_unlocked(self.current_stage),
            "next_stage": self._stage_view_unlocked(self.next_stage),
            "run_started_at": self.run_started_at,
            "run_elapsed_s": run_elapsed,
            "stage_started_at": self.stage_started_at,
            "stage_elapsed_s": stage_elapsed,
            "stage_remaining_s": stage_remaining,
            "transition_started_at": self.transition_started_at,
            "transition_remaining_s": transition_remaining,
            "pause_started_at": self.pause_started_at,
            "preview_camera_id": self.preview_camera_id,
            "recording": self.recording,
            "cameras": [camera.status for camera in self.cameras.values()],
            "scales": [scale.snapshot() for scale in self.scales.values()],
            "atlas": (
                self.atlas.sensor_snapshots()
                if self.atlas is not None
                else []
            ),
            "calibration": {
                "cameras": deepcopy(self.camera_calibration),
                "sensors": deepcopy(self.sensor_calibration),
            },
            "scraping": {
                "enabled": self._scraping_required(self.current_stage),
                "interval_s": self._scraping_interval(self.current_stage),
                "method": self.scraping_method,
                "sequence": self.scraping_sequence,
                "last_at": self.last_scraping_at,
                "next_in_s": next_scraping_in,
            },
            "stage_attempt": self.stage_attempt,
            "recovery": deepcopy(self.recovery_context),
            "warnings": deepcopy(self.warnings[-50:]),
            "devices": self._device_status_unlocked(),
            "performance": self._performance_summary_unlocked(),
            "last_error": self.last_error,
        }

    def _experiment_summary_unlocked(self):
        if self.experiment is None:
            return None
        return {
            "id": self.experiment.get("id"),
            "name": self.experiment.get("name"),
            "state": self.experiment.get("state"),
            "source": self.experiment.get("source"),
            "stages": len(self.experiment.get("stages", [])),
        }

    def _stage_view_unlocked(self, stage):
        if stage is None:
            return None

        result = deepcopy(stage)
        reagent_id = stage.get("reagent_id")
        if reagent_id is not None and self.experiment is not None:
            for reagent in self.experiment.get("reagents", []):
                if reagent.get("reagent_id") == reagent_id:
                    result["reagent"] = deepcopy(reagent)
                    break
        result["policy"] = self.stage_policy(stage)
        return result


    def _device_status_unlocked(self):
        cameras = []
        configured = {int(item["id"]): item for item in self.config.get("cameras", [])}
        for camera_id, camera_config in configured.items():
            camera = self.cameras.get(camera_id)
            if camera is None:
                cameras.append({
                    "id": camera_id,
                    "name": camera_config.get("name", f"Camera {camera_id}"),
                    "type": "camera",
                    "status": "offline",
                    "state": "Offline",
                    "error": "Camera not detected.",
                })
            else:
                status = camera.status
                cameras.append({
                    **status,
                    "type": "camera",
                    "status": "connected",
                    "error": None,
                })

        scales = []
        for scale in self.scales.values():
            snapshot = scale.snapshot()
            scales.append({**snapshot, "type": "scale"})

        atlas = []
        if self.atlas is not None:
            atlas = self.atlas.sensor_snapshots()

        return {
            "cameras": cameras,
            "scales": scales,
            "atlas": atlas,
        }

    def _performance_summary_unlocked(self):
        if self.performance is None:
            return {
                "status": "UNAVAILABLE",
                "reason": "Performance module is unavailable.",
            }
        try:
            evaluation = self.performance.evaluate(self)
            system = deepcopy(self.performance.last_sample)
            return {
                **evaluation,
                "system": system,
                "profile": deepcopy(self.performance.profile),
            }
        except Exception as error:
            return {
                "status": "UNAVAILABLE",
                "reason": str(error),
            }

    def _add_warning_unlocked(self, source: str, message: str, data=None):
        warning = {
            "id": f"{time.time_ns()}",
            "timestamp": _utc_now(),
            "source": str(source),
            "message": str(message),
            "data": deepcopy(data or {}),
        }
        self.warnings.append(warning)
        if len(self.warnings) > 100:
            del self.warnings[:-100]
        if self.run_directory is not None:
            self._append_event_unlocked(
                "WARNING",
                {"source": source, "message": message, **(data or {})},
            )
            self._write_runtime_unlocked()
        self.revision += 1
        self.condition.notify_all()
        return warning

    def _add_warning_once_unlocked(self, key, source, message, data=None):
        key = str(key)
        if key in self.device_failure_keys:
            return None
        self.device_failure_keys.add(key)
        return self._add_warning_unlocked(source, message, data)

    def wait_for_update(self, last_revision, timeout=1.0):
        with self.condition:
            self.condition.wait_for(
                lambda: self.revision != last_revision or self.stop_event.is_set(),
                timeout=timeout,
            )
            return self._status_unlocked()

    def _touch_unlocked(self, event_type=None, data=None, persist=True):
        self.revision += 1

        if self.run_directory is not None:
            if event_type is not None:
                self._append_event_unlocked(event_type, data or {})
            if persist:
                self._write_runtime_unlocked()

        self.condition.notify_all()

    # ------------------------------------------------------------------
    # Experiment storage / persistence
    # ------------------------------------------------------------------

    def _validate_storage_id(self, storage_id: str):
        if not storage_id or Path(storage_id).name != storage_id:
            raise KeyError("Local experiment not found.")

        directory = self.local_storage_dir / storage_id
        if not directory.is_dir():
            raise KeyError("Local experiment not found.")
        return directory

    @staticmethod
    def _read_json(path: Path):
        with Path(path).open("r", encoding="utf-8") as file:
            return json.load(file)

    def _write_runtime_unlocked(self):
        if self.run_directory is None:
            return

        runtime = self._status_unlocked()
        runtime["saved_at"] = _utc_now()
        _atomic_write_json(self.run_directory / "runtime.json", runtime)

    def _write_config_snapshot_unlocked(self):
        if self.run_directory is None:
            return

        snapshot = deepcopy(self.config)
        server = snapshot.get("server")
        if isinstance(server, dict):
            server.pop("token", None)

        _atomic_write_json(
            self.run_directory / "config_snapshot.json",
            snapshot,
        )

    def _append_event_unlocked(self, event_type: str, data: dict):
        if self.run_directory is None:
            return

        self.event_sequence += 1
        current = self.current_stage
        next_stage = self.next_stage
        event = {
            "sequence": self.event_sequence,
            "event": event_type,
            "timestamp": _utc_now(),
            "timestamp_ns": time.time_ns(),
            "monotonic_ns": time.monotonic_ns(),
            "run_elapsed_s": self._run_elapsed_unlocked(),
            "state": self.state,
            "stage_state": self.stage_state,
            "stage_id": current.get("id") if current else None,
            "stage_name": current.get("name") if current else None,
            "stage_type": current.get("type") if current else None,
            "stage_attempt": self.stage_attempt,
            "next_stage_id": next_stage.get("id") if next_stage else None,
            "data": data,
        }

        path = self.run_directory / "events.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(event, ensure_ascii=False) + "\n")
            file.flush()
            os.fsync(file.fileno())

    def _run_elapsed_unlocked(self):
        if self.run_started_monotonic is None:
            return None
        return max(0.0, time.monotonic() - self.run_started_monotonic)

    def _discover_incomplete_run(self):
        self.local_storage_dir.mkdir(parents=True, exist_ok=True)
        candidates = []
        terminal = {self.IDLE, self.COMPLETED, self.ABORTED, self.ERROR}

        for directory in self.local_storage_dir.iterdir():
            if not directory.is_dir():
                continue
            runtime_path = directory / "runtime.json"
            experiment_path = directory / "experiment.json"
            if not runtime_path.is_file() or not experiment_path.is_file():
                continue
            try:
                runtime = self._read_json(runtime_path)
            except Exception:
                continue
            if runtime.get("state") in terminal:
                continue
            candidates.append((runtime_path.stat().st_mtime, directory, runtime))

        if not candidates:
            return

        _, directory, runtime = max(candidates, key=lambda item: item[0])
        try:
            experiment = self._read_json(directory / "experiment.json")
        except Exception:
            return

        with self.lock:
            self._load_existing_runtime_unlocked(directory, experiment, runtime)

    def _restore_event_sequence_unlocked(self):
        self.event_sequence = 0
        if self.run_directory is None:
            return
        path = self.run_directory / "events.jsonl"
        if not path.is_file():
            return
        try:
            with path.open("r", encoding="utf-8") as file:
                for line in file:
                    if line.strip():
                        self.event_sequence += 1
        except Exception:
            self.event_sequence = 0

    # ------------------------------------------------------------------
    # Experiment workflow
    # ------------------------------------------------------------------

    def select_experiment(self, storage_id: str):
        with self.lock:
            if self.storage_id == storage_id and self.state != self.IDLE:
                return self.status

            if self.state not in {self.IDLE, self.COMPLETED, self.ABORTED, self.ERROR}:
                raise RuntimeError(
                    f"Another experiment is already active ({self.storage_id})."
                )

            self._reset_run_state_unlocked()
            directory = self._validate_storage_id(storage_id)
            experiment = self._read_json(directory / "experiment.json")
            self._validate_experiment_unlocked(experiment)

            runtime_path = directory / "runtime.json"
            if runtime_path.is_file():
                try:
                    runtime = self._read_json(runtime_path)
                except Exception:
                    runtime = None

                if runtime is not None:
                    self._load_existing_runtime_unlocked(
                        directory,
                        experiment,
                        runtime,
                    )
                    return self.status

            self.storage_id = storage_id
            self.run_directory = directory
            self.experiment = experiment
            self.state = self.CAMERA_CALIBRATION
            self.stage_state = self.STAGE_NONE
            self._initialise_calibration_state_unlocked()
            self._write_config_snapshot_unlocked()
            self._touch_unlocked(
                "EXPERIMENT_SELECTED",
                {
                    "experiment_id": experiment.get("id"),
                    "experiment_name": experiment.get("name"),
                },
            )
            self._advance_from_camera_calibration_unlocked()
            return self.status

    def _load_existing_runtime_unlocked(self, directory, experiment, runtime):
        previous_state = runtime.get("state")
        self.storage_id = directory.name
        self.run_directory = directory
        self.experiment = experiment
        self.current_stage_index = runtime.get("current_stage_index")
        self.stage_state = runtime.get("stage_state", self.STAGE_NONE)
        self.run_started_at = runtime.get("run_started_at")
        saved_run_elapsed = runtime.get("run_elapsed_s")
        if saved_run_elapsed is not None:
            self.run_started_monotonic = time.monotonic() - max(0.0, float(saved_run_elapsed))
        self.stage_started_at = runtime.get("stage_started_at")
        self.transition_started_at = runtime.get("transition_started_at")
        self.pause_started_at = runtime.get("pause_started_at")
        self.scraping_sequence = int(
            (runtime.get("scraping") or {}).get("sequence", 0) or 0
        )
        self.last_scraping_at = (runtime.get("scraping") or {}).get("last_at")
        self.last_error = runtime.get("last_error")
        self.stage_attempt = int(runtime.get("stage_attempt", 0) or 0)
        self._initialise_calibration_state_unlocked()

        saved_calibration = runtime.get("calibration") or {}
        if isinstance(saved_calibration.get("cameras"), dict):
            self.camera_calibration.update(saved_calibration["cameras"])
        if isinstance(saved_calibration.get("sensors"), dict):
            self.sensor_calibration.update(saved_calibration["sensors"])

        self._restore_event_sequence_unlocked()

        if previous_state == self.COMPLETED:
            self.state = self.COMPLETED
            self.stage_state = self.STAGE_NONE
        elif previous_state == self.ABORTED:
            self.state = self.ABORTED
            self.stage_state = self.STAGE_NONE
        elif previous_state == self.ERROR:
            self.state = self.ERROR
            self.stage_state = self.STAGE_NONE
        elif previous_state in {
            self.CAMERA_CALIBRATION,
            self.SENSOR_CALIBRATION,
            self.READY,
        }:
            # No timed acquisition is active in these phases, so a process
            # restart can safely restore the workflow instead of forcing a
            # recovery screen that has no stage to resume.
            self.state = previous_state
            self.last_error = None
            self.recovery_context = None
            self.revision += 1
            self.condition.notify_all()
            if self.state == self.CAMERA_CALIBRATION:
                self._advance_from_camera_calibration_unlocked()
            return
        else:
            self.state = self.RECOVERY_REQUIRED
            self.last_error = (
                "This execution was active in an earlier DigiFlot process. "
                "Choose a recovery action before continuing."
            )
            self.stage_attempt = max(1, self.stage_attempt)
            self.recovery_context = {
                "source": "process_restart",
                "reason": self.last_error,
                "previous_state": previous_state,
                "previous_stage_state": runtime.get("stage_state"),
                "stage_elapsed_s": runtime.get("stage_elapsed_s"),
                "stage_remaining_s": runtime.get("stage_remaining_s"),
                "transition_remaining_s": runtime.get("transition_remaining_s"),
                "stage_attempt": self.stage_attempt,
                "entered_at": _utc_now(),
            }
            self._touch_unlocked(
                "RECOVERY_REQUIRED",
                {"previous_state": previous_state, "source": "process_restart"},
            )
            return

        self.revision += 1
        self.condition.notify_all()

    def _validate_experiment_unlocked(self, experiment: dict):
        stages = experiment.get("stages")
        if not isinstance(stages, list) or not stages:
            raise ValueError("Experiment must contain at least one stage.")

        for index, stage in enumerate(stages):
            stage_type = str(stage.get("type", "")).strip().lower()
            if stage_type not in self.STAGE_POLICIES:
                raise ValueError(
                    f"Stage {index + 1} has unsupported type '{stage.get('type')}'."
                )
            try:
                duration = float(stage.get("duration"))
            except (TypeError, ValueError):
                raise ValueError(f"Stage {index + 1} has an invalid duration.")
            if duration <= 0:
                raise ValueError(f"Stage {index + 1} duration must be positive.")


    def _reset_run_state_unlocked(self):
        self.stop_preview()
        self._stop_camera_recording_unlocked(ignore_errors=True)
        self._stop_sensor_recording_unlocked()

        self.storage_id = None
        self.run_directory = None
        self.experiment = None
        self.current_stage_index = None
        self.stage_state = self.STAGE_NONE
        self.run_started_at = None
        self.run_started_monotonic = None
        self.stage_started_at = None
        self.stage_started_monotonic = None
        self.stage_deadline = None
        self.transition_started_at = None
        self.transition_started_monotonic = None
        self.transition_deadline = None
        self.pause_started_at = None
        self.pause_started_monotonic = None
        self.paused_stage_state = None
        self.next_scraping_deadline = None
        self.scraping_sequence = 0
        self.last_scraping_at = None
        self.camera_calibration = {}
        self.sensor_calibration = {}
        self.active_camera_segments = {}
        self.camera_segment_count = {}
        self.stage_attempt = 0
        self.recovery_context = None
        self.warnings = []
        self.device_failure_keys = set()
        self.event_sequence = 0
        self.last_error = None
        self.state = self.IDLE

    def _initialise_calibration_state_unlocked(self):
        camera_calibration = {}
        for camera_config in self.config.get("cameras", []):
            camera_id = int(camera_config["id"])
            camera = self.cameras.get(camera_id)
            camera_calibration[str(camera_id)] = {
                "id": camera_id,
                "name": (camera.name if camera is not None else camera_config.get("name", f"Camera {camera_id}")),
                "status": "pending" if camera is not None else "offline",
                "exposure": deepcopy(camera.exposure) if camera is not None else None,
                "confirmed_at": None,
                "available": camera is not None,
                "error": None if camera is not None else "Camera not detected.",
            }

        self.camera_calibration = camera_calibration

        sensor_calibration = {}
        for scale in self.scales.values():
            sensor_calibration[str(scale.id)] = {
                "id": scale.id,
                "name": scale.name,
                "type": "scale",
                "mode": "manual_tare",
                "status": "pending",
                "confirmed_at": None,
            }

        if self.atlas is not None:
            for sensor in self.atlas.sensors:
                sensor_id = self.atlas.sensor_id(sensor)
                sensor_type = sensor.get("type", "sensor")
                is_ph = str(sensor_type).lower() == "ph"
                sensor_calibration[sensor_id] = {
                    "id": sensor_id,
                    "name": sensor.get("name", sensor_type),
                    "type": sensor_type,
                    "mode": "two_point" if is_ph else "manual_check",
                    "status": "pending",
                    "confirmed_at": None,
                    "software_calibration_available": is_ph,
                    "points": (
                        {
                            "mid": {
                                "value": 7.0,
                                "status": "pending",
                                "calibrated_at": None,
                            },
                            "low": {
                                "value": 4.0,
                                "status": "pending",
                                "calibrated_at": None,
                            },
                        }
                        if is_ph else None
                    ),
                }

        self.sensor_calibration = sensor_calibration

    def _advance_from_camera_calibration_unlocked(self):
        """Advance once every configured camera is resolved.

        An empty camera configuration is valid: DigiFlot can run without
        cameras, so the workflow must not get stuck in CameraCalibration.
        Offline configured cameras remain visible until the operator skips
        them or retries the device.
        """
        if self.state != self.CAMERA_CALIBRATION:
            return

        if self.camera_calibration and not all(
            value.get("status") in {"passed", "skipped"}
            for value in self.camera_calibration.values()
        ):
            return

        self._touch_unlocked("CAMERA_CALIBRATION_COMPLETED")
        if self.sensor_calibration:
            self.state = self.SENSOR_CALIBRATION
            self._touch_unlocked("SENSOR_CALIBRATION_STARTED")
        else:
            self.state = self.READY
            self.stage_state = self.STAGE_WAITING
            self._touch_unlocked("SENSOR_CALIBRATION_COMPLETED")

    def start_camera_calibration(self, camera_id: int):
        with self.lock:
            if self.state != self.CAMERA_CALIBRATION:
                raise RuntimeError("Camera calibration is not active.")

            camera = self.get_camera(camera_id)
            item = self.camera_calibration[str(camera.id)]
            item["status"] = "calibrating"
            self._touch_unlocked("CAMERA_CALIBRATION_STARTED", {"camera_id": camera.id})

            try:
                self.start_preview(camera.id)
                exposure = self.calibrate_exposure(camera.id)
            except Exception as error:
                item["status"] = "error"
                item["error"] = str(error)
                self._touch_unlocked(
                    "CAMERA_CALIBRATION_FAILED",
                    {"camera_id": camera.id, "error": str(error)},
                )
                raise

            item["status"] = "calibrating"
            item["exposure"] = deepcopy(exposure)
            item.pop("error", None)
            self._write_config_snapshot_unlocked()
            self._touch_unlocked(
                "CAMERA_EXPOSURE_CALIBRATED",
                {"camera_id": camera.id, **exposure},
            )
            return self.status

    def confirm_camera_calibration(self, camera_id: int):
        with self.lock:
            if self.state != self.CAMERA_CALIBRATION:
                raise RuntimeError("Camera calibration is not active.")

            camera = self.get_camera(camera_id)
            if self.preview_camera_id == camera.id:
                self.stop_preview()

            if camera.exposure_time_us is None or camera.analogue_gain is None:
                raise RuntimeError(f"{camera.name} exposure has not been calibrated.")

            item = self.camera_calibration[str(camera.id)]
            item["status"] = "passed"
            item["exposure"] = deepcopy(camera.exposure)
            item["confirmed_at"] = _utc_now()
            self.save_config()
            self._write_config_snapshot_unlocked()
            self._touch_unlocked("CAMERA_CALIBRATION_CONFIRMED", {"camera_id": camera.id})

            self._advance_from_camera_calibration_unlocked()

            return self.status

    def skip_camera_calibration(self, camera_id: int, reason: str = "Operator skipped calibration"):
        with self.lock:
            if self.state != self.CAMERA_CALIBRATION:
                raise RuntimeError("Camera calibration is not active.")

            key = str(int(camera_id))
            if key not in self.camera_calibration:
                raise KeyError(f"Camera '{camera_id}' is not configured.")

            if self.preview_camera_id == int(camera_id):
                try:
                    self.stop_preview()
                except Exception:
                    pass

            item = self.camera_calibration[key]
            item["status"] = "skipped"
            item["confirmed_at"] = _utc_now()
            item["skip_reason"] = str(reason or "Operator skipped calibration")
            self._touch_unlocked(
                "CAMERA_CALIBRATION_SKIPPED",
                {"camera_id": int(camera_id), "reason": item["skip_reason"]},
            )

            self._advance_from_camera_calibration_unlocked()

            return self.status

    def confirm_sensor_calibration(self, sensor_id: str):
        """Confirm a manual sensor check or explicitly skip an offline sensor."""
        with self.lock:
            if self.state != self.SENSOR_CALIBRATION:
                raise RuntimeError("Sensor calibration is not active.")

            sensor_id = str(sensor_id)
            if sensor_id not in self.sensor_calibration:
                raise KeyError(f"Sensor '{sensor_id}' is not part of this calibration.")

            item = self.sensor_calibration[sensor_id]
            sensor_status = self._sensor_status_unlocked(sensor_id)
            connection = sensor_status.get("status")

            if connection != "connected":
                item["status"] = "skipped"
                item["confirmed_at"] = _utc_now()
                item["skip_reason"] = sensor_status.get("error") or connection or "offline"
                self._touch_unlocked(
                    "SENSOR_CALIBRATION_SKIPPED",
                    {
                        "sensor_id": sensor_id,
                        "reason": item["skip_reason"],
                    },
                )
                return self.status

            if item.get("mode") == "two_point":
                points = item.get("points") or {}
                missing = [
                    name
                    for name in ("mid", "low")
                    if points.get(name, {}).get("status") != "passed"
                ]
                if missing:
                    raise RuntimeError(
                        "Complete the pH two-point calibration before confirming this sensor."
                    )

            item["status"] = "passed"
            item["confirmed_at"] = _utc_now()
            item.pop("skip_reason", None)
            self._touch_unlocked(
                "SENSOR_CALIBRATION_CONFIRMED",
                {"sensor_id": sensor_id},
            )
            return self.status

    def skip_sensor_calibration(self, sensor_id: str, reason: str = "Operator skipped calibration"):
        """Explicitly skip calibration for one sensor without blocking the run."""
        with self.lock:
            if self.state != self.SENSOR_CALIBRATION:
                raise RuntimeError("Sensor calibration is not active.")

            sensor_id = str(sensor_id)
            if sensor_id not in self.sensor_calibration:
                raise KeyError(f"Sensor '{sensor_id}' is not part of this calibration.")

            item = self.sensor_calibration[sensor_id]
            item["status"] = "skipped"
            item["confirmed_at"] = _utc_now()
            item["skip_reason"] = str(reason or "Operator skipped calibration")
            item.pop("error", None)

            self._touch_unlocked(
                "SENSOR_CALIBRATION_SKIPPED",
                {
                    "sensor_id": sensor_id,
                    "reason": item["skip_reason"],
                    "operator": True,
                },
            )
            return self.status

    def complete_sensor_calibration(self):
        """Finish the calibration phase when every connected sensor is resolved."""
        with self.lock:
            if self.state != self.SENSOR_CALIBRATION:
                raise RuntimeError("Sensor calibration is not active.")

            incomplete = []
            for sensor_id, item in self.sensor_calibration.items():
                snapshot = self._sensor_status_unlocked(sensor_id)
                if snapshot.get("status") == "connected":
                    if item.get("status") not in {"passed", "skipped"}:
                        incomplete.append(item.get("name", sensor_id))
                elif item.get("status") not in {"passed", "skipped"}:
                    item["status"] = "skipped"
                    item["confirmed_at"] = _utc_now()
                    item["skip_reason"] = snapshot.get("error") or snapshot.get("status") or "offline"
                    self._append_event_unlocked(
                        "SENSOR_CALIBRATION_SKIPPED",
                        {
                            "sensor_id": sensor_id,
                            "reason": item["skip_reason"],
                        },
                    )

            if incomplete:
                raise RuntimeError(
                    "Calibration is still required for: " + ", ".join(incomplete)
                )

            self.state = self.READY
            self.stage_state = self.STAGE_WAITING
            self._write_config_snapshot_unlocked()
            self._touch_unlocked("SENSOR_CALIBRATION_COMPLETED")
            return self.status

    def _sensor_status_unlocked(self, sensor_id: str):
        sensor_id = str(sensor_id)
        if sensor_id in self.scales:
            return self.scales[sensor_id].snapshot()

        if self.atlas is not None:
            try:
                return self.atlas.snapshot(sensor_id)
            except KeyError:
                pass

        raise KeyError(f"Sensor '{sensor_id}' not found.")

    def start_sensor_calibration(self, sensor_id: str, **kwargs):
        """Run one software calibration step for sensors that support it."""
        sensor_id = str(sensor_id)

        with self.lock:
            if self.state != self.SENSOR_CALIBRATION:
                raise RuntimeError("Sensor calibration is not active.")
            if sensor_id not in self.sensor_calibration:
                raise KeyError(f"Sensor '{sensor_id}' not found.")

            item = self.sensor_calibration[sensor_id]
            if item.get("mode") != "two_point":
                raise RuntimeError("This sensor does not use software point calibration.")

            snapshot = self._sensor_status_unlocked(sensor_id)
            if snapshot.get("status") != "connected":
                detail = snapshot.get("error") or snapshot.get("status") or "offline"
                raise RuntimeError(f"Sensor '{sensor_id}' is offline: {detail}")

            point = str(kwargs.get("point", "")).strip().lower()
            if point not in {"mid", "low"}:
                raise ValueError("Two-point pH calibration requires point 'mid' or 'low'.")

            points = item.get("points") or {}
            if point == "low" and points.get("mid", {}).get("status") != "passed":
                raise RuntimeError("Calibrate the pH midpoint before the low point.")

            try:
                value = float(kwargs.get("value", points.get(point, {}).get("value")))
            except (TypeError, ValueError) as error:
                raise ValueError("Calibration buffer value must be numeric.") from error

            item["status"] = "calibrating"
            points[point]["status"] = "calibrating"
            points[point]["value"] = value
            self._touch_unlocked(
                "SENSOR_CALIBRATION_STARTED",
                {
                    "sensor_id": sensor_id,
                    "point": point,
                    "value": value,
                },
            )

        try:
            if self.atlas is None:
                raise RuntimeError("Atlas Scientific interface is not configured.")
            result = self.atlas.calibrate_ph(sensor_id, point, value)
        except Exception as error:
            with self.lock:
                item = self.sensor_calibration[sensor_id]
                item["status"] = "error"
                item["error"] = str(error)
                point_item = (item.get("points") or {}).get(point)
                if point_item is not None:
                    point_item["status"] = "error"
                    point_item["error"] = str(error)
                self._touch_unlocked(
                    "SENSOR_CALIBRATION_FAILED",
                    {
                        "sensor_id": sensor_id,
                        "point": point,
                        "error": str(error),
                    },
                )
            raise

        with self.lock:
            item = self.sensor_calibration[sensor_id]
            point_item = item["points"][point]
            point_item["status"] = "passed"
            point_item["calibrated_at"] = _utc_now()
            point_item.pop("error", None)
            item.pop("error", None)

            complete = all(
                item["points"][name].get("status") == "passed"
                for name in ("mid", "low")
            )
            item["status"] = "passed" if complete else "calibrating"
            if complete:
                item["confirmed_at"] = _utc_now()

            self._touch_unlocked(
                "SENSOR_CALIBRATION_POINT_COMPLETED",
                {
                    "sensor_id": sensor_id,
                    **result,
                },
            )
            return self.status

    # ------------------------------------------------------------------
    # Stage orchestration
    # ------------------------------------------------------------------

    def start_next_stage(self):
        with self.lock:
            if self.state == self.READY:
                if self.current_stage_index is not None:
                    raise RuntimeError("The first stage has already been started.")

                now = time.monotonic()
                self.run_started_monotonic = now
                self.run_started_at = _utc_now()
                self.state = self.RUNNING
                self.current_stage_index = 0
                self.stage_attempt = 1
                self._touch_unlocked("EXPERIMENT_STARTED")

                try:
                    self._start_sensor_recording_unlocked()
                    self._start_performance_telemetry_unlocked()
                    self._start_stage_unlocked(self.current_stage, new_attempt=False)
                except Exception as error:
                    self._enter_recovery_unlocked(error, source="experiment_start")
                    raise

                return self.status

            if self.state == self.PAUSED:
                if self.paused_stage_state != self.STAGE_TRANSITION:
                    raise RuntimeError("Resume the active stage before continuing.")
                self.resume()

            if self.state != self.RUNNING or self.stage_state != self.STAGE_TRANSITION:
                raise RuntimeError("The experiment is not waiting for the next stage.")

            next_stage = self.next_stage
            if next_stage is None:
                self._finish_experiment_unlocked()
                return self.status

            self.current_stage_index += 1
            self.stage_attempt = 1
            self._start_stage_unlocked(self.current_stage, new_attempt=False)
            return self.status

    def _start_stage_unlocked(self, stage: dict, new_attempt=False):
        if new_attempt:
            self.stage_attempt = max(1, self.stage_attempt + 1)
        elif self.stage_attempt < 1:
            self.stage_attempt = 1

        now = time.monotonic()
        duration = float(stage["duration"])

        self.stage_state = self.STAGE_ACTIVE
        self.stage_started_monotonic = now
        self.stage_started_at = _utc_now()
        self.stage_deadline = now + duration
        self.transition_started_monotonic = None
        self.transition_started_at = None
        self.transition_deadline = None
        self.pause_started_monotonic = None
        self.pause_started_at = None
        self.paused_stage_state = None

        try:
            self.apply_stage_setpoints(stage)
        except Exception as error:
            self._add_warning_unlocked(
                "process_hardware",
                f"Could not apply stage setpoints: {error}",
                {"stage_id": stage.get("id")},
            )

        if self._camera_required(stage):
            if not self.recording:
                self._start_camera_recording_unlocked(stage)
        elif self.recording:
            self._stop_camera_recording_unlocked(ignore_errors=True)

        if self._scraping_required(stage):
            self.next_scraping_deadline = now + self._scraping_interval(stage)
        else:
            self.next_scraping_deadline = None

        self._touch_unlocked(
            "STAGE_STARTED",
            {
                "stage": deepcopy(stage),
                "duration_s": duration,
                "attempt": self.stage_attempt,
            },
        )

    def _complete_stage_unlocked(self, early=False, skipped=False, reason=None):
        stage = self.current_stage
        next_stage = self.next_stage
        if stage is None:
            return

        elapsed = None
        if self.stage_started_monotonic is not None:
            elapsed = max(0.0, time.monotonic() - self.stage_started_monotonic)

        if skipped:
            event_type = "STAGE_SKIPPED"
        elif early:
            event_type = "STAGE_FINISHED_EARLY"
        else:
            event_type = "STAGE_COMPLETED"

        self._append_event_unlocked(
            event_type,
            {
                "stage": deepcopy(stage),
                "attempt": self.stage_attempt,
                "planned_duration_s": float(stage.get("duration", 0) or 0),
                "elapsed_s": elapsed,
                "reason": reason,
            },
        )
        self.next_scraping_deadline = None
        self.stage_deadline = None

        if next_stage is None:
            self._finish_experiment_unlocked()
            return

        keep_camera = (
            self._camera_required(stage)
            and self._camera_required(next_stage)
        )
        if self.recording and not keep_camera:
            self._stop_camera_recording_unlocked(ignore_errors=True)

        now = time.monotonic()
        self.stage_state = self.STAGE_TRANSITION
        self.transition_started_monotonic = now
        self.transition_started_at = _utc_now()
        self.transition_deadline = (
            now + self.transition_timeout_s
            if self.auto_advance_enabled
            else None
        )
        self._touch_unlocked(
            "TRANSITION_STARTED",
            {
                "from_stage_id": stage.get("id"),
                "to_stage_id": next_stage.get("id"),
                "timeout_s": (self.transition_timeout_s if self.auto_advance_enabled else None),
                "automatic_advance": self.auto_advance_enabled,
                "camera_continues": keep_camera,
                "previous_stage_skipped": skipped,
                "previous_stage_finished_early": early,
            },
        )

    def finish_stage_now(self, reason="Operator finished stage early"):
        with self.lock:
            if self.state == self.PAUSED and self.paused_stage_state == self.STAGE_ACTIVE:
                self.resume()
            if self.state != self.RUNNING or self.stage_state != self.STAGE_ACTIVE:
                raise RuntimeError("There is no active stage to finish.")
            self._complete_stage_unlocked(early=True, reason=str(reason))
            return self.status

    def skip_current_stage(self, reason="Operator skipped stage"):
        with self.lock:
            if self.state == self.PAUSED and self.paused_stage_state == self.STAGE_ACTIVE:
                self.resume()
            if self.state not in {self.RUNNING, self.RECOVERY_REQUIRED}:
                raise RuntimeError("There is no current stage to skip.")
            if self.current_stage is None:
                raise RuntimeError("There is no current stage to skip.")

            if self.state == self.RECOVERY_REQUIRED:
                recovery_stage_state = (self.recovery_context or {}).get("previous_stage_state")
                self._start_sensor_recording_unlocked()
                self._start_performance_telemetry_unlocked()
                self.state = self.RUNNING

                if recovery_stage_state == self.STAGE_TRANSITION:
                    upcoming = self.next_stage
                    if upcoming is None:
                        self._finish_experiment_unlocked()
                        return self.status
                    self.current_stage_index += 1
                    self.stage_attempt = 1
                    self.stage_state = self.STAGE_ACTIVE
                    self.stage_started_monotonic = time.monotonic()
                    self.stage_started_at = _utc_now()
                    self._complete_stage_unlocked(skipped=True, reason=str(reason))
                    return self.status

                self.stage_state = self.STAGE_ACTIVE

            self._complete_stage_unlocked(skipped=True, reason=str(reason))
            return self.status

    def pause(self):
        with self.lock:
            if self.state != self.RUNNING:
                raise RuntimeError("Only a running experiment can be paused.")
            if self.stage_state not in {self.STAGE_ACTIVE, self.STAGE_TRANSITION}:
                raise RuntimeError("There is no active stage or transition to pause.")

            self.paused_stage_state = self.stage_state
            self.pause_started_monotonic = time.monotonic()
            self.pause_started_at = _utc_now()
            self.state = self.PAUSED
            self._touch_unlocked(
                "EXPERIMENT_PAUSED",
                {"paused_stage_state": self.paused_stage_state},
            )
            return self.status

    def resume(self):
        with self.lock:
            if self.state != self.PAUSED or self.pause_started_monotonic is None:
                raise RuntimeError("The experiment is not paused.")

            now = time.monotonic()
            pause_duration = now - self.pause_started_monotonic

            if self.paused_stage_state == self.STAGE_ACTIVE:
                if self.stage_started_monotonic is not None:
                    self.stage_started_monotonic += pause_duration
                if self.stage_deadline is not None:
                    self.stage_deadline += pause_duration
                if self.next_scraping_deadline is not None:
                    self.next_scraping_deadline += pause_duration
            elif self.paused_stage_state == self.STAGE_TRANSITION:
                if self.transition_started_monotonic is not None:
                    self.transition_started_monotonic += pause_duration
                if self.transition_deadline is not None:
                    self.transition_deadline += pause_duration

            self.state = self.RUNNING
            self.stage_state = self.paused_stage_state or self.stage_state
            self.pause_started_monotonic = None
            self.pause_started_at = None
            self.paused_stage_state = None
            self._touch_unlocked(
                "EXPERIMENT_RESUMED",
                {"pause_duration_s": pause_duration},
            )
            return self.status

    def _finish_experiment_unlocked(self):
        self.next_scraping_deadline = None
        self.stage_deadline = None
        self.transition_deadline = None
        self._stop_camera_recording_unlocked(ignore_errors=True)
        self._stop_sensor_recording_unlocked()
        self._stop_performance_telemetry_unlocked()
        self.stage_state = self.STAGE_NONE
        self.state = self.COMPLETED
        self.recovery_context = None
        self._touch_unlocked("EXPERIMENT_COMPLETED")

    def abort_experiment(self, reason="Operator aborted experiment"):
        with self.lock:
            if self.state == self.IDLE:
                return self.status

            self.next_scraping_deadline = None
            self.stage_deadline = None
            self.transition_deadline = None
            self._stop_camera_recording_unlocked(ignore_errors=True)
            self._stop_sensor_recording_unlocked()
            self._stop_performance_telemetry_unlocked()
            try:
                self.stop_preview()
            except Exception:
                pass
            self.stage_state = self.STAGE_NONE
            self.state = self.ABORTED
            self.last_error = str(reason)
            self.recovery_context = None
            self._touch_unlocked("EXPERIMENT_ABORTED", {"reason": str(reason)})
            return self.status

    def _enter_recovery_unlocked(self, error, source="orchestrator"):
        previous_state = self.state
        previous_stage_state = self.stage_state
        snapshot = self._status_unlocked()
        self.last_error = str(error)
        self.recovery_context = {
            "source": source,
            "reason": str(error),
            "previous_state": previous_state,
            "previous_stage_state": previous_stage_state,
            "stage_elapsed_s": snapshot.get("stage_elapsed_s"),
            "stage_remaining_s": snapshot.get("stage_remaining_s"),
            "transition_remaining_s": snapshot.get("transition_remaining_s"),
            "stage_attempt": self.stage_attempt,
            "entered_at": _utc_now(),
        }
        try:
            self._stop_camera_recording_unlocked(ignore_errors=True)
        except Exception:
            pass
        try:
            self._stop_sensor_recording_unlocked()
        except Exception:
            pass
        self._stop_performance_telemetry_unlocked()
        self.state = self.RECOVERY_REQUIRED
        self.stage_state = previous_stage_state
        self._touch_unlocked(
            "RECOVERY_REQUIRED",
            deepcopy(self.recovery_context),
        )

    def retry_devices(self):
        """Retry unavailable devices without changing experiment progression."""
        with self.lock:
            results = {"cameras": [], "scales": [], "atlas": None}

            try:
                info_by_id = {
                    int(item["Num"]): item
                    for item in Picamera2.global_camera_info()
                }
                for camera_config in self.config.get("cameras", []):
                    camera_id = int(camera_config["id"])
                    if camera_id in self.cameras:
                        results["cameras"].append({"id": camera_id, "status": "connected"})
                        continue
                    if camera_id not in info_by_id:
                        results["cameras"].append({"id": camera_id, "status": "offline"})
                        continue
                    try:
                        camera = Camera(
                            camera_config,
                            self.config.get("output", {}),
                            hardware_info=info_by_id[camera_id],
                        )
                        self.cameras[camera_id] = camera
                        if camera_id in self.missing_camera_ids:
                            self.missing_camera_ids.remove(camera_id)
                        item = self.camera_calibration.get(str(camera_id))
                        if item is not None:
                            item["available"] = True
                            if item.get("status") == "offline":
                                item["status"] = "pending"
                            item.pop("error", None)
                        results["cameras"].append({"id": camera_id, "status": "connected"})
                    except Exception as error:
                        results["cameras"].append({"id": camera_id, "status": "error", "error": str(error)})
            except Exception as error:
                self._add_warning_unlocked("camera", f"Camera retry failed: {error}")

            for scale in self.scales.values():
                if not scale.running:
                    try:
                        scale.start()
                    except Exception as error:
                        scale.error = str(error)
                results["scales"].append(scale.snapshot())

            if self.atlas is not None:
                if not self.atlas.running:
                    try:
                        self.atlas.start()
                    except Exception as error:
                        self.atlas.error = str(error)
                results["atlas"] = self.atlas.sensor_snapshots()

            # If acquisition is already active, reconnecting a device should
            # be useful immediately. Existing recorders are idempotent, while
            # newly available devices start a fresh camera segment or append to
            # their sensor TSV without changing stage timing.
            if self.state in {self.RUNNING, self.PAUSED}:
                try:
                    self._start_sensor_recording_unlocked()
                except Exception as error:
                    self._add_warning_unlocked(
                        "sensor",
                        f"Sensor retry completed, but recording could not be restarted: {error}",
                    )

                camera_expected = False
                if self.stage_state == self.STAGE_ACTIVE:
                    camera_expected = self._camera_required(self.current_stage)
                elif self.stage_state == self.STAGE_TRANSITION:
                    camera_expected = (
                        self._camera_required(self.current_stage)
                        and self._camera_required(self.next_stage)
                    )
                if camera_expected:
                    self._start_camera_recording_unlocked(self.current_stage)

            # Allow a recovered device to generate a fresh warning if it fails
            # again later in the same execution.
            self.device_failure_keys.clear()
            self._touch_unlocked("DEVICES_RETRIED", {"results": results})
            return self.status

    def resume_recovery(self):
        with self.lock:
            if self.state != self.RECOVERY_REQUIRED:
                raise RuntimeError("The experiment is not in recovery.")
            if self.current_stage is None:
                raise RuntimeError("There is no stage to resume.")

            context = self.recovery_context or {}
            previous_stage_state = context.get("previous_stage_state") or self.stage_state
            now = time.monotonic()

            self._start_sensor_recording_unlocked()
            self._start_performance_telemetry_unlocked()

            if previous_stage_state == self.STAGE_TRANSITION:
                remaining = context.get("transition_remaining_s")
                self.stage_state = self.STAGE_TRANSITION
                self.transition_started_monotonic = now
                self.transition_started_at = _utc_now()
                if self.auto_advance_enabled:
                    if remaining is None:
                        remaining = self.transition_timeout_s
                    self.transition_deadline = now + max(0.0, float(remaining))
                else:
                    self.transition_deadline = None
                if self._camera_required(self.current_stage) and self._camera_required(self.next_stage):
                    self._start_camera_recording_unlocked(self.current_stage)
            else:
                elapsed = float(context.get("stage_elapsed_s") or 0.0)
                duration = float(self.current_stage.get("duration", 0) or 0)
                remaining = context.get("stage_remaining_s")
                if remaining is None:
                    remaining = max(0.0, duration - elapsed)
                self.stage_state = self.STAGE_ACTIVE
                self.stage_started_monotonic = now - elapsed
                self.stage_started_at = _utc_now()
                self.stage_deadline = now + max(0.0, float(remaining))
                if self._camera_required(self.current_stage):
                    self._start_camera_recording_unlocked(self.current_stage)
                if self._scraping_required(self.current_stage):
                    self.next_scraping_deadline = now + self._scraping_interval(self.current_stage)

            self.state = self.RUNNING
            self.last_error = None
            self.recovery_context = None
            self._touch_unlocked("RECOVERY_RESUMED")
            return self.status

    def restart_current_stage(self, reason="Operator restarted stage"):
        with self.lock:
            if self.state not in {self.RECOVERY_REQUIRED, self.PAUSED, self.RUNNING}:
                raise RuntimeError("The current stage cannot be restarted from this state.")
            if self.current_stage is None:
                raise RuntimeError("There is no current stage to restart.")

            previous_attempt = self.stage_attempt
            self._append_event_unlocked(
                "STAGE_ATTEMPT_INVALIDATED",
                {
                    "stage_id": self.current_stage.get("id"),
                    "attempt": previous_attempt,
                    "reason": str(reason),
                },
            )
            self._stop_camera_recording_unlocked(ignore_errors=True)
            self._start_sensor_recording_unlocked()
            self._start_performance_telemetry_unlocked()
            self.state = self.RUNNING
            self.recovery_context = None
            self.last_error = None
            self._start_stage_unlocked(self.current_stage, new_attempt=True)
            return self.status

    def reset(self):
        with self.lock:
            if self.state not in {self.COMPLETED, self.ABORTED, self.ERROR, self.RECOVERY_REQUIRED}:
                raise RuntimeError("Only a completed, aborted, failed or recovery run can be reset.")
            self._reset_run_state_unlocked()
            self.revision += 1
            self.condition.notify_all()
            return self.status

    def _check_device_health_unlocked(self):
        if self.state not in {self.RUNNING, self.PAUSED}:
            return

        for camera in list(self.cameras.values()):
            if not camera.recording or camera.ffmpeg is None:
                continue
            return_code = camera.ffmpeg.poll()
            if return_code is None:
                continue

            self._add_warning_once_unlocked(
                f"camera-ffmpeg-{camera.id}-{self.camera_segment_count.get(camera.id, 0)}",
                "camera",
                f"{camera.name} recording stopped unexpectedly (FFmpeg {return_code}). The experiment continues.",
                {"camera_id": camera.id, "return_code": return_code},
            )
            metadata = self.active_camera_segments.pop(camera.id, None)
            try:
                camera.cleanup_failed_recording()
            except Exception:
                pass
            if metadata is not None:
                metadata.update({
                    "end_timestamp": _utc_now(),
                    "end_timestamp_ns": time.time_ns(),
                    "end_monotonic_ns": time.monotonic_ns(),
                    "error": f"FFmpeg exited with code {return_code}",
                })
                self._write_camera_segment_metadata_unlocked(metadata)
                self._append_event_unlocked("CAMERA_RECORDING_FAILED", deepcopy(metadata))

        for scale in self.scales.values():
            snapshot = scale.snapshot()
            if snapshot.get("status") in {"offline", "error", "stopped"}:
                self._add_warning_once_unlocked(
                    f"scale-{scale.id}-{snapshot.get('status')}",
                    "sensor",
                    f"{scale.name} is {snapshot.get('status')}. The experiment continues without new data from it.",
                    {"sensor_id": scale.id, "error": snapshot.get("error")},
                )

        if self.atlas is not None:
            for snapshot in self.atlas.sensor_snapshots():
                if snapshot.get("status") in {"offline", "error", "stopped"}:
                    self._add_warning_once_unlocked(
                        f"atlas-{snapshot.get('id')}-{snapshot.get('status')}",
                        "sensor",
                        f"{snapshot.get('name')} is {snapshot.get('status')}. The experiment continues without new data from it.",
                        {"sensor_id": snapshot.get("id"), "error": snapshot.get("error")},
                    )

    # ------------------------------------------------------------------
    # Timing / control loop
    # ------------------------------------------------------------------

    def _control_loop(self):
        while not self.stop_event.is_set():
            try:
                with self.condition:
                    if self.state in {self.RUNNING, self.PAUSED}:
                        self._check_device_health_unlocked()

                    if self.state == self.RUNNING:
                        now = time.monotonic()

                        if (
                            self.stage_state == self.STAGE_ACTIVE
                            and self.next_scraping_deadline is not None
                            and now >= self.next_scraping_deadline
                        ):
                            interval = self._scraping_interval(self.current_stage)
                            scheduled = self.next_scraping_deadline
                            self._trigger_scraping_unlocked()
                            missed = max(1, int((now - scheduled) // interval) + 1)
                            self.next_scraping_deadline = scheduled + missed * interval

                        if (
                            self.stage_state == self.STAGE_ACTIVE
                            and self.stage_deadline is not None
                            and now >= self.stage_deadline
                        ):
                            self._complete_stage_unlocked()
                            continue

                        if (
                            self.stage_state == self.STAGE_TRANSITION
                            and self.transition_deadline is not None
                            and now >= self.transition_deadline
                        ):
                            self.start_next_stage()
                            continue

                    self.condition.wait(timeout=self._next_control_wait_unlocked())

            except Exception as error:
                with self.lock:
                    if self.state in {self.RUNNING, self.PAUSED}:
                        self._enter_recovery_unlocked(error, source="orchestrator")
                    else:
                        self.last_error = str(error)
                        self._add_warning_unlocked(
                            "orchestrator",
                            f"Background orchestrator warning: {error}",
                        )
                time.sleep(0.2)

    def _next_control_wait_unlocked(self):
        if self.state != self.RUNNING:
            return 1.0

        now = time.monotonic()
        deadlines = []
        for deadline in (
            self.stage_deadline,
            self.transition_deadline,
            self.next_scraping_deadline,
        ):
            if deadline is not None:
                deadlines.append(max(0.0, deadline - now))

        if not deadlines:
            return 1.0
        return max(0.02, min(0.5, min(deadlines)))

    # ------------------------------------------------------------------
    # Stage policies / process hardware
    # ------------------------------------------------------------------

    def stage_policy(self, stage: dict | None):
        if stage is None:
            return {"camera": False, "sensors": False, "scraping": False}
        stage_type = str(stage.get("type", "")).strip().lower()
        return deepcopy(self.STAGE_POLICIES.get(stage_type, self.STAGE_POLICIES["custom"]))

    def _camera_required(self, stage):
        return bool(self.stage_policy(stage)["camera"])

    def _scraping_required(self, stage):
        return bool(stage is not None and self.stage_policy(stage)["scraping"])

    def _scraping_interval(self, stage):
        if stage is not None and stage.get("scraping_interval") is not None:
            interval = float(stage["scraping_interval"])
        else:
            interval = self.scraping_interval_s
        return max(0.1, interval)

    def apply_stage_setpoints(self, stage: dict):
        """Hardware control extension point for airflow, rotor speed, pH, etc."""
        return {
            "airflow": stage.get("airflow"),
            "rotor_speed": stage.get("rotor_speed"),
            "pH": stage.get("ph", stage.get("pH")),
        }

    def _trigger_scraping_unlocked(self):
        if not self._scraping_required(self.current_stage):
            return

        self.scraping_sequence += 1
        self.last_scraping_at = _utc_now()

        if self.scraping_method == "gpio":
            self._trigger_scraping_hardware()

        self._touch_unlocked(
            "SCRAPING_SIGNAL",
            {
                "method": self.scraping_method,
                "scraping_sequence": self.scraping_sequence,
            },
        )

    def _trigger_scraping_hardware(self):
        """Future GPIO/TTL scraping pulse implementation."""
        return None

    # ------------------------------------------------------------------
    # Sensors
    # ------------------------------------------------------------------

    def acquisition_context(self):
        with self.lock:
            current = self.current_stage
            next_stage = self.next_stage

            if self.stage_state == self.STAGE_TRANSITION:
                stage_id = None
                previous_stage_id = current.get("id") if current else None
                next_stage_id = next_stage.get("id") if next_stage else None
            else:
                stage_id = current.get("id") if current else None
                previous_stage_id = None
                next_stage_id = None

            return {
                "monotonic_ns": time.monotonic_ns(),
                "run_elapsed_s": self._run_elapsed_unlocked(),
                "digiflot_state": self.state,
                "stage_state": self.stage_state,
                "stage_id": stage_id,
                "stage_attempt": self.stage_attempt,
                "previous_stage_id": previous_stage_id,
                "next_stage_id": next_stage_id,
            }

    def _start_sensor_recording_unlocked(self):
        if self.run_directory is None:
            raise RuntimeError("No experiment execution is selected.")

        directory = self.run_directory / "sensors"

        for scale in self.scales.values():
            snapshot = scale.snapshot()
            if not scale.running or snapshot.get("status") != "connected":
                reason = snapshot.get("error") or snapshot.get("status") or "offline"
                self._add_warning_unlocked(
                    "sensor",
                    f"{scale.name} is unavailable and will not be recorded.",
                    {"sensor_id": scale.id, "reason": reason},
                )
                self._append_event_unlocked(
                    "SENSOR_RECORDING_SKIPPED",
                    {"sensor_id": scale.id, "reason": reason},
                )
                continue

            try:
                path = scale.start_recording(
                    output_dir=directory,
                    file_stem=_safe_path_name(scale.id),
                )
                self._append_event_unlocked(
                    "SENSOR_RECORDING_STARTED",
                    {"sensor_id": scale.id, "path": str(path)},
                )
            except Exception as error:
                self._add_warning_unlocked(
                    "sensor",
                    f"Could not start {scale.name}: {error}",
                    {"sensor_id": scale.id},
                )
                self._append_event_unlocked(
                    "SENSOR_RECORDING_SKIPPED",
                    {"sensor_id": scale.id, "reason": str(error)},
                )

        if self.atlas is not None:
            connected = [
                item for item in self.atlas.sensor_snapshots()
                if item.get("status") == "connected"
            ]
            if not self.atlas.running or not connected:
                reason = self.atlas.error or "No Atlas sensors are online."
                self._add_warning_unlocked(
                    "sensor",
                    "Atlas Scientific acquisition is unavailable and will be skipped.",
                    {"sensor_id": "atlas", "reason": reason},
                )
                self._append_event_unlocked(
                    "SENSOR_RECORDING_SKIPPED",
                    {"sensor_id": "atlas", "reason": reason},
                )
            else:
                try:
                    path = self.atlas.start_recording(
                        output_dir=directory,
                        file_stem=_safe_path_name(self.atlas.name),
                    )
                    self._append_event_unlocked(
                        "SENSOR_RECORDING_STARTED",
                        {
                            "sensor_id": "atlas",
                            "path": str(path),
                            "connected_sensors": [item.get("id") for item in connected],
                        },
                    )
                except Exception as error:
                    self._add_warning_unlocked(
                        "sensor",
                        f"Could not start Atlas recording: {error}",
                        {"sensor_id": "atlas"},
                    )
                    self._append_event_unlocked(
                        "SENSOR_RECORDING_SKIPPED",
                        {"sensor_id": "atlas", "reason": str(error)},
                    )

    def _stop_sensor_recording_unlocked(self):
        for scale in self.scales.values():
            try:
                if scale.recording or scale.writer_active:
                    scale.stop_recording()
                    self._append_event_unlocked(
                        "SENSOR_RECORDING_STOPPED",
                        {"sensor_id": scale.id},
                    )
            except Exception as error:
                self._add_warning_unlocked(
                    "sensor",
                    f"Could not stop {scale.name} recording cleanly: {error}",
                    {"sensor_id": scale.id},
                )

        if self.atlas is not None:
            try:
                if self.atlas.recording or self.atlas.writer_active:
                    self.atlas.stop_recording()
                    self._append_event_unlocked(
                        "SENSOR_RECORDING_STOPPED",
                        {"sensor_id": "atlas"},
                    )
            except Exception as error:
                self._add_warning_unlocked(
                    "sensor",
                    f"Could not stop Atlas recording cleanly: {error}",
                    {"sensor_id": "atlas"},
                )

    # ------------------------------------------------------------------
    # Optional performance telemetry
    # ------------------------------------------------------------------

    def _performance_warning_callback(self, message, sample):
        with self.lock:
            if self.run_directory is None:
                return
            try:
                if self.performance is not None:
                    self.performance.mark_degraded(message, sample)
            except Exception:
                pass
            self._add_warning_unlocked(
                "performance",
                message,
                {"sample": deepcopy(sample)},
            )
            self._touch_unlocked(
                "PERFORMANCE_WARNING",
                {"message": message, "sample": deepcopy(sample)},
            )

    def _start_performance_telemetry_unlocked(self):
        if self.performance is None or self.run_directory is None:
            return
        try:
            if self.performance.telemetry_thread is None:
                self.performance.start_experiment_telemetry(
                    self.run_directory,
                    event_callback=self._performance_warning_callback,
                )
        except Exception as error:
            self._add_warning_unlocked(
                "performance",
                f"System telemetry is unavailable: {error}",
            )

    def _stop_performance_telemetry_unlocked(self):
        if self.performance is None:
            return
        try:
            self.performance.stop_experiment_telemetry()
        except Exception as error:
            if self.run_directory is not None:
                self._add_warning_unlocked(
                    "performance",
                    f"Could not stop system telemetry cleanly: {error}",
                )

    def evaluate_camera_performance(
        self,
        camera_id=None,
        frame_rate=None,
        camera_config=None,
    ):
        with self.lock:
            if self.performance is None:
                return {
                    "status": "UNAVAILABLE",
                    "reason": "Performance module is unavailable.",
                    "recommended": None,
                }
            rate_overrides = {}
            config_overrides = {}
            if camera_id is not None:
                camera_id = int(camera_id)
                if frame_rate is not None:
                    rate_overrides[str(camera_id)] = float(frame_rate)
                if isinstance(camera_config, dict):
                    config_overrides[str(camera_id)] = deepcopy(camera_config)
            return self.performance.evaluate(
                self,
                overrides=rate_overrides,
                config_overrides=config_overrides,
            )

    # ------------------------------------------------------------------
    # System settings and persistent hardware configuration
    # ------------------------------------------------------------------

    def settings_payload(self):
        with self.lock:
            return {
                "state": self.state,
                "restart_required": False,
                "orchestration": {
                    "auto_advance_enabled": self.auto_advance_enabled,
                    "transition_timeout_s": self.transition_timeout_s,
                    "scraping_interval": self.scraping_interval_s,
                    "scraping_method": self.scraping_method,
                },
                "configured": {
                    "cameras": deepcopy(self.config.get("cameras", [])),
                    "scales": deepcopy(self.config.get("sensors", {}).get("scales", [])),
                    "atlas_scientific": deepcopy(self.config.get("sensors", {}).get("atlas_scientific")),
                },
            }

    def update_system_settings(self, payload: dict):
        with self.lock:
            if self.state != self.IDLE:
                raise RuntimeError("System settings can only be changed while DigiFlot is idle.")

            orchestration = self.config.setdefault("orchestration", {})
            if "auto_advance_enabled" in payload:
                self.auto_advance_enabled = bool(payload["auto_advance_enabled"])
            if "transition_timeout_s" in payload:
                value = float(payload["transition_timeout_s"])
                if value < 0:
                    raise ValueError("transition_timeout_s must be greater than or equal to zero.")
                self.transition_timeout_s = value
            if "scraping_interval" in payload:
                value = float(payload["scraping_interval"])
                if value <= 0:
                    raise ValueError("scraping_interval must be greater than zero.")
                self.scraping_interval_s = value
            if "scraping_method" in payload:
                method = str(payload["scraping_method"]).strip().lower()
                if method not in {"audio", "gpio"}:
                    raise ValueError("scraping_method must be 'audio' or 'gpio'.")
                self.scraping_method = method

            orchestration["auto_advance_enabled"] = self.auto_advance_enabled
            orchestration["transition_timeout_s"] = self.transition_timeout_s
            orchestration["scraping_interval"] = self.scraping_interval_s
            orchestration["scraping_method"] = self.scraping_method
            paths = self.save_config()
            return {"orchestration": deepcopy(orchestration), "saved_to": paths}

    def save_discovered_devices(self, payload: dict):
        """Persist explicitly selected detected hardware. Activation occurs after restart."""
        with self.lock:
            if self.state != self.IDLE:
                raise RuntimeError("Hardware configuration can only be changed while DigiFlot is idle.")

            added = {"cameras": [], "scales": [], "atlas": []}
            config_cameras = self.config.setdefault("cameras", [])
            existing_camera_ids = {int(item["id"]) for item in config_cameras}
            existing_names = {str(item.get("name", "")) for item in config_cameras}

            for item in payload.get("cameras", []) or []:
                camera_id = int(item["id"])
                if camera_id in existing_camera_ids:
                    continue
                name = f"Camera_{camera_id + 1}"
                suffix = 2
                while name in existing_names:
                    name = f"Camera_{camera_id + 1}_{suffix}"
                    suffix += 1
                camera_config = Camera.config_from_detection(item, name=name)
                config_cameras.append(camera_config)
                existing_camera_ids.add(camera_id)
                existing_names.add(name)
                added["cameras"].append(camera_config)

            sensors = self.config.setdefault("sensors", {})
            scale_configs = sensors.setdefault("scales", [])
            existing_ports = {str(item.get("port")) for item in scale_configs}
            existing_scale_ids = {str(item.get("id")) for item in scale_configs}
            next_scale = 1
            for item in payload.get("scales", []) or []:
                port = str(item["port"])
                if port in existing_ports:
                    continue
                while f"scale_{next_scale}" in existing_scale_ids:
                    next_scale += 1
                sensor_id = f"scale_{next_scale}"
                scale_config = Scale.config_from_detection(item, sensor_id=sensor_id, name=f"Scale {next_scale}")
                scale_configs.append(scale_config)
                existing_ports.add(port)
                existing_scale_ids.add(sensor_id)
                next_scale += 1
                added["scales"].append(scale_config)

            atlas_items = payload.get("atlas", []) or []
            if atlas_items:
                atlas_config = sensors.setdefault("atlas_scientific", {
                    "bus": int(payload.get("atlas_bus", 1)),
                    "name": "Atlas",
                    "sensors": [],
                    "sample_interval": 1.0,
                    "output_dir": "./data/atlas",
                    "buffer_size": 100,
                    "flush_interval": 5.0,
                })
                configured_sensors = atlas_config.setdefault("sensors", [])
                existing_addresses = {int(item["address"]) for item in configured_sensors}
                for item in atlas_items:
                    address = int(item["address"])
                    if address in existing_addresses:
                        continue
                    sensor_config = AtlasScientific.sensor_config_from_detection(item)
                    configured_sensors.append(sensor_config)
                    existing_addresses.add(address)
                    added["atlas"].append(sensor_config)

            changed = any(added.values())
            paths = self.save_config() if changed else []
            return {
                "added": added,
                "changed": changed,
                "restart_required": changed,
                "saved_to": paths,
            }

    # ------------------------------------------------------------------
    # Cameras and camera configuration
    # ------------------------------------------------------------------

    def camera_summaries(self):
        with self.lock:
            result = []
            for camera in self.cameras.values():
                item = {
                    "id": camera.id,
                    "name": camera.name,
                    "state": camera.state,
                }
                calibration = self.camera_calibration.get(str(camera.id))
                if calibration is not None:
                    item["calibration_status"] = calibration.get("status")
                result.append(item)
            return result

    def get_camera(self, camera_id: int):
        camera_id = int(camera_id)
        if camera_id not in self.cameras:
            raise KeyError(f"Camera ID {camera_id} not found.")
        return self.cameras[camera_id]

    def get_camera_payload(self, camera_id: int):
        with self.lock:
            camera = self.get_camera(camera_id)
            payload = camera.configuration_payload()
            payload["digiflot_state"] = self.state
            payload["is_active_preview"] = (
                self.preview_camera_id == camera.id
                and camera.state == camera.PREVIEW
            )
            payload["calibration"] = deepcopy(
                self.camera_calibration.get(str(camera.id))
            )
            return payload

    def save_config(self):
        paths = {
            CURRENT_CONFIG_PATH.resolve(),
            DEFAULT_CONFIG_PATH.resolve(),
        }
        for path in paths:
            _atomic_write_json(path, self.config)
        return [str(path) for path in sorted(paths, key=str)]

    def update_camera_config(self, camera_id: int, updates: dict):
        with self.lock:
            if self.state not in {self.IDLE, self.CAMERA_CALIBRATION}:
                raise RuntimeError(
                    "Camera configuration can only be changed while DigiFlot is idle or calibrating cameras."
                )
            if self.recording:
                raise RuntimeError("Camera configuration cannot be changed while recording.")

            camera = self.get_camera(camera_id)
            if camera.state != camera.IDLE:
                raise RuntimeError("Stop preview before saving structural camera settings.")

            new_name = str(updates.get("name", camera.name)).strip()
            for item in self.config.get("cameras", []):
                if int(item["id"]) == camera.id:
                    continue
                if str(item.get("name", "")).strip() == new_name:
                    raise ValueError(f"Camera name '{new_name}' is already in use.")

            camera.update_config(updates)
            paths = self.save_config()
            if self.run_directory is not None:
                calibration = self.camera_calibration.get(str(camera.id))
                if calibration is not None:
                    calibration["name"] = camera.name
                self._write_config_snapshot_unlocked()
                self._touch_unlocked(
                    "CAMERA_CONFIGURATION_SAVED",
                    {"camera_id": camera.id},
                )

            return {
                "camera": self.get_camera_payload(camera.id),
                "saved_to": paths,
            }

    def start_preview(self, camera_id: int):
        with self.lock:
            if self.recording:
                raise RuntimeError("Preview is not available while recording.")
            if self.state not in {self.IDLE, self.CAMERA_CALIBRATION}:
                raise RuntimeError("Preview is only available while idle or calibrating cameras.")

            camera = self.get_camera(camera_id)
            if self.preview_camera_id == camera.id and camera.state == camera.PREVIEW:
                return self.status

            if self.preview_camera_id is not None:
                self.stop_preview()

            try:
                camera.start_preview()
            except Exception:
                self.preview_camera_id = None
                raise

            self.preview_camera_id = camera.id
            self.revision += 1
            self.condition.notify_all()
            return self.status

    def stop_preview(self):
        with self.lock:
            camera_id = self.preview_camera_id
            self.preview_camera_id = None

            if camera_id is not None and camera_id in self.cameras:
                self.cameras[camera_id].stop_preview()

            self.revision += 1
            self.condition.notify_all()
            return self._status_unlocked()

    def calibrate_exposure(self, camera_id: int):
        with self.lock:
            camera = self.get_camera(camera_id)
            if self.preview_camera_id != camera.id or camera.state != camera.PREVIEW:
                raise RuntimeError(
                    "Exposure calibration requires this camera to be the active preview."
                )

            exposure = camera.calibrate_exposure()
            self.save_config()
            if self.run_directory is not None:
                calibration = self.camera_calibration.get(str(camera.id))
                if calibration is not None:
                    calibration["exposure"] = deepcopy(exposure)
                self._write_config_snapshot_unlocked()
            return exposure

    def set_exposure(self, camera_id: int, exposure_time_us: int, analogue_gain: float):
        with self.lock:
            camera = self.get_camera(camera_id)
            if self.preview_camera_id != camera.id or camera.state != camera.PREVIEW:
                raise RuntimeError(
                    "Manual exposure requires this camera to be the active preview."
                )
            exposure = camera.set_exposure(exposure_time_us, analogue_gain)
            self.save_config()
            if self.run_directory is not None:
                calibration = self.camera_calibration.get(str(camera.id))
                if calibration is not None:
                    calibration["exposure"] = deepcopy(exposure)
                self._write_config_snapshot_unlocked()
            return exposure

    def set_camera_controls(self, camera_id: int, controls: dict):
        with self.lock:
            if self.recording:
                raise RuntimeError("Camera controls cannot be changed while recording.")
            camera = self.get_camera(camera_id)
            values = camera.set_controls(controls)
            self.save_config()
            if self.run_directory is not None:
                self._write_config_snapshot_unlocked()
            return values

    def _start_camera_recording_unlocked(self, stage: dict | None = None):
        if self.run_directory is None:
            raise RuntimeError("No experiment execution is selected.")

        if not self.cameras:
            self._add_warning_unlocked(
                "camera",
                "No cameras are currently available. The experiment will continue without video.",
            )
            self._append_event_unlocked(
                "CAMERA_RECORDING_SKIPPED",
                {"reason": "No cameras available."},
            )
            return

        for camera in self.cameras.values():
            if camera.recording:
                continue

            calibration = self.camera_calibration.get(str(camera.id), {})
            if calibration.get("status") == "skipped":
                self._add_warning_unlocked(
                    "camera",
                    f"{camera.name} calibration was skipped; video acquisition for this camera is skipped.",
                    {"camera_id": camera.id},
                )
                self._append_event_unlocked(
                    "CAMERA_RECORDING_SKIPPED",
                    {"camera_id": camera.id, "reason": "Calibration skipped."},
                )
                continue

            if camera.exposure_time_us is None or camera.analogue_gain is None:
                self._add_warning_unlocked(
                    "camera",
                    f"{camera.name} has no calibrated exposure and will not be recorded.",
                    {"camera_id": camera.id},
                )
                self._append_event_unlocked(
                    "CAMERA_RECORDING_SKIPPED",
                    {"camera_id": camera.id, "reason": "Exposure unavailable."},
                )
                continue

            try:
                count = self.camera_segment_count.get(camera.id, 0) + 1
                self.camera_segment_count[camera.id] = count
                safe_name = _safe_path_name(camera.name)
                output_base = (
                    self.run_directory
                    / "cameras"
                    / safe_name
                    / f"segment_{count:04d}_{safe_name}"
                )
                output_path = camera.start_recording(output_base)

                metadata = {
                    "camera_id": camera.id,
                    "camera_name": camera.name,
                    "segment": count,
                    "path": str(output_path),
                    "start_timestamp": _utc_now(),
                    "start_timestamp_ns": time.time_ns(),
                    "start_monotonic_ns": time.monotonic_ns(),
                    "start_stage_id": stage.get("id") if stage else None,
                    "stage_attempt": self.stage_attempt,
                }
                self.active_camera_segments[camera.id] = metadata
                self._write_camera_segment_metadata_unlocked(metadata)
                self._append_event_unlocked("CAMERA_RECORDING_STARTED", deepcopy(metadata))
            except Exception as error:
                self._add_warning_unlocked(
                    "camera",
                    f"Could not start {camera.name}: {error}",
                    {"camera_id": camera.id},
                )
                self._append_event_unlocked(
                    "CAMERA_RECORDING_SKIPPED",
                    {"camera_id": camera.id, "reason": str(error)},
                )
                try:
                    camera.stop_recording()
                except Exception:
                    pass

    def _stop_camera_recording_unlocked(self, ignore_errors=False):
        errors = []
        for camera in self.cameras.values():
            if not camera.recording:
                continue

            metadata = self.active_camera_segments.pop(camera.id, None)
            try:
                camera.stop_recording()
            except Exception as error:
                errors.append((camera.name, error))
                self._add_warning_unlocked(
                    "camera",
                    f"Could not stop {camera.name} recording cleanly: {error}",
                    {"camera_id": camera.id},
                )

            if metadata is not None:
                metadata.update({
                    "end_timestamp": _utc_now(),
                    "end_timestamp_ns": time.time_ns(),
                    "end_monotonic_ns": time.monotonic_ns(),
                    "end_stage_id": self.current_stage.get("id") if self.current_stage else None,
                })
                self._write_camera_segment_metadata_unlocked(metadata)
                self._append_event_unlocked("CAMERA_RECORDING_STOPPED", deepcopy(metadata))

        if errors and not ignore_errors:
            raise RuntimeError(
                "Failed to stop recording: "
                + ", ".join(f"{name}: {error}" for name, error in errors)
            )

    def _write_camera_segment_metadata_unlocked(self, metadata: dict):
        path = Path(metadata["path"])
        sidecar = path.with_suffix(path.suffix + ".json")
        _atomic_write_json(sidecar, metadata)

    # Backward-compatible manual camera recording helpers.
    def start_recording(self, experiment_name: str, output_types: dict | None = None):
        del output_types
        with self.lock:
            if self.state != self.IDLE:
                raise RuntimeError("Manual recording is only available while DigiFlot is idle.")
            if self.recording:
                raise RuntimeError("Recording already active.")

            directory = self.output_directory / _safe_path_name(experiment_name)
            directory.mkdir(parents=True, exist_ok=True)
            paths = {}
            run_id = datetime.now().strftime("%Y%m%d-%H%M%S")

            try:
                for camera in self.cameras.values():
                    safe_name = _safe_path_name(camera.name)
                    output_base = directory / safe_name / f"{run_id}_{safe_name}"
                    paths[camera.name] = str(camera.start_recording(output_base))
            except Exception:
                for camera in self.cameras.values():
                    try:
                        camera.stop_recording()
                    except Exception:
                        pass
                raise

            self.revision += 1
            self.condition.notify_all()
            return paths

    def stop_recording(self, ignore_errors=False):
        with self.lock:
            errors = []
            for camera in self.cameras.values():
                try:
                    camera.stop_recording()
                except Exception as error:
                    errors.append((camera.name, error))

            self.revision += 1
            self.condition.notify_all()

            if errors and not ignore_errors:
                raise RuntimeError(
                    "Failed to stop recording: "
                    + ", ".join(f"{name}: {error}" for name, error in errors)
                )
            return self._status_unlocked()
