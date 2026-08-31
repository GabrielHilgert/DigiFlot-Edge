import fcntl
import os
import re
import threading
import time
from pathlib import Path


class AtlasScientific:
    I2C_SLAVE = 0x0703
    READ_DELAY = {"pH": 0.9, "ORP": 0.9, "EC": 0.6, "RTD": 0.6}
    DEFAULT_UNIT = {"pH": "pH", "ORP": "mV", "EC": "µS/cm", "RTD": "°C"}
    DEFAULT_DECIMALS = {"pH": 3, "ORP": 1, "EC": 1, "RTD": 2}
    DEFAULT_SENSORS = [
        {"name": "ORP", "type": "ORP", "address": 98},
        {"name": "pH", "type": "pH", "address": 99},
        {"name": "EC", "type": "EC", "address": 100},
        {"name": "RTD", "type": "RTD", "address": 102},
    ]

    def __init__(
        self,
        bus=1,
        name="Atlas",
        sensors=None,
        sample_interval=1.0,
        output_dir="./data",
        buffer_size=100,
        flush_interval=5.0,
    ):
        self.bus = int(bus)
        self.name = name
        self.sensors = [
            dict(sensor)
            for sensor in (self.DEFAULT_SENSORS if sensors is None else sensors)
        ]
        self.sample_interval = float(sample_interval)
        self.output_dir = Path(output_dir)
        self.buffer_size = int(buffer_size)
        self.flush_interval = float(flush_interval)

        self.connected_sensors = []
        self.latest = {}
        self.latest_raw = {}
        self.latest_timestamp_ns = {}
        self.sample_count = {}
        self.revision = {}
        self.sensor_errors = {}

        self.output_path = None
        self.running = False
        self.recording = False
        self.writer_active = False
        self.error = None

        self.fd = None
        self.thread = None
        self.stop_event = threading.Event()
        self.condition = threading.Condition()
        self.io_lock = threading.RLock()
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
        return cls(**config)

    def export_config(self):
        return {
            "bus": self.bus,
            "name": self.name,
            "sensors": self.sensors,
            "sample_interval": self.sample_interval,
            "output_dir": str(self.output_dir),
            "buffer_size": self.buffer_size,
            "flush_interval": self.flush_interval,
        }

    @staticmethod
    def sensor_id(sensor):
        return f'atlas-{int(sensor["address"])}'

    def open(self):
        if self.fd is None:
            self.fd = os.open(f"/dev/i2c-{self.bus}", os.O_RDWR)

    def close(self):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None

    def _write(self, address, command):
        fcntl.ioctl(self.fd, self.I2C_SLAVE, int(address))
        os.write(self.fd, command.encode("ascii") + b"\x00")

    def _read(self, address, size=32):
        fcntl.ioctl(self.fd, self.I2C_SLAVE, int(address))
        raw = os.read(self.fd, size)
        if not raw:
            return 255, ""

        data = bytes(value & 0x7F for value in raw[1:]).split(b"\x00", 1)[0]
        return raw[0], data.decode("ascii", errors="replace").strip()

    def _sensor(self, sensor):
        # Always search the configured sensor list. This keeps configured
        # sensors addressable even when one or more devices are offline.
        for device in self.sensors:
            if sensor in (
                device.get("name"),
                device.get("type"),
                device.get("address"),
                self.sensor_id(device),
            ):
                return device
        raise KeyError(f"Sensor not configured: {sensor}")

    def query(self, sensor, command, delay=None):
        """Send an EZO command safely while live monitoring is running."""
        device = self._sensor(sensor)

        with self.io_lock:
            self.open()
            self._write(device["address"], command)

            if command.lower() == "sleep":
                return None

            if delay is None:
                upper = command.upper()
                delay = (
                    self.READ_DELAY.get(device.get("type"), 0.9)
                    if upper.startswith(("R", "CAL"))
                    else 1.0 if upper.startswith("FACTORY")
                    else 0.3
                )

            time.sleep(delay)
            code, response = self._read(device["address"])

        if code == 1:
            return response
        if code == 254:
            raise TimeoutError("Atlas device is still processing.")
        if code == 2:
            raise ValueError("Atlas device reported a syntax error.")
        raise OSError(f"Atlas response code: {code}")

    def calibrate_ph(self, sensor, point, value):
        point = str(point).strip().lower()
        if point not in {"mid", "low", "high"}:
            raise ValueError("pH calibration point must be mid, low, or high.")

        device = self._sensor(sensor)
        if str(device.get("type", "")).lower() != "ph":
            raise ValueError("Software two-point calibration is only enabled for pH sensors.")

        value = float(value)
        self.query(sensor, f"Cal,{point},{value:g}", delay=0.9)
        return {
            "point": point,
            "value": value,
        }

    def discover_available(self, addresses=None):
        """Identify Atlas EZO circuits at known/configured addresses.

        The scan uses the same I²C lock as live monitoring, so it does not mix
        identification replies with measurement replies. It does not modify the
        configured sensor list.
        """
        if addresses is None:
            addresses = [item["address"] for item in self.DEFAULT_SENSORS]
            addresses.extend(item["address"] for item in self.sensors)
        addresses = sorted({int(address) for address in addresses})

        configured_addresses = {int(sensor["address"]) for sensor in self.sensors}
        found = []
        self.open()

        for address in addresses:
            try:
                with self.io_lock:
                    self._write(address, "i")
                    time.sleep(0.3)
                    code, response = self._read(address)
            except OSError:
                continue

            if code != 1 or not response.lower().startswith("?i,"):
                continue

            parts = response.split(",")
            sensor_type = parts[1] if len(parts) > 1 else "EZO"
            found.append({
                "address": address,
                "type": sensor_type,
                "name": sensor_type,
                "configured": address in configured_addresses,
                "detected": True,
                "response": response,
            })

        return found

    @classmethod
    def discover_bus(cls, bus=1, addresses=None):
        # An unconfigured bus scan must not mark the default EZO addresses as
        # configured. The caller decides configuration from config.json.
        probe = cls(bus=bus, sensors=[])
        try:
            return probe.discover_available(addresses=addresses)
        finally:
            probe.close()

    @staticmethod
    def sensor_config_from_detection(item):
        sensor_type = str(item.get("type") or "EZO")
        return {
            "name": sensor_type,
            "type": sensor_type,
            "address": int(item["address"]),
        }

    def detect(self):
        self.open()
        found = []

        for configured in self.sensors:
            device = dict(configured)
            address = int(device["address"])

            try:
                with self.io_lock:
                    self._write(address, "i")
                    time.sleep(0.3)
                    code, response = self._read(address)
            except OSError:
                continue

            if code != 1 or not response.lower().startswith("?i,"):
                continue

            parts = response.split(",")
            if len(parts) > 1:
                device["type"] = parts[1]

            device.setdefault("name", device.get("type", str(address)))
            device["address"] = address
            found.append(device)

        with self.condition:
            self.connected_sensors = found
            for sensor in self.sensors:
                address = int(sensor["address"])
                self.revision.setdefault(address, 0)
                self.sample_count.setdefault(address, 0)
            self.condition.notify_all()

        return [dict(sensor) for sensor in found]

    def start(self):
        if self.running:
            return

        self.error = None
        sensors = self.detect()
        if not sensors:
            self.close()
            raise RuntimeError("No configured Atlas Scientific EZO sensors found.")

        minimum = max(self.READ_DELAY.get(sensor.get("type"), 0.9) for sensor in sensors)
        if self.sample_interval < minimum:
            self.close()
            raise ValueError(f"sample_interval must be >= {minimum:.1f} s")

        self.stop_event.clear()
        self.running = True
        self.thread = threading.Thread(
            target=self._read_loop,
            daemon=True,
            name="atlas-scientific",
        )
        self.thread.start()

    def stop(self):
        if not self.running:
            self.close()
            return

        self.stop_recording()
        self.stop_event.set()
        if self.thread is not None:
            self.thread.join()
        self.thread = None
        self.running = False
        self.close()

    def start_recording(self, output_dir=None, file_stem=None):
        if not self.running:
            raise RuntimeError("Atlas Scientific acquisition is not running.")

        with self.condition:
            if self.recording:
                return self.output_path

            directory = Path(output_dir) if output_dir is not None else self.output_dir
            directory.mkdir(parents=True, exist_ok=True)

            if file_stem is None:
                safe_name = re.sub(r"[^a-zA-Z0-9_-]", "_", self.name)
                file_stem = f"{time.strftime('%Y%m%d-%H%M%S')}_{safe_name}"

            self.output_path = directory / f"{file_stem}.tsv"
            self.recording = True
            self.condition.notify_all()
            return self.output_path

    def stop_recording(self):
        with self.condition:
            if not self.recording and not self.writer_active:
                return

            self.recording = False
            self.condition.notify_all()
            self.condition.wait_for(
                lambda: not self.writer_active,
                timeout=max(2.0, self.sample_interval + 1.0),
            )

    def sensor_snapshots(self):
        # Report every configured sensor, including offline devices.
        return [self.snapshot(self.sensor_id(sensor)) for sensor in self.sensors]

    def snapshot(self, sensor):
        device = self._sensor(sensor)
        address = int(device["address"])

        with self.condition:
            connected = any(
                int(item["address"]) == address
                for item in self.connected_sensors
            )
            error = self.sensor_errors.get(address) or self.error

            if connected and self.running and error:
                status = "error"
            elif connected and self.running:
                status = "connected"
            elif not connected:
                status = "offline"
            else:
                status = "stopped"

            latest = self.latest.get(device["name"])
            parsed = latest[1] if latest else None
            values = list(parsed) if isinstance(parsed, tuple) else None
            value = values[0] if values else parsed
            timestamp_ns = self.latest_timestamp_ns.get(address)
            sensor_type = device.get("type", "sensor")

            return {
                "revision": self.revision.get(address, 0),
                "id": self.sensor_id(device),
                "source": "atlas",
                "type": sensor_type,
                "name": device.get("name", sensor_type),
                "status": status,
                "running": self.running,
                "recording": self.recording,
                "interface": "I²C",
                "device": f"0x{address:02X} ({address})",
                "connection": f"Bus {self.bus}",
                "bus": self.bus,
                "address": address,
                "value": value,
                "values": values,
                "unit": device.get("unit", self.DEFAULT_UNIT.get(sensor_type, "")),
                "decimals": int(device.get("decimals", self.DEFAULT_DECIMALS.get(sensor_type, 2))),
                "raw": self.latest_raw.get(address),
                "timestamp_ns": str(timestamp_ns) if timestamp_ns is not None else None,
                "timestamp_ms": timestamp_ns // 1_000_000 if timestamp_ns is not None else None,
                "sample_count": self.sample_count.get(address, 0),
                "output_path": str(self.output_path) if self.output_path is not None else None,
                "error": error,
            }

    def wait_for_update(self, sensor, last_revision, timeout=5.0):
        device = self._sensor(sensor)
        address = int(device["address"])

        with self.condition:
            self.condition.wait_for(
                lambda: self.revision.get(address, 0) != last_revision,
                timeout=timeout,
            )

        return self.snapshot(self.sensor_id(device))

    def _read_loop(self):
        file = None
        buffer = []
        last_flush = time.monotonic()
        active_output_path = None

        try:
            while not self.stop_event.is_set():
                if file is not None and not self.recording:
                    if buffer:
                        file.writelines(buffer)
                        buffer.clear()
                    file.close()
                    file = None
                    active_output_path = None
                    with self.condition:
                        self.writer_active = False
                        self.condition.notify_all()

                timestamp_ns = time.time_ns()
                context = self.acquisition_context()
                rows = []

                # Keep a complete EZO request/read cycle atomic with respect
                # to calibration commands. Calibration may therefore run
                # while the live monitor stays active without mixing replies.
                with self.io_lock:
                    active = []
                    for sensor in self.connected_sensors:
                        try:
                            self._write(sensor["address"], "R")
                            active.append(sensor)
                        except OSError as error:
                            with self.condition:
                                self.sensor_errors[int(sensor["address"])] = str(error)

                    if self.stop_event.wait(self.sample_interval):
                        break

                    timestamp_ns = time.time_ns()
                    for sensor in active:
                        address = int(sensor["address"])
                        try:
                            code, raw_value = self._read(address)
                        except OSError as error:
                            with self.condition:
                                self.sensor_errors[address] = str(error)
                                self.revision[address] = self.revision.get(address, 0) + 1
                                self.condition.notify_all()
                            continue

                        if code != 1 or not raw_value:
                            continue

                        parsed = self._parse(raw_value)
                        with self.condition:
                            self.latest[sensor["name"]] = (timestamp_ns, parsed)
                            self.latest_raw[address] = raw_value
                            self.latest_timestamp_ns[address] = timestamp_ns
                            self.sample_count[address] = self.sample_count.get(address, 0) + 1
                            self.revision[address] = self.revision.get(address, 0) + 1
                            self.sensor_errors.pop(address, None)
                            self.condition.notify_all()

                        if self.recording:
                            rows.append(
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
                                    str(sensor["name"]),
                                    str(address),
                                    str(raw_value),
                                ]) + "\n"
                            )

                if not self.recording or not rows:
                    continue

                if file is None or active_output_path != self.output_path:
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
                    if file.tell() == 0:
                        file.write(
                            "timestamp_ns\tmonotonic_ns\trun_elapsed_s\t"
                            "digiflot_state\tstage_state\tstage_id\tstage_attempt\t"
                            "previous_stage_id\tnext_stage_id\t"
                            "sensor\taddress\tvalue\n"
                        )

                    with self.condition:
                        self.writer_active = True
                        self.condition.notify_all()

                buffer.extend(rows)
                now = time.monotonic()
                if len(buffer) >= self.buffer_size or now - last_flush >= self.flush_interval:
                    file.writelines(buffer)
                    buffer.clear()
                    last_flush = now

        except Exception as error:
            with self.condition:
                self.error = str(error)
                self.condition.notify_all()

        finally:
            if file is not None:
                if buffer:
                    file.writelines(buffer)
                file.close()

            with self.condition:
                self.recording = False
                self.writer_active = False
                self.running = False
                self.condition.notify_all()

    @staticmethod
    def _parse(value):
        try:
            values = tuple(float(item) for item in value.split(","))
            return values[0] if len(values) == 1 else values
        except ValueError:
            return value
