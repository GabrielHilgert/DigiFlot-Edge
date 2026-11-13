import json
import math
import os
import shutil
import subprocess
import tempfile
import threading
import time
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path


def _utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


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


class PerformanceManager:
    """Optional performance profiling and lightweight system telemetry.

    This module never owns experiment state. DigiFlot may use its results, but
    a failure here must not stop acquisition or orchestration.
    """

    IDLE = "Idle"
    RUNNING = "Running"
    COMPLETED = "Completed"
    FAILED = "Failed"
    ABORTED = "Aborted"

    def __init__(self, config: dict, base_dir: Path):
        self.config = config.setdefault("performance", {})
        self.base_dir = Path(base_dir) / "performance"
        self.profile_path = self.base_dir / "profile.json"
        self.history_dir = self.base_dir / "benchmarks"

        self.rates = sorted({
            float(value)
            for value in self.config.get(
                "rates",
                [10, 15, 20, 25, 30],
            )
            if float(value) > 0
        })
        self.quick_duration_s = float(self.config.get("quick_duration_s", 30.0))
        self.stability_duration_s = float(self.config.get("stability_duration_s", 120.0))
        self.sample_interval_s = max(0.25, float(self.config.get("sample_interval_s", 1.0)))
        self.telemetry_interval_s = max(1.0, float(self.config.get("telemetry_interval_s", 10.0)))
        self.idle_telemetry_interval_s = max(1.0, float(self.config.get("idle_telemetry_interval_s", 30.0)))
        self.storage_safety_margin_pct = max(0.0, float(self.config.get("storage_safety_margin_pct", 30.0)))
        self.max_temperature_c = float(self.config.get("max_temperature_c", 80.0))
        self.min_disk_free_gb = float(self.config.get("min_disk_free_gb", 2.0))
        self.profile_max_age_days = int(self.config.get("profile_max_age_days", 60))

        self.lock = threading.RLock()
        self.condition = threading.Condition(self.lock)
        self.state = self.IDLE
        self.revision = 0
        self.current_rate = None
        self.current_result = None
        self.started_at = None
        self.elapsed_s = 0.0
        self.last_error = None
        self.results = []
        self.virtual_sensor = None
        self.abort_event = threading.Event()
        self.benchmark_thread = None

        self.monitor_stop = threading.Event()
        self.monitor_wake = threading.Event()
        self.monitor_thread = None
        self.telemetry_lock = threading.RLock()
        self.telemetry_path = None
        self.telemetry_event_callback = None
        self.monitor_error = None
        self._cpu_sample_lock = threading.Lock()
        self._previous_cpu_times = None
        self.last_sample = self.sample_system()
        self.profile = self._load_profile()

    def _load_profile(self):
        try:
            with self.profile_path.open("r", encoding="utf-8") as file:
                return json.load(file)
        except Exception:
            return None

    def _save_history_record(self, record: dict):
        self.history_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        _atomic_write_json(self.history_dir / f"{stamp}.json", record)

    def _save_profile(self, profile: dict):
        self.base_dir.mkdir(parents=True, exist_ok=True)
        _atomic_write_json(self.profile_path, profile)
        self._save_history_record(profile)
        self.profile = deepcopy(profile)

    @staticmethod
    def _read_temperature():
        # Prefer sysfs: no process creation on normal Raspberry Pi systems.
        thermal = Path("/sys/class/thermal/thermal_zone0/temp")
        try:
            return float(thermal.read_text(encoding="utf-8").strip()) / 1000.0
        except (OSError, ValueError):
            pass
        try:
            result = subprocess.run(["vcgencmd", "measure_temp"], capture_output=True,
                                    text=True, timeout=1.0, check=False)
            text = result.stdout.strip()
            if "=" in text:
                return float(text.split("=", 1)[1].split("'", 1)[0])
        except (OSError, ValueError, subprocess.TimeoutExpired):
            pass
        return None

    @staticmethod
    def _read_throttled():
        try:
            result = subprocess.run(
                ["vcgencmd", "get_throttled"],
                capture_output=True,
                text=True,
                timeout=1.0,
                check=False,
            )
            text = result.stdout.strip()
            if "=" in text:
                raw = text.split("=", 1)[1]
                value = int(raw, 16)
                return {
                    "raw": raw,
                    "value": value,
                    "current": bool(value & 0xF),
                    "thermal_current": bool(value & 0x6),
                    "historical": bool(value & 0xF0000),
                }
        except Exception:
            pass
        return {"raw": None, "value": None, "current": False, "thermal_current": False, "historical": False}

    def _read_cpu_headroom(self):
        """Real interval CPU busy/idle based on Linux /proc/stat, not load average."""
        try:
            values = [int(x) for x in Path("/proc/stat").read_text().splitlines()[0].split()[1:]]
            if len(values) < 5:
                return None
            total, idle = sum(values[:8]), values[3] + values[4]
            with self._cpu_sample_lock:
                previous = self._previous_cpu_times
                self._previous_cpu_times = (total, idle)
            if not previous or total <= previous[0]:
                return None
            idle_pct = max(0., min(100., 100.*(idle-previous[1])/(total-previous[0])))
            return {"used_pct": round(100.-idle_pct, 2), "free_pct": round(idle_pct, 2)}
        except (OSError, ValueError, IndexError):
            return None

    @staticmethod
    def _read_memory_headroom():
        try:
            values = {}
            for line in Path("/proc/meminfo").read_text().splitlines():
                key, value = line.split(":", 1)
                if key in ("MemTotal", "MemAvailable", "SwapTotal", "SwapFree"):
                    values[key] = int(value.strip().split()[0])
            total, free = values["MemTotal"], values["MemAvailable"]
            if total <= 0:
                return None
            result = {"total_gb": round(total/1024**2, 3),
                      "available_gb": round(free/1024**2, 3),
                      "free_pct": round(100*free/total, 2),
                      "used_pct": round(100*(1-free/total), 2)}
            if values.get("SwapTotal"):
                result["swap_used_pct"] = round(
                    100*(1-values.get("SwapFree", 0)/values["SwapTotal"]), 2)
            return result
        except (OSError, ValueError, IndexError, KeyError):
            return None

    @staticmethod
    def headroom_risk(samples, threshold_pct=10.):
        """Descriptive short-run low-headroom exposure, NOT a future failure probability.

        One-sided Wilson upper bound assumes independent observations; nearby samples
        share load and are correlated, so we avoid describing the bound as predictive.
        """
        valid = [s for s in samples if (s.get("cpu") or {}).get("free_pct") is not None
                 and (s.get("memory") or {}).get("free_pct") is not None]
        n = len(valid)
        low = sum(min(s["cpu"]["free_pct"], s["memory"]["free_pct"]) < threshold_pct
                  for s in valid)
        if not n:
            return {"threshold_pct": threshold_pct, "samples": 0, "low_samples": 0,
                    "observed_pct": None, "upper_bound_95_pct": None,
                    "interpretation": "Insufficient system headroom measurements"}
        p, z = low/n, 1.645
        upper = (p+z*z/(2*n)+z*math.sqrt(p*(1-p)/n+z*z/(4*n*n)))/(1+z*z/n)
        return {"threshold_pct": threshold_pct, "samples": n, "low_samples": low,
                "observed_pct": round(p*100, 2),
                "upper_bound_95_pct": round(min(100., upper*100), 2),
                "interpretation": "Descriptive only: independent-sample upper bound; "
                    "autocorrelation and future load are not captured"}

    def sample_system(self):
        try:
            load1, load5, load15 = os.getloadavg()
        except Exception:
            load1 = load5 = load15 = None

        try:
            usage = shutil.disk_usage(self.base_dir.parent)
            disk = {
                "total_gb": usage.total / 1024**3,
                "free_gb": usage.free / 1024**3,
                "used_gb": usage.used / 1024**3,
            }
        except Exception:
            disk = {"total_gb": None, "free_gb": None, "used_gb": None}

        cpu = self._read_cpu_headroom()
        memory = self._read_memory_headroom()
        return {
            "timestamp": _utc_now(),
            "cpu": cpu,
            "memory": memory,
            "temperature_c": self._read_temperature(),
            "throttled": self._read_throttled(),
            "load1": load1,
            "load5": load5,
            "load15": load15,
            "cpu_count": os.cpu_count() or 1,
            "disk": disk,
        }

    def hardware_signature(self, digiflot, config_overrides=None, virtual_sensor=None):
        config_overrides = config_overrides or {}
        cameras = []
        for camera in sorted(digiflot.cameras.values(), key=lambda item: item.id):
            override = (
                config_overrides.get(str(camera.id))
                or config_overrides.get(camera.id)
                or {}
            )
            model = (
                camera.hardware_info.get("Model")
                or camera.hardware_info.get("model")
                or "Unknown"
            )
            recording = override.get("recording") or {}
            frame_size = override.get("frame_size", camera.frame_size)
            crop_region = override.get("crop_region", camera.crop_region)
            cameras.append({
                "id": camera.id,
                "model": model,
                "frame_size": list(frame_size) if frame_size is not None else None,
                "crop_region": list(crop_region) if crop_region is not None else None,
                "format": override.get("format", camera.format),
                "recording_output_type": recording.get(
                    "output_type",
                    camera.recording_output_type,
                ),
            })
        return {"cameras": cameras, "virtual_sensor": virtual_sensor}

    @staticmethod
    def _virtual_summary(workload):
        if not workload:
            return None
        return {"camera_id": int(workload["camera_id"]), "cell_id": str(workload["cell_id"]),
                "signature": workload["signature"], "method": workload["config"]["method"],
                "sampling_interval_s": float(workload["config"]["sampling_interval_s"]),
                "lores_size": list(workload["lores_size"])}

    def current_camera_rates(self, digiflot, overrides=None):
        overrides = overrides or {}
        rates = {}
        for camera in digiflot.cameras.values():
            rates[str(camera.id)] = float(overrides.get(str(camera.id), overrides.get(camera.id, camera.frame_rate)))
        return rates

    def evaluate(self, digiflot, overrides=None, config_overrides=None):
        try:
            workload = digiflot.vision.performance_workload() if digiflot.vision else None
            virtual_info = self._virtual_summary(workload) if workload else None
            signature = self.hardware_signature(
                digiflot,
                config_overrides=config_overrides, virtual_sensor=virtual_info,
            )
            rates = self.current_camera_rates(digiflot, overrides)
            profile = self.profile
            if not profile:
                return {
                    "status": "UNVALIDATED",
                    "reason": "No performance benchmark has been saved for this system.",
                    "camera_rates": rates,
                    "recommended": None,
                }

            health_reasons = []
            if profile.get("health_status") == "DEGRADED":
                health_reasons.append(
                    profile.get("health_reason")
                    or "Recent experiment telemetry detected a performance problem."
                )

            tested_at = profile.get("tested_at")
            if tested_at and self.profile_max_age_days > 0:
                try:
                    tested_time = datetime.fromisoformat(str(tested_at).replace("Z", "+00:00"))
                    if tested_time.tzinfo is None:
                        tested_time = tested_time.replace(tzinfo=timezone.utc)
                    age_days = (datetime.now(timezone.utc) - tested_time).total_seconds() / 86400.0
                    if age_days > self.profile_max_age_days:
                        health_reasons.append(
                            f"The saved benchmark is {age_days:.0f} days old and should be revalidated."
                        )
                except Exception:
                    pass

            degraded_reason = " ".join(health_reasons) or None

            if profile.get("hardware_signature") != signature:
                return {
                    "status": "UNVALIDATED",
                    "reason": "The camera configuration differs from the saved benchmark profile.",
                    "camera_rates": rates,
                    "recommended": profile.get("recommended_camera_rates"),
                }

            exact = None
            for result in profile.get("results", []):
                result_rates = {str(k): float(v) for k, v in (result.get("camera_rates") or {}).items()}
                if result_rates == rates:
                    exact = result
                    break

            if exact:
                classification = exact.get("classification")
                if classification in {"FAIL", "NOT_TESTED"}:
                    return {
                        "status": "DANGEROUS",
                        "reason": exact.get("reason") or (
                            "This configuration is above a frame rate that failed the benchmark."
                            if classification == "NOT_TESTED"
                            else "This exact configuration failed the benchmark."
                        ),
                        "camera_rates": rates,
                        "recommended": profile.get("recommended_camera_rates"),
                        "benchmark_result": exact,
                    }
                if classification == "MARGINAL":
                    return {
                        "status": "WARNING",
                        "reason": exact.get("reason") or "This configuration passed with little safety margin.",
                        "camera_rates": rates,
                        "recommended": profile.get("recommended_camera_rates"),
                        "benchmark_result": exact,
                    }
                return {
                    "status": "WARNING" if degraded_reason else "SAFE",
                    "reason": degraded_reason or "This exact camera configuration passed the saved benchmark.",
                    "camera_rates": rates,
                    "recommended": profile.get("recommended_camera_rates"),
                    "benchmark_result": exact,
                }

            recommended = {str(k): float(v) for k, v in (profile.get("recommended_camera_rates") or {}).items()}
            maximum = {str(k): float(v) for k, v in (profile.get("max_stable_camera_rates") or {}).items()}
            if recommended and all(rates.get(k, float("inf")) <= v for k, v in recommended.items()):
                return {
                    "status": "WARNING" if degraded_reason else "SAFE",
                    "reason": degraded_reason or "This configuration is at or below the recommended validated envelope.",
                    "camera_rates": rates,
                    "recommended": recommended,
                }
            if maximum and all(rates.get(k, float("inf")) <= v for k, v in maximum.items()):
                return {
                    "status": "WARNING",
                    "reason": "This configuration is within the tested limit but above the recommended safety setting.",
                    "camera_rates": rates,
                    "recommended": recommended,
                }
            return {
                "status": "UNVALIDATED",
                "reason": "This combined camera configuration has not been validated.",
                "camera_rates": rates,
                "recommended": recommended or None,
            }
        except Exception as error:
            return {
                "status": "UNAVAILABLE",
                "reason": str(error),
                "camera_rates": {},
                "recommended": None,
            }

    @property
    def status(self):
        with self.lock:
            return {
                "revision": self.revision,
                "state": self.state,
                "current_rate": self.current_rate,
                "current_result": deepcopy(self.current_result),
                "started_at": self.started_at,
                "elapsed_s": self.elapsed_s,
                "last_error": self.last_error,
                "results": deepcopy(self.results),
                "virtual_sensor": deepcopy(self.virtual_sensor),
                "profile": deepcopy(self.profile),
                "system": deepcopy(self.last_sample),
            }

    def wait_for_update(self, last_revision, timeout=1.0):
        with self.condition:
            self.condition.wait_for(lambda: self.revision != last_revision, timeout=timeout)
            return self.status

    def _touch(self):
        self.revision += 1
        self.condition.notify_all()

    def start_benchmark(self, digiflot, rates=None, duration_s=None, include_virtual=True):
        with self.lock:
            if self.state == self.RUNNING:
                raise RuntimeError("A performance benchmark is already running.")
            if digiflot.state != digiflot.IDLE:
                raise RuntimeError("Performance benchmark is only available while DigiFlot is idle.")
            if digiflot.preview_camera_id is not None or digiflot.recording:
                raise RuntimeError("Stop camera preview/recording before starting the benchmark.")
            if not digiflot.cameras:
                raise RuntimeError("No cameras are currently available for benchmarking.")

            test_rates = sorted({
                float(value)
                for value in (rates or self.rates)
                if float(value) > 0
            })
            if not test_rates:
                raise ValueError(
                    "At least one positive frame rate is required."
                )

            if type(include_virtual) is not bool:
                raise ValueError("include_virtual must be a boolean")
            workload = (digiflot.vision.performance_workload()
                        if include_virtual and digiflot.vision is not None else None)
            if include_virtual and workload is None:
                raise ValueError("No saved, calibrated Froth Interface source was found. "
                                 "Configure a camera/cell sensor profile or explicitly uncheck "
                                 "'Include Froth Interface' for a camera-only benchmark.")
            self.state = self.RUNNING
            self.current_rate = None
            self.current_result = None
            self.started_at = _utc_now()
            self.elapsed_s = 0.0
            self.last_error = None
            self.results = []
            self.virtual_sensor = self._virtual_summary(workload)
            self.abort_event.clear()
            self._touch()

            self.benchmark_thread = threading.Thread(
                target=self._benchmark_loop,
                args=(digiflot, test_rates, float(duration_s or self.quick_duration_s), workload),
                daemon=True,
                name="digiflot-performance-benchmark",
            )
            self.benchmark_thread.start()
            return self.status

    def abort_benchmark(self):
        with self.lock:
            if self.state != self.RUNNING:
                return self.status
            self.abort_event.set()
            self.current_result = {
                **(self.current_result or {}),
                "classification": "STOPPING",
                "reason": "Benchmark abort requested. Waiting for camera/FFmpeg cleanup.",
            }
            self._touch()
            return self.status

    def _benchmark_loop(self, digiflot, rates, duration_s, workload=None):
        original_rates = {camera.id: camera.frame_rate for camera in digiflot.cameras.values()}
        signature = self.hardware_signature(digiflot, virtual_sensor=self._virtual_summary(workload))
        benchmark_started = _utc_now()
        all_results = []

        try:
            self.base_dir.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(prefix="benchmark_", dir=self.base_dir) as temporary:
                temporary = Path(temporary)
                for index, rate in enumerate(rates):
                    if self.abort_event.is_set():
                        break

                    result = self._run_rate_test(
                        digiflot,
                        rate,
                        duration_s,
                        temporary,
                        virtual_workload=workload,
                    )
                    all_results.append(result)

                    if result.get("classification") == "FAIL":
                        reason = (
                            f"Not tested because {rate:g} fps failed. "
                            "Higher rates are outside the discovered stable envelope."
                        )
                        for skipped_rate in rates[index + 1:]:
                            all_results.append({
                                "rate": skipped_rate,
                                "camera_rates": {
                                    str(camera.id): float(skipped_rate)
                                    for camera in digiflot.cameras.values()
                                },
                                "classification": "NOT_TESTED",
                                "reason": reason,
                                "duration_s": 0.0,
                                "samples": [],
                                "safety_abort": False,
                            })

                    with self.lock:
                        self.results = deepcopy(all_results)
                        self.current_result = deepcopy(result)
                        self._touch()

                    if result.get("classification") in {
                        "ABORTED",
                        "FAIL",
                    }:
                        break

            if self.abort_event.is_set():
                # Keep partial measurements for diagnostics, but never replace a
                # previously certified profile with an incomplete benchmark.
                record = {
                    "schema_version": 1,
                    "status": "ABORTED",
                    "tested_at": benchmark_started,
                    "completed_at": _utc_now(),
                    "hardware_signature": signature,
                    "virtual_sensor": self._virtual_summary(workload),
                    "results": all_results,
                }
                self._save_history_record(record)
                with self.lock:
                    self.state = self.ABORTED
                    self.current_rate = None
                    self.current_result = {
                        "classification": "ABORTED",
                        "reason": "Benchmark aborted by operator. Saved performance profile was not changed.",
                    }
                    self._touch()
                return

            passes = [item for item in all_results if item.get("classification") == "PASS"]
            stable = [
                item for item in all_results
                if item.get("classification") in {"PASS", "MARGINAL"}
            ]
            recommended = passes[-1].get("camera_rates") if passes else None
            max_stable = stable[-1] if stable else None

            profile = {
                "schema_version": 1,
                "status": "COMPLETED",
                "tested_at": benchmark_started,
                "completed_at": _utc_now(),
                "hardware_signature": signature,
                "virtual_sensor": self._virtual_summary(workload),
                "results": all_results,
                "recommended_camera_rates": recommended,
                "max_stable_camera_rates": max_stable.get("camera_rates") if max_stable else None,
                "health_status": "VALID",
                "health_reason": None,
            }
            self._save_profile(profile)

            with self.lock:
                self.state = self.COMPLETED
                self.current_rate = None
                self.profile = deepcopy(profile)
                self._touch()
        except Exception as error:
            with self.lock:
                self.state = self.FAILED
                self.last_error = str(error)
                self._touch()
        finally:
            for camera in digiflot.cameras.values():
                try:
                    if camera.recording:
                        camera.stop_recording()
                except Exception:
                    pass
                try:
                    camera.config["frame_rate"] = original_rates[camera.id]
                    camera.refresh_from_config()
                except Exception:
                    pass
            with self.lock:
                self.benchmark_thread = None
                self.current_rate = None
                self._touch()

    def _run_rate_test(self, digiflot, rate, duration_s, temporary: Path, virtual_workload=None):
        """Run all physical cameras and the real virtual detector at the same time."""
        started, samples, errors, virtual_samples = [], [], [], []
        camera_rates = {str(camera.id): float(rate) for camera in digiflot.cameras.values()}
        last_camera_metrics, safety_abort = {}, False
        source = virtual_workload["camera"] if virtual_workload else None
        vision = digiflot.vision if virtual_workload else None
        original_analysis = (source.analysis_enabled, source.analysis_target_size) if source else None
        virtual_info = self._virtual_summary(virtual_workload)
        duration = 0.0
        for camera in digiflot.cameras.values():
            try:
                camera.config["frame_rate"] = float(rate)
                camera.refresh_from_config()
                camera.validate_config(camera.config)
            except Exception as error:
                errors.append(f"{camera.name}: {error}")
        if errors:
            return {"rate": rate, "camera_rates": camera_rates, "classification": "FAIL",
                    "reason": "; ".join(errors), "duration_s": 0.0, "samples": [],
                    "virtual_sensor": {"included": bool(source), "configuration": virtual_info},
                    "headroom_risk": self.headroom_risk([]), "safety_abort": False}
        try:
            if source:
                # Disable the independent Vision worker, then configure the same lores
                # resolution that the live virtual sensor requires while the encoders run.
                vision._benchmarking = True
                source.analysis_enabled = True
                source.analysis_target_size = tuple(virtual_workload["lores_size"])
                vision._map_key, vision._roi_map = None, None

            for camera in digiflot.cameras.values():
                rate_label = f"{rate:g}".replace(".", "p")
                output = temporary / f"{rate_label}fps_{camera.id}_{str(camera.name).replace('/', '_')}"
                camera.start_recording(output)
                started.append(camera)

            with self.lock:
                self.current_rate = rate
                self.current_result = {"classification": "RUNNING", "camera_rates": camera_rates,
                                       "virtual_sensor": virtual_info}
                self._touch()

            start_time = time.monotonic()
            sample_due = start_time
            virtual_interval = max(.2, float(virtual_workload["config"]["sampling_interval_s"])) if source else None
            virtual_due = start_time + min(.10, virtual_interval/3) if source else None
            missed_intervals = 0

            while not self.abort_event.is_set():
                now = time.monotonic()
                elapsed = now-start_time
                if elapsed >= duration_s:
                    break
                if source and now >= virtual_due:
                    if now > virtual_due + virtual_interval:
                        missed = int((now-virtual_due)//virtual_interval)
                        missed_intervals += missed
                        virtual_due += missed*virtual_interval
                    try:
                        reading = vision.performance_detection(virtual_workload)
                        virtual_samples.append(reading)
                    except Exception as error:
                        virtual_samples.append({"valid": False, "latency_ms": None, "error": str(error)})
                    virtual_due += virtual_interval

                if now >= sample_due:
                    sample = self.sample_system()
                    camera_metrics = {str(camera.id): camera.recording_metrics() for camera in started}
                    sample["cameras"] = camera_metrics
                    samples.append(sample)
                    last_camera_metrics = deepcopy(camera_metrics)
                    with self.lock:
                        self.elapsed_s = elapsed
                        self.last_sample = sample
                        self._touch()

                    temperature = sample.get("temperature_c")
                    throttled = (sample.get("throttled") or {}).get("current")
                    free_gb = (sample.get("disk") or {}).get("free_gb")
                    memfree = (sample.get("memory") or {}).get("free_pct")
                    dead_ffmpeg = [camera.name for camera in started
                                   if camera.ffmpeg is not None and camera.ffmpeg.poll() is not None]
                    if throttled:
                        errors.append("System throttling was detected.")
                        safety_abort = True
                        break
                    if temperature is not None and temperature >= self.max_temperature_c:
                        errors.append(f"Temperature reached {temperature:.1f} °C.")
                        safety_abort = True
                        break
                    if free_gb is not None and free_gb < self.min_disk_free_gb:
                        errors.append("Disk free space dropped below the safety threshold.")
                        safety_abort = True
                        break
                    if memfree is not None and memfree < 2.:
                        errors.append("Less than 2% of system RAM remains available.")
                        safety_abort = True
                        break
                    if dead_ffmpeg:
                        errors.append("FFmpeg stopped unexpectedly: "+", ".join(dead_ffmpeg))
                        break
                    if elapsed >= 5.:
                        stalled = [camera.name for camera in started
                                   if (camera_metrics[str(camera.id)].get("last_frame_age_s") or 0) > 3.]
                        if stalled:
                            errors.append("Camera output stalled: "+", ".join(stalled))
                            break
                    sample_due += self.sample_interval_s
                next_due = min(sample_due, virtual_due) if source else sample_due
                wait = next_due-time.monotonic()
                if wait > 0:
                    time.sleep(min(.05, wait))
        except Exception as error:
            errors.append(str(error))
        finally:
            if started:
                last_camera_metrics = {str(camera.id): camera.recording_metrics()
                                       for camera in started}
            for camera in started:
                try:
                    camera.stop_recording()
                except Exception as error:
                    errors.append(f"{camera.name}: {error}")
            if source:
                source.analysis_enabled, source.analysis_target_size = original_analysis
                vision._benchmarking = False
                vision._map_key, vision._roi_map = None, None
            if 'start_time' in locals():
                duration = time.monotonic()-start_time

        max_temp = max((s.get("temperature_c") for s in samples
                        if s.get("temperature_c") is not None), default=None)
        max_load1 = max((s.get("load1") for s in samples if s.get("load1") is not None), default=None)
        throttled_seen = any((s.get("throttled") or {}).get("current") for s in samples)
        total_write_rate = sum(float(item.get("write_rate_mbps") or 0.)
                               for item in last_camera_metrics.values())
        low_fps = [cid for cid, metrics in last_camera_metrics.items()
                   if duration >= 5. and float(metrics.get("actual_fps") or 0) < rate*.70]
        if low_fps and not errors:
            errors.append("Sustained encoded FPS fell below 70% for camera(s): "+", ".join(low_fps))

        headroom = self.headroom_risk(samples)
        cpu_free = [float(s["cpu"]["free_pct"]) for s in samples if (s.get("cpu") or {}).get("free_pct") is not None]
        mem_free = [float(s["memory"]["free_pct"]) for s in samples if (s.get("memory") or {}).get("free_pct") is not None]
        virtual_result = {"included": bool(source), "configuration": virtual_info, "samples": len(virtual_samples),
                          "valid_detections": sum(bool(x.get("valid")) for x in virtual_samples),
                          "missed_intervals": missed_intervals}
        if source:
            latencies = sorted(float(s["latency_ms"]) for s in virtual_samples if s.get("latency_ms") is not None)
            timestamps = [s["sensor_timestamp_ns"] for s in virtual_samples
                          if s.get("sensor_timestamp_ns") is not None]
            duplicate_timestamps = len(timestamps)-len(set(timestamps))
            virtual_result.update({"sampling_interval_s": virtual_interval,
                "p95_latency_ms": latencies[min(len(latencies)-1, math.ceil(.95*len(latencies))-1)] if latencies else None,
                "p99_latency_ms": latencies[min(len(latencies)-1, math.ceil(.99*len(latencies))-1)] if latencies else None,
                "errors": [s["error"] for s in virtual_samples if s.get("error")][:5],
                "duplicate_sensor_timestamps": duplicate_timestamps})
            if not virtual_samples:
                errors.append("Froth Interface did not acquire any frames.")
            elif len(latencies) < len(virtual_samples)*.7:
                errors.append("More than 30% of Froth Interface acquisitions failed.")
            elif virtual_result["p99_latency_ms"] >= virtual_interval*1000:
                errors.append("Froth Interface P99 processing latency exceeded its sampling interval.")
            elif duplicate_timestamps:
                errors.append("Froth Interface captured duplicate camera timestamps.")
            elif missed_intervals > max(1, len(virtual_samples)//10):
                errors.append("Froth Interface missed more than 10% of scheduled acquisitions.")

        if self.abort_event.is_set() and not errors:
            classification, reason = "ABORTED", "Benchmark aborted by operator."
        elif errors:
            classification, reason = "FAIL", "; ".join(errors)
        else:
            classification, reason = "PASS", "Both camera encoders and selected vision workload completed."
            if (max_temp is not None and max_temp >= self.max_temperature_c-5 or
                    headroom["low_samples"] > 0 or
                    (source and virtual_result["p95_latency_ms"] is not None and
                     virtual_result["p95_latency_ms"] > virtual_interval*700)):
                classification, reason = "MARGINAL", "Completed, but system headroom, latency or temperature was marginal."

        return {"rate": rate, "camera_rates": camera_rates, "classification": classification,
                "reason": reason, "duration_s": duration, "max_temperature_c": max_temp,
                "max_load1": max_load1, "throttling": throttled_seen,
                "camera_metrics": last_camera_metrics, "write_rate_mbps": total_write_rate,
                "cpu_free_min_pct": min(cpu_free) if cpu_free else None,
                "memory_free_min_pct": min(mem_free) if mem_free else None,
                "headroom_risk": headroom, "virtual_sensor": virtual_result,
                "samples": samples, "safety_abort": safety_abort}

    def mark_degraded(self, reason: str, sample=None):
        with self.lock:
            if not self.profile:
                return
            profile = deepcopy(self.profile)
            profile["health_status"] = "DEGRADED"
            profile["health_reason"] = str(reason)
            profile["degraded_at"] = _utc_now()
            if sample is not None:
                profile["degraded_sample"] = deepcopy(sample)
            _atomic_write_json(self.profile_path, profile)
            self.profile = profile
            self._touch()

    def start_system_monitor(self):
        with self.lock:
            if self.monitor_thread is not None and self.monitor_thread.is_alive():
                return
            self.monitor_stop.clear()
            self.monitor_wake.clear()
            self.monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True,
                                                   name="digiflot-system-monitor")
            self.monitor_thread.start()

    def stop_system_monitor(self):
        self.monitor_stop.set()
        self.monitor_wake.set()
        thread = self.monitor_thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=3.0)
        self.monitor_thread = None

    def update_monitor_settings(self, settings):
        with self.lock:
            self.telemetry_interval_s = float(settings["telemetry_interval_s"])
            self.idle_telemetry_interval_s = float(settings["idle_telemetry_interval_s"])
            self.min_disk_free_gb = float(settings["min_disk_free_gb"])
            self.storage_safety_margin_pct = float(settings["storage_safety_margin_pct"])
            self.config.update(settings)
        self.monitor_wake.set()

    def system_health(self):
        with self.lock:
            sample = deepcopy(self.last_sample)
            return {"system": sample,
                    "telemetry": {"running": self.monitor_thread is not None and self.monitor_thread.is_alive(),
                                  "recording": self.telemetry_path is not None,
                                  "experiment_interval_s": self.telemetry_interval_s,
                                  "idle_interval_s": self.idle_telemetry_interval_s,
                                  "error": self.monitor_error},
                    "min_disk_free_gb": self.min_disk_free_gb,
                    "storage_safety_margin_pct": self.storage_safety_margin_pct}

    @staticmethod
    def _format_telemetry_row(sample):
        throttled = sample.get("throttled") or {}
        disk = sample.get("disk") or {}
        return "\t".join([
            str(sample.get("timestamp") or ""),
            "" if sample.get("temperature_c") is None else f"{sample['temperature_c']:.3f}",
            "" if sample.get("load1") is None else f"{sample['load1']:.3f}",
            "" if sample.get("load5") is None else f"{sample['load5']:.3f}",
            "" if sample.get("load15") is None else f"{sample['load15']:.3f}",
            "1" if throttled.get("current") else "0",
            str(throttled.get("raw") or ""),
            "" if disk.get("free_gb") is None else f"{disk['free_gb']:.3f}",
        ]) + "\n"

    def _append_telemetry(self, sample):
        with self.telemetry_lock:
            path = self.telemetry_path
            if path is None:
                return
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                header_needed = not path.exists() or path.stat().st_size == 0
                with path.open("a", encoding="utf-8") as file:
                    if header_needed:
                        file.write("timestamp\ttemperature_c\tload1\tload5\tload15\tthrottled\tthrottled_raw\tdisk_free_gb\n")
                    file.write(self._format_telemetry_row(sample))
            except OSError as error:
                with self.lock:
                    self.monitor_error = f"System telemetry write failed: {error}"

    def start_experiment_telemetry(self, run_directory: Path, event_callback=None):
        with self.telemetry_lock:
            self.telemetry_path = Path(run_directory) / "system_metrics.tsv"
            self.telemetry_event_callback = event_callback
        with self.lock:
            sample = deepcopy(self.last_sample)
        self._append_telemetry(sample)
        self.monitor_wake.set()

    def stop_experiment_telemetry(self):
        # Called after acquisition stops. Append a final cached measurement,
        # refreshing disk capacity without launching a subprocess.
        with self.lock:
            sample = deepcopy(self.last_sample)
        sample["timestamp"] = _utc_now()
        try:
            usage = shutil.disk_usage(self.base_dir.parent)
            sample["disk"] = {"total_gb": usage.total / 1024**3,
                              "free_gb": usage.free / 1024**3,
                              "used_gb": usage.used / 1024**3}
        except OSError:
            pass
        with self.telemetry_lock:
            if self.telemetry_path is not None:
                self._append_telemetry(sample)
            self.telemetry_path = None
            self.telemetry_event_callback = None
        self.monitor_wake.set()

    def _monitor_loop(self):
        last_warning = None
        while not self.monitor_stop.is_set():
            try:
                sample = self.sample_system()
                with self.lock:
                    self.last_sample = sample
                    self.monitor_error = None
                    self._touch()
                self._append_telemetry(sample)
                throttled = sample.get("throttled") or {}
                free_gb = (sample.get("disk") or {}).get("free_gb")
                warning = None
                if free_gb is not None and free_gb < self.min_disk_free_gb:
                    warning = "Disk free space is below the configured safety threshold."
                elif throttled.get("current"):
                    warning = "System throttling detected during experiment."
                elif sample.get("temperature_c") is not None and sample["temperature_c"] >= self.max_temperature_c:
                    warning = f"System temperature reached {sample['temperature_c']:.1f} °C."
                with self.telemetry_lock:
                    callback = self.telemetry_event_callback
                    recording = self.telemetry_path is not None
                if warning and warning != last_warning and recording and callback is not None:
                    try:
                        callback(warning, sample)
                    except Exception:
                        pass
                last_warning = warning if recording else None
            except Exception as error:
                with self.lock:
                    self.monitor_error = f"System monitor failed: {error}"
            with self.telemetry_lock:
                active = self.telemetry_path is not None
            delay = self.telemetry_interval_s if active else self.idle_telemetry_interval_s
            self.monitor_wake.wait(max(1.0, delay))
            self.monitor_wake.clear()
