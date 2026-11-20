"""WAGO 879-1300 energy meter acquisition over read-only Modbus RTU.

The MID26 879-1300 register table was not present in verified public material
when this driver was written. No registers are guessed: measurement channels
must be supplied from the device-specific manufacturer register map.
"""
import csv
import math
import threading
import time
from pathlib import Path

try:
    import minimalmodbus
except ImportError:
    minimalmodbus = None


class Wago:
    DRIVER = "wago"
    CHANNELS = {"active_power": ("W", "float32"), "energy_import": ("kWh", "float32"),
                "voltage": ("V", "float32"), "current": ("A", "float32"),
                "frequency": ("Hz", "float32"), "power_factor": ("", "float32")}
    FIELDS = ("timestamp_ns", "run_elapsed_s", "digiflot_state", "stage_state",
              "stage_id", "stage_attempt", "active_power", "energy_import",
              "stage_energy_wh", "voltage", "current", "frequency", "power_factor")

    def __init__(self, id, name="Power Meter", port=None, slave_id=1, baudrate=9600,
                 parity="N", stopbits=1, sample_interval=1.0, registers=None, enabled=True,
                 connection=None, identity=None, output_dir="./data/wago", **_):
        self.id, self.name, self.port = str(id), str(name), str(port or "")
        self.slave_id, self.baudrate = int(slave_id), int(baudrate)
        self.parity, self.stopbits = str(parity).upper(), int(stopbits)
        if self.parity not in ("N", "E", "O") or self.stopbits not in (1, 2):
            raise ValueError("Invalid Modbus serial configuration")
        self.sample_interval, self.enabled = max(0.2, float(sample_interval)), bool(enabled)
        self.registers = dict(registers or {})
        self.connection, self.identity = connection or {}, identity or {}
        self.output_dir = Path(output_dir)
        self.status = "stopped"
        self.error = None
        self.running = self.recording = self.writer_active = False
        self.channels = {}
        self.stage_energy_wh = None
        self.sample_count = self.revision = 0
        self.timestamp_ns = None
        self._instrument = self._thread = None
        self._stop_event = threading.Event()
        self._condition = threading.Condition(threading.RLock())
        self._context = lambda: {}
        self._stage_key = self._stage_base = None
        self._writer = self._writer_file = None

    @classmethod
    def from_config(cls, config):
        return cls(**config)

    def set_context_provider(self, provider):
        self._context = provider

    @staticmethod
    def _connect(port, slave_id, baudrate, parity, stopbits):
        if minimalmodbus is None:
            raise RuntimeError("Install minimalmodbus for WAGO RS-485 communication")
        device = minimalmodbus.Instrument(port, slave_id, mode=minimalmodbus.MODE_RTU,
                                           close_port_after_each_call=True)
        device.serial.baudrate = int(baudrate)
        device.serial.parity = parity
        device.serial.stopbits = int(stopbits)
        device.serial.timeout = 0.25
        device.clear_buffers_before_each_transaction = True
        return device

    @classmethod
    def discover_available(cls, ports, occupied=(), slave_ids=(1,), baudrates=(9600, 19200)):
        """Find read-only Modbus responders, but never claim their manufacturer.

        The legacy WAGO 879-30xx uses register 0x4000; the MID26 879-1300
        mapping is unverified. A response is only a Modbus candidate.
        """
        if minimalmodbus is None:
            raise RuntimeError("Install minimalmodbus to discover RS-485 devices")
        occupied = set(occupied)
        found = []
        for endpoint in ports:
            port = str(endpoint.get("port"))
            if port in occupied:
                continue
            matched = None
            for baudrate in baudrates:
                for slave_id in slave_ids:
                    for parity in ("N", "E"):
                        try:
                            device = cls._connect(port, slave_id, baudrate, parity, 1)
                            # Read-only probes on candidate register offsets. A valid
                            # reply confirms Modbus, never the WAGO model itself.
                            for address in (0x4000, 0):
                                try:
                                    response = device.read_registers(address, 1, functioncode=3)
                                except Exception:
                                    continue
                                if response and isinstance(response[0], int):
                                    matched = {"port": port, "driver": cls.DRIVER,
                                               "slave_id": slave_id, "baudrate": baudrate,
                                               "parity": parity, "detected": True,
                                               "verified_model": False,
                                               "evidence": "Modbus RTU response; manufacturer not verified",
                                               "connection": endpoint.get("connection") or {}}
                                    break
                            if matched:
                                break
                        except Exception:
                            continue
                    if matched:
                        break
                if matched:
                    break
            if matched:
                found.append(matched)
        return found

    def _read_channel(self, name, spec):
        address = int(spec["address"])
        function = int(spec.get("function", 3))
        if not 0 <= address <= 65535 or function not in (3, 4):
            raise ValueError(f"Invalid register definition for {name}")
        dtype = str(spec.get("data_type", "float32"))
        order = str(spec.get("byteorder", "big")).lower()
        ordering = {"big": minimalmodbus.BYTEORDER_BIG,
                    "little": minimalmodbus.BYTEORDER_LITTLE,
                    "big_swap": minimalmodbus.BYTEORDER_BIG_SWAP,
                    "little_swap": minimalmodbus.BYTEORDER_LITTLE_SWAP}
        if order not in ordering:
            raise ValueError(f"Unknown word order for {name}")
        if dtype == "float32":
            value = self._instrument.read_float(address, functioncode=function,
                                                number_of_registers=2, byteorder=ordering[order])
        elif dtype in ("uint32", "int32"):
            value = self._instrument.read_long(address, functioncode=function, signed=dtype=="int32",
                                               byteorder=ordering[order])
        elif dtype in ("uint16", "int16"):
            value = self._instrument.read_register(address, number_of_decimals=0,
                                                   functioncode=function, signed=dtype=="int16")
        else:
            raise ValueError(f"Unsupported Modbus data type {dtype}")
        result = float(value) * float(spec.get("scale", 1.0))
        if not math.isfinite(result):
            raise ValueError(f"Non-finite WAGO value for {name}")
        return result

    def start(self):
        if self.running or not self.enabled:
            return
        self._stop_event.clear()
        self.running = True
        self._thread = threading.Thread(target=self._loop, daemon=True, name=f"wago-{self.id}")
        self._thread.start()

    def stop(self):
        self._stop_event.set()
        self.running = False
        if self._thread is not None:
            self._thread.join(timeout=3.0)
        self.stop_recording()
        self._instrument = None
        with self._condition:
            self.status = "stopped"
            self._condition.notify_all()

    def _publish(self, channels):
        now = time.time_ns()
        context = dict(self._context() or {})
        key = (context.get("stage_id"), context.get("stage_attempt"))
        energy = channels.get("energy_import")
        with self._condition:
            if key != self._stage_key:
                self._stage_key, self._stage_base = key, energy
                self.stage_energy_wh = None
            if energy is not None and self._stage_base is not None:
                diff = (energy - self._stage_base) * 1000
                self.stage_energy_wh = diff if 0 <= diff < 1e9 else None
            self.channels = channels
            self.timestamp_ns, self.sample_count = now, self.sample_count + 1
            self.status, self.error = "connected", None
            self.revision += 1
            if self._writer:
                self._writer.writerow({**{field: context.get(field) for field in self.FIELDS},
                    **channels, "stage_energy_wh": self.stage_energy_wh, "timestamp_ns": now})
                self._writer_file.flush()
            self._condition.notify_all()

    def _loop(self):
        if not self.registers:
            with self._condition:
                self.status, self.error = "unconfigured", (
                    "WAGO 879-1300 register map not verified; configure registers from its manual")
                self.revision += 1
                self._condition.notify_all()
            return
        while not self._stop_event.is_set():
            try:
                if self._instrument is None:
                    self._instrument = self._connect(self.port, self.slave_id, self.baudrate,
                                                      self.parity, self.stopbits)
                data = {name: self._read_channel(name, spec) for name, spec in self.registers.items()}
                if not data:
                    raise RuntimeError("No WAGO channels configured")
                self._publish(data)
                self._stop_event.wait(self.sample_interval)
            except Exception as error:
                self._instrument = None
                with self._condition:
                    self.status, self.error = "offline", str(error)
                    self.channels = {}
                    self.revision += 1
                    self._condition.notify_all()
                self._stop_event.wait(3.0)

    def snapshot(self):
        with self._condition:
            value = self.channels.get("active_power")
            return {"id": self.id, "name": self.name, "type": "wago", "source": "wago",
                    "interface": "Modbus RTU / RS-485", "device": self.port,
                    "status": self.status, "value": value, "unit": "W", "decimals": 1,
                    "channels": dict(self.channels) | {"stage_energy_wh": self.stage_energy_wh},
                    "timestamp_ns": self.timestamp_ns,
                    "timestamp_ms": self.timestamp_ns // 1_000_000 if self.timestamp_ns else None,
                    "sample_count": self.sample_count, "revision": self.revision,
                    "error": self.error, "recording": self.recording}

    def wait_for_update(self, last_revision, timeout=5.0):
        with self._condition:
            self._condition.wait_for(lambda: self.revision != last_revision, timeout=timeout)
        return self.snapshot()

    def start_recording(self, output_dir=None, file_stem=None):
        with self._condition:
            if self.recording:
                return Path(self._writer_file.name)
            folder = Path(output_dir) if output_dir else self.output_dir
            folder.mkdir(parents=True, exist_ok=True)
            path = folder / f"{file_stem or self.id}.tsv"
            self._writer_file = path.open("w", encoding="utf-8", newline="")
            self._writer = csv.DictWriter(self._writer_file, fieldnames=self.FIELDS, delimiter="\t",
                                          extrasaction="ignore")
            self._writer.writeheader()
            self.recording = self.writer_active = True
            return path

    def stop_recording(self):
        with self._condition:
            self.recording = self.writer_active = False
            self._writer = None
            if self._writer_file is not None:
                self._writer_file.close()
                self._writer_file = None
