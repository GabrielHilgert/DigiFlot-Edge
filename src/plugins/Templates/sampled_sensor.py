"""Reusable, hardware-agnostic sampled sensor template for DigiFlot plugins.

Override read_channels(). Subclasses may add hardware-specific connect/disconnect
operations without changing the DigiFlot API or orchestration.
"""
import csv
import math
import threading
import time
from pathlib import Path


class SampledSensor:
    CHANNELS = {"value": ""}
    PRIMARY = "value"

    def __init__(self, id, name="Plugin sensor", sample_interval=1.0, **_):
        self.id, self.name = str(id), str(name)
        self.sample_interval = max(0.2, float(sample_interval))
        self.running = self.recording = self.writer_active = False
        self.status, self.error, self.timestamp_ns = "stopped", None, None
        self.sample_count = self.revision = 0
        self.channels = {}
        self._condition = threading.Condition(threading.RLock())
        self._stop_event = threading.Event()
        self._thread = self._file = self._writer = None
        self._context = lambda: {}

    def set_context_provider(self, provider):
        self._context = provider

    def read_channels(self):
        """Override with one sampling operation; return {channel: float}."""
        raise NotImplementedError

    def start(self):
        if self.running:
            return
        self._stop_event.clear()
        self.running = True
        self._thread = threading.Thread(target=self._loop, daemon=True, name=f"plugin-{self.id}")
        self._thread.start()

    def stop(self):
        self._stop_event.set()
        self.running = False
        if self._thread is not None and self._thread is not threading.current_thread():
            self._thread.join(timeout=3)
        self.stop_recording()
        with self._condition:
            self.status = "stopped"
            self.revision += 1
            self._condition.notify_all()

    def _loop(self):
        while not self._stop_event.is_set():
            try:
                values = self.read_channels()
                if not isinstance(values, dict) or not values:
                    raise ValueError("read_channels() must return a nonempty dictionary")
                channels = {key: float(value) for key, value in values.items() if key in self.CHANNELS}
                if self.PRIMARY not in channels or any(not math.isfinite(v) for v in channels.values()):
                    raise ValueError("Invalid or missing primary measurement")
                context = dict(self._context() or {})
                now = time.time_ns()
                with self._condition:
                    self.channels, self.status, self.error = channels, "connected", None
                    self.sample_count += 1
                    self.revision += 1
                    self.timestamp_ns = now
                    if self._writer:
                        self._writer.writerow({"timestamp_ns": now,
                            "run_elapsed_s": context.get("run_elapsed_s"),
                            "digiflot_state": context.get("digiflot_state"),
                            "stage_id": context.get("stage_id"),
                            "stage_attempt": context.get("stage_attempt"),
                            **channels})
                        self._file.flush()
                    self._condition.notify_all()
            except Exception as error:
                with self._condition:
                    self.status, self.error = "offline", str(error)
                    self.channels = {}
                    self.revision += 1
                    self._condition.notify_all()
            self._stop_event.wait(self.sample_interval)

    def snapshot(self):
        with self._condition:
            value = self.channels.get(self.PRIMARY)
            return {"id": self.id, "name": self.name, "source": "plugin",
                "type": "plugin_sensor", "status": self.status,
                "value": value, "unit": self.CHANNELS.get(self.PRIMARY, ""),
                "decimals": 2, "channels": dict(self.channels),
                "timestamp_ns": self.timestamp_ns,
                "timestamp_ms": self.timestamp_ns // 1000000 if self.timestamp_ns else None,
                "sample_count": self.sample_count, "revision": self.revision,
                "recording": self.recording, "error": self.error}

    def wait_for_update(self, last_revision, timeout=5.0):
        with self._condition:
            self._condition.wait_for(lambda: self.revision != last_revision, timeout=timeout)
        return self.snapshot()

    def start_recording(self, output_dir=None, file_stem=None):
        with self._condition:
            if self.recording:
                return Path(self._file.name)
            folder = Path(output_dir or "./data/plugins")
            folder.mkdir(parents=True, exist_ok=True)
            path = folder / f"{file_stem or self.id}.tsv"
            self._file = path.open("w", encoding="utf-8", newline="")
            fields = ["timestamp_ns", "run_elapsed_s", "digiflot_state",
                      "stage_id", "stage_attempt", *self.CHANNELS]
            self._writer = csv.DictWriter(self._file, fieldnames=fields, delimiter="\t",
                                          extrasaction="ignore")
            self._writer.writeheader()
            self.recording = self.writer_active = True
            return path

    def stop_recording(self):
        with self._condition:
            self.recording = self.writer_active = False
            self._writer = None
            if self._file is not None:
                self._file.close()
                self._file = None
