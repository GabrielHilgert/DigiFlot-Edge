import re
import time
import threading
from pathlib import Path

import serial
from serial.tools import list_ports


_VALUE_PATTERN = re.compile(
    r"(?P<value>[+-]?\s*\d+(?:[.,]\d+)?)\s*(?P<unit>[a-zA-Zµμ%]+)?"
)


class Scale:
    @staticmethod
    def _is_weight_unit(unit):
        unit = str(unit or "").strip().lower().replace("μ", "µ")
        return unit in {"g", "kg", "mg"}

    @classmethod
    def discover_available(
        cls,
        configured_ports=None,
        runtime_scales=None,
        baudrate=9600,
        probe_seconds=1.0,
    ):
        """Enumerate serial ports and conservatively identify scales.

        ``serial_detected`` only means that the operating system exposes the
        serial port. ``scale_detected`` requires actual scale evidence.
        Configured ports that are already opened by DigiFlot are inspected
        through their runtime Scale object and are never reopened here.
        Unknown ports are observed passively; no command is sent.
        """
        configured_ports = {str(value) for value in (configured_ports or [])}
        runtime_scales = {
            str(port): scale
            for port, scale in (runtime_scales or {}).items()
        }
        devices = []

        for port in list_ports.comports():
            device = str(port.device)
            runtime_scale = runtime_scales.get(device)
            item = {
                "port": device,
                "configured": device in configured_ports,
                "serial_detected": True,
                "scale_detected": False,
                # Backward-compatible field: for scales, detected means that
                # the device was confirmed as a scale, not merely a serial port.
                "detected": False,
                "probable_scale": False,
                "description": port.description,
                "manufacturer": port.manufacturer,
                "vid": port.vid,
                "pid": port.pid,
                "serial_number": port.serial_number,
                "sample": None,
                "runtime_status": None,
                "evidence": None,
                "error": None,
            }

            if runtime_scale is not None:
                try:
                    snapshot = runtime_scale.snapshot()
                    item["runtime_status"] = snapshot.get("status")
                    item["sample"] = snapshot.get("raw")
                    unit = snapshot.get("unit")
                    if snapshot.get("value") is not None and cls._is_weight_unit(unit):
                        item["scale_detected"] = True
                        item["probable_scale"] = True
                        item["detected"] = True
                        item["evidence"] = f"Live weight data ({unit})"
                    elif snapshot.get("status") in {"offline", "error"}:
                        item["error"] = snapshot.get("error")
                    else:
                        item["evidence"] = "Serial port is open, but no weight-formatted sample has been received yet."
                except Exception as error:
                    item["error"] = str(error)

                devices.append(item)
                continue

            handle = None
            weighted_samples = 0
            deadline = time.monotonic() + max(0.2, float(probe_seconds))
            try:
                handle = serial.Serial(
                    port=device,
                    baudrate=int(baudrate),
                    timeout=0.2,
                )
                while time.monotonic() < deadline and weighted_samples < 2:
                    raw = handle.readline()
                    if not raw:
                        continue
                    text = raw.decode("ascii", errors="ignore").strip()
                    if not text:
                        continue
                    item["sample"] = text
                    match = _VALUE_PATTERN.search(text)
                    if match is None:
                        continue
                    unit = match.group("unit")
                    if cls._is_weight_unit(unit):
                        weighted_samples += 1

                # Be deliberately conservative. A random serial stream that
                # contains plain numbers is not enough to call it a scale.
                item["scale_detected"] = weighted_samples >= 2
                item["probable_scale"] = item["scale_detected"]
                item["detected"] = item["scale_detected"]
                if item["scale_detected"]:
                    item["evidence"] = f"{weighted_samples} weight-formatted samples"
                else:
                    item["evidence"] = "Serial device detected; no confirmed weight stream."
            except Exception as error:
                item["error"] = str(error)
            finally:
                if handle is not None:
                    try:
                        handle.close()
                    except Exception:
                        pass

            devices.append(item)

        return devices

    @staticmethod
    def config_from_detection(item, sensor_id, name=None):
        return {
            "id": str(sensor_id),
            "name": str(name or sensor_id),
            "port": str(item["port"]),
            "baudrate": 9600,
            "timeout": 1.0,
            "encoding": "ascii",
            "output_dir": "./data/scales",
            "buffer_size": 100,
            "flush_interval": 5.0,
        }

    def __init__(
        self,
        port,
        sensor_id=None,
        name=None,
        baudrate=9600,
        timeout=1.0,
        encoding="ascii",
        output_dir="./data",
        buffer_size=100,
        flush_interval=5.0,
    ):
        self.port = port
        self.id = sensor_id if sensor_id is not None else port
        self.name = name if name is not None else port

        self.baudrate = baudrate
        self.timeout = timeout
        self.encoding = encoding

        self.output_dir = Path(output_dir)
        self.buffer_size = buffer_size
        self.flush_interval = flush_interval

        self.serial = None
        self.thread = None
        self.stop_event = threading.Event()
        self.condition = threading.Condition()

        self.running = False
        self.recording = False
        self.writer_active = False

        self.output_path = None
        self.error = None

        self.latest_raw = None
        self.latest_value = None
        self.latest_unit = None
        self.latest_timestamp_ns = None

        self.sample_count = 0
        self.recorded_sample_count = 0
        self.revision = 0
        self.context_provider = None

    def set_context_provider(self, provider):
        """Attach a lightweight callback that supplies experiment context."""
        self.context_provider = provider

    def acquisition_context(self):
        if self.context_provider is None:
            return {}
        try:
            return dict(self.context_provider() or {})
        except Exception:
            return {}

    @staticmethod
    def context_value(context, key):
        value = context.get(key)
        return "" if value is None else str(value)

    @classmethod
    def from_config(cls, config):
        return cls(
            port=config["port"],
            sensor_id=config.get("id"),
            name=config.get("name"),
            baudrate=config.get("baudrate", 9600),
            timeout=config.get("timeout", 1.0),
            encoding=config.get("encoding", "ascii"),
            output_dir=config.get("output_dir", "./data"),
            buffer_size=config.get("buffer_size", 100),
            flush_interval=config.get("flush_interval", 5.0),
        )

    def export_config(self):
        return {
            "id": self.id,
            "port": self.port,
            "name": self.name,
            "baudrate": self.baudrate,
            "timeout": self.timeout,
            "encoding": self.encoding,
            "output_dir": str(self.output_dir),
            "buffer_size": self.buffer_size,
            "flush_interval": self.flush_interval,
        }

    def start(self):
        """
        Start serial monitoring only.

        This does not create or write a TSV file. Disk recording is
        explicitly controlled with start_recording()/stop_recording().
        """
        with self.condition:
            if self.running:
                return

            self.stop_event.clear()
            self.error = None
            self.running = True
            self.revision += 1
            self.condition.notify_all()

        self.thread = threading.Thread(
            target=self.read_loop,
            daemon=True,
            name=f"scale-{self.id}",
        )
        self.thread.start()

    def stop(self):
        if not self.running:
            return

        self.stop_recording()

        with self.condition:
            self.stop_event.set()

        if self.thread is not None:
            self.thread.join()

        self.thread = None

    def start_recording(
        self,
        output_dir=None,
        file_stem=None,
    ):
        """
        Begin writing incoming samples to a TSV file.

        The serial monitor must already be running. If output_dir is not
        supplied, the configured output_dir is used.
        """
        with self.condition:
            if not self.running:
                raise RuntimeError(
                    f"Scale '{self.name}' is not running."
                )

            if self.recording:
                return self.output_path

            directory = (
                Path(output_dir)
                if output_dir is not None
                else self.output_dir
            )

            directory.mkdir(
                parents=True,
                exist_ok=True,
            )

            if file_stem is None:
                safe_name = re.sub(
                    r"[^a-zA-Z0-9_-]",
                    "_",
                    self.name,
                )

                timestamp = time.strftime(
                    "%Y%m%d-%H%M%S"
                )

                file_stem = (
                    f"{timestamp}_{safe_name}"
                )

            self.output_path = (
                directory
                / f"{file_stem}.tsv"
            )

            self.recorded_sample_count = 0
            self.recording = True
            self.revision += 1
            self.condition.notify_all()

            return self.output_path

    def stop_recording(self):
        """Stop disk recording while keeping serial monitoring active."""
        with self.condition:
            if not self.recording and not self.writer_active:
                return

            self.recording = False
            self.revision += 1
            self.condition.notify_all()

            self.condition.wait_for(
                lambda: not self.writer_active,
                timeout=max(
                    2.0,
                    self.timeout + 1.0,
                ),
            )

    def parse_value(self, raw_value):
        match = _VALUE_PATTERN.search(raw_value)

        if match is None:
            return None, None

        value_text = (
            match.group("value")
            .replace(" ", "")
            .replace(",", ".")
        )

        try:
            value = float(value_text)
        except ValueError:
            value = None

        return value, match.group("unit")

    def snapshot(self):
        with self.condition:
            return self._snapshot_unlocked()

    def wait_for_update(
        self,
        last_revision,
        timeout=5.0,
    ):
        with self.condition:
            self.condition.wait_for(
                lambda: self.revision != last_revision,
                timeout=timeout,
            )

            return self._snapshot_unlocked()

    def _snapshot_unlocked(self):
        serial_open = (
            self.serial is not None
            and getattr(
                self.serial,
                "is_open",
                False,
            )
        )

        if self.error and not serial_open:
            status = "offline"
        elif self.error:
            status = "error"
        elif serial_open:
            status = "connected"
        elif self.running:
            status = "starting"
        else:
            status = "stopped"

        timestamp_ms = None

        if self.latest_timestamp_ns is not None:
            timestamp_ms = (
                self.latest_timestamp_ns
                // 1_000_000
            )

        return {
            "revision": self.revision,
            "id": self.id,
            "type": "scale",
            "name": self.name,
            "status": status,
            "running": self.running,
            "recording": self.recording,
            "port": self.port,
            "baudrate": self.baudrate,
            "value": self.latest_value,
            "unit": self.latest_unit,
            "raw": self.latest_raw,
            "timestamp_ns": (
                str(self.latest_timestamp_ns)
                if self.latest_timestamp_ns is not None
                else None
            ),
            "timestamp_ms": timestamp_ms,
            "sample_count": self.sample_count,
            "recorded_sample_count": (
                self.recorded_sample_count
            ),
            "output_path": (
                str(self.output_path)
                if self.output_path is not None
                else None
            ),
            "error": self.error,
        }

    def read_loop(self):
        file = None
        buffer = []
        last_flush = time.monotonic()
        active_output_path = None

        try:
            self.serial = serial.Serial(
                port=self.port,
                baudrate=self.baudrate,
                timeout=self.timeout,
            )

            with self.condition:
                self.revision += 1
                self.condition.notify_all()

            while not self.stop_event.is_set():
                # Recording can be stopped while monitoring continues.
                if file is not None and not self.recording:
                    if buffer:
                        file.writelines(buffer)
                        buffer.clear()

                    file.close()
                    file = None
                    active_output_path = None

                    with self.condition:
                        self.writer_active = False
                        self.revision += 1
                        self.condition.notify_all()

                raw = self.serial.readline()

                if not raw:
                    continue

                raw_value = raw.decode(
                    self.encoding,
                    errors="replace",
                ).strip()

                if not raw_value:
                    continue

                timestamp_ns = time.time_ns()
                value, unit = self.parse_value(
                    raw_value
                )

                with self.condition:
                    self.latest_raw = raw_value
                    self.latest_value = value
                    self.latest_unit = unit
                    self.latest_timestamp_ns = (
                        timestamp_ns
                    )
                    self.sample_count += 1
                    self.revision += 1
                    self.condition.notify_all()

                if not self.recording:
                    continue

                if (
                    file is None
                    or active_output_path != self.output_path
                ):
                    if file is not None:
                        if buffer:
                            file.writelines(buffer)
                            buffer.clear()

                        file.close()

                    active_output_path = self.output_path

                    file = active_output_path.open(
                        "a",
                        encoding="ascii",
                        buffering=1024 * 1024,
                    )

                    buffer = []
                    last_flush = time.monotonic()

                    if file.tell() == 0:
                        file.write(
                            "timestamp_ns\tmonotonic_ns\trun_elapsed_s\t"
                            "digiflot_state\tstage_state\tstage_id\tstage_attempt\t"
                            "previous_stage_id\tnext_stage_id\tvalue\n"
                        )

                    with self.condition:
                        self.writer_active = True
                        self.revision += 1
                        self.condition.notify_all()

                context = self.acquisition_context()
                buffer.append(
                    "\t".join([
                        str(timestamp_ns),
                        self.context_value(context, "monotonic_ns"),
                        self.context_value(context, "run_elapsed_s"),
                        self.context_value(context, "digiflot_state"),
                        self.context_value(context, "stage_state"),
                        self.context_value(context, "stage_id"),
                        self.context_value(context, "stage_attempt"),
                        self.context_value(context, "previous_stage_id"),
                        self.context_value(context, "next_stage_id"),
                        raw_value,
                    ]) + "\n"
                )

                with self.condition:
                    self.recorded_sample_count += 1

                now = time.monotonic()

                if (
                    len(buffer) >= self.buffer_size
                    or now - last_flush
                    >= self.flush_interval
                ):
                    file.writelines(buffer)
                    buffer.clear()
                    last_flush = now

        except Exception as error:
            with self.condition:
                self.error = str(error)
                self.revision += 1
                self.condition.notify_all()

        finally:
            if file is not None:
                if buffer:
                    file.writelines(buffer)

                file.close()

            if self.serial is not None:
                self.serial.close()
                self.serial = None

            with self.condition:
                self.recording = False
                self.writer_active = False
                self.running = False
                self.revision += 1
                self.condition.notify_all()
