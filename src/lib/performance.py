import json
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
        self.telemetry_interval_s = max(1.0, float(self.config.get("telemetry_interval_s", 5.0)))
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
        self.abort_event = threading.Event()
        self.benchmark_thread = None

        self.telemetry_stop = threading.Event()
        self.telemetry_thread = None
        self.telemetry_path = None
        self.telemetry_event_callback = None
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
        try:
            result = subprocess.run(
                ["vcgencmd", "measure_temp"],
                capture_output=True,
                text=True,
                timeout=1.0,
                check=False,
            )
            text = result.stdout.strip()
            if "=" in text:
                return float(text.split("=", 1)[1].split("'", 1)[0])
        except Exception:
            pass

        thermal = Path("/sys/class/thermal/thermal_zone0/temp")
        try:
            return float(thermal.read_text(encoding="utf-8").strip()) / 1000.0
        except Exception:
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

        return {
            "timestamp": _utc_now(),
            "temperature_c": self._read_temperature(),
            "throttled": self._read_throttled(),
            "load1": load1,
            "load5": load5,
            "load15": load15,
            "cpu_count": os.cpu_count() or 1,
            "disk": disk,
        }

    def hardware_signature(self, digiflot, config_overrides=None):
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
        return {"cameras": cameras}

    def current_camera_rates(self, digiflot, overrides=None):
        overrides = overrides or {}
        rates = {}
        for camera in digiflot.cameras.values():
            rates[str(camera.id)] = float(overrides.get(str(camera.id), overrides.get(camera.id, camera.frame_rate)))
        return rates

    def evaluate(self, digiflot, overrides=None, config_overrides=None):
        try:
            signature = self.hardware_signature(
                digiflot,
                config_overrides=config_overrides,
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
            self.last_sample = self.sample_system()
            return {
                "revision": self.revision,
                "state": self.state,
                "current_rate": self.current_rate,
                "current_result": deepcopy(self.current_result),
                "started_at": self.started_at,
                "elapsed_s": self.elapsed_s,
                "last_error": self.last_error,
                "results": deepcopy(self.results),
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

    def start_benchmark(self, digiflot, rates=None, duration_s=None):
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

            self.state = self.RUNNING
            self.current_rate = None
            self.current_result = None
            self.started_at = _utc_now()
            self.elapsed_s = 0.0
            self.last_error = None
            self.results = []
            self.abort_event.clear()
            self._touch()

            self.benchmark_thread = threading.Thread(
                target=self._benchmark_loop,
                args=(digiflot, test_rates, float(duration_s or self.quick_duration_s)),
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

    def _benchmark_loop(self, digiflot, rates, duration_s):
        original_rates = {camera.id: camera.frame_rate for camera in digiflot.cameras.values()}
        signature = self.hardware_signature(digiflot)
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

    def _run_rate_test(self, digiflot, rate, duration_s, temporary: Path):
        started = []
        samples = []
        errors = []
        start_time = time.monotonic()
        camera_rates = {}
        safety_abort = False
        last_camera_metrics = {}

        for camera in digiflot.cameras.values():
            camera_rates[str(camera.id)] = float(rate)
            try:
                camera.config["frame_rate"] = float(rate)
                camera.refresh_from_config()
                camera.validate_config(camera.config)
            except Exception as error:
                errors.append(f"{camera.name}: {error}")

        if errors:
            return {
                "rate": rate,
                "camera_rates": camera_rates,
                "classification": "FAIL",
                "reason": "; ".join(errors),
                "duration_s": 0.0,
                "samples": [],
                "safety_abort": False,
            }

        try:
            for camera in digiflot.cameras.values():
                rate_label = f"{rate:g}".replace(".", "p")
                output = temporary / (
                    f"{rate_label}fps_{camera.id}_"
                    f"{str(camera.name).replace('/', '_')}"
                )
                camera.start_recording(output)
                started.append(camera)

            with self.lock:
                self.current_rate = rate
                self.current_result = {"classification": "RUNNING", "camera_rates": camera_rates}
                self._touch()

            next_sample = start_time
            while not self.abort_event.is_set():
                now = time.monotonic()
                elapsed = now - start_time
                if elapsed >= duration_s:
                    break
                if now < next_sample:
                    time.sleep(min(0.1, next_sample - now))
                    continue

                sample = self.sample_system()
                samples.append(sample)
                with self.lock:
                    self.elapsed_s = elapsed
                    self.last_sample = sample
                    self._touch()

                temperature = sample.get("temperature_c")
                throttled = (sample.get("throttled") or {}).get("current")
                free_gb = (sample.get("disk") or {}).get("free_gb")
                dead_ffmpeg = [
                    camera.name for camera in started
                    if camera.ffmpeg is not None and camera.ffmpeg.poll() is not None
                ]
                camera_metrics = {
                    str(camera.id): camera.recording_metrics()
                    for camera in started
                }
                last_camera_metrics = deepcopy(camera_metrics)
                sample["cameras"] = camera_metrics
                if throttled:
                    errors.append("System throttling was detected.")
                    safety_abort = True
                    break
                if temperature is not None and temperature >= self.max_temperature_c:
                    errors.append(f"Temperature reached {temperature:.1f} °C.")
                    safety_abort = True
                    break
                if free_gb is not None and free_gb < self.min_disk_free_gb:
                    errors.append("Disk free space dropped below the configured safety threshold.")
                    safety_abort = True
                    break
                if dead_ffmpeg:
                    errors.append("FFmpeg stopped unexpectedly: " + ", ".join(dead_ffmpeg))
                    break
                if elapsed >= 5.0:
                    stalled = [
                        camera.name for camera in started
                        if (camera_metrics[str(camera.id)].get("last_frame_age_s") or 0) > 3.0
                    ]
                    if stalled:
                        errors.append("Camera output stalled: " + ", ".join(stalled))
                        break

                next_sample += self.sample_interval_s
        except Exception as error:
            errors.append(str(error))
        finally:
            if started:
                last_camera_metrics = {
                    str(camera.id): camera.recording_metrics()
                    for camera in started
                }
            stop_errors = []
            for camera in started:
                try:
                    camera.stop_recording()
                except Exception as error:
                    stop_errors.append(f"{camera.name}: {error}")
            errors.extend(stop_errors)

        duration = time.monotonic() - start_time
        max_temp = max((s.get("temperature_c") for s in samples if s.get("temperature_c") is not None), default=None)
        max_load1 = max((s.get("load1") for s in samples if s.get("load1") is not None), default=None)
        throttled_seen = any((s.get("throttled") or {}).get("current") for s in samples)
        final_camera_metrics = last_camera_metrics
        total_write_rate = sum(
            float(item.get("write_rate_mbps") or 0.0)
            for item in final_camera_metrics.values()
        )

        low_fps = [
            camera_id for camera_id, metrics in final_camera_metrics.items()
            if duration >= 5.0 and float(metrics.get("actual_fps") or 0.0) < float(rate) * 0.70
        ]
        if low_fps and not errors:
            errors.append(
                "Sustained encoded frame rate fell below 70% of target for camera(s): "
                + ", ".join(low_fps)
            )

        if self.abort_event.is_set() and not errors:
            classification = "ABORTED"
            reason = "Benchmark aborted by operator."
        elif errors:
            classification = "FAIL"
            reason = "; ".join(errors)
        else:
            classification = "PASS"
            reason = "Completed without throttling or acquisition errors."
            if max_temp is not None and max_temp >= self.max_temperature_c - 5.0:
                classification = "MARGINAL"
                reason = "Completed, but temperature approached the configured safety limit."

        return {
            "rate": rate,
            "camera_rates": camera_rates,
            "classification": classification,
            "reason": reason,
            "duration_s": duration,
            "max_temperature_c": max_temp,
            "max_load1": max_load1,
            "throttling": throttled_seen,
            "camera_metrics": final_camera_metrics,
            "write_rate_mbps": total_write_rate,
            "samples": samples,
            "safety_abort": safety_abort,
        }

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

    def start_experiment_telemetry(self, run_directory: Path, event_callback=None):
        self.stop_experiment_telemetry()
        self.telemetry_path = Path(run_directory) / "system_metrics.tsv"
        self.telemetry_event_callback = event_callback
        self.telemetry_stop.clear()
        self.telemetry_thread = threading.Thread(
            target=self._telemetry_loop,
            daemon=True,
            name="digiflot-system-telemetry",
        )
        self.telemetry_thread.start()

    def stop_experiment_telemetry(self):
        self.telemetry_stop.set()
        thread = self.telemetry_thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=2.0)
        self.telemetry_thread = None
        self.telemetry_path = None
        self.telemetry_event_callback = None

    def _telemetry_loop(self):
        path = self.telemetry_path
        if path is None:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        header_needed = not path.exists()
        last_warning = None
        try:
            with path.open("a", encoding="utf-8") as file:
                if header_needed:
                    file.write("timestamp\ttemperature_c\tload1\tload5\tload15\tthrottled\tthrottled_raw\tdisk_free_gb\n")
                while not self.telemetry_stop.wait(self.telemetry_interval_s):
                    sample = self.sample_system()
                    with self.lock:
                        self.last_sample = deepcopy(sample)
                        self._touch()
                    throttled = sample.get("throttled") or {}
                    disk = sample.get("disk") or {}
                    file.write("\t".join([
                        str(sample.get("timestamp") or ""),
                        "" if sample.get("temperature_c") is None else f"{sample['temperature_c']:.3f}",
                        "" if sample.get("load1") is None else f"{sample['load1']:.3f}",
                        "" if sample.get("load5") is None else f"{sample['load5']:.3f}",
                        "" if sample.get("load15") is None else f"{sample['load15']:.3f}",
                        "1" if throttled.get("current") else "0",
                        str(throttled.get("raw") or ""),
                        "" if disk.get("free_gb") is None else f"{disk['free_gb']:.3f}",
                    ]) + "\n")
                    file.flush()

                    warning = None
                    if throttled.get("current"):
                        warning = "System throttling detected during experiment."
                    elif sample.get("temperature_c") is not None and sample["temperature_c"] >= self.max_temperature_c:
                        warning = f"System temperature reached {sample['temperature_c']:.1f} °C."
                    elif disk.get("free_gb") is not None and disk["free_gb"] < self.min_disk_free_gb:
                        warning = "Disk free space is below the configured safety threshold."

                    if warning and warning != last_warning and self.telemetry_event_callback:
                        try:
                            self.telemetry_event_callback(warning, sample)
                        except Exception:
                            pass
                    last_warning = warning
        except Exception:
            return
