"""Bronkhorst ProPar mass-flow controller for DigiFlot-Edge.

The physical instrument, not the USB serial adapter, provides the flow unit and
serial number. ProPar FlowDDE parameter 205 is measured flow and 206 is setpoint.
No actuator command is issued during discovery, boot, or reconnection.
"""
import csv
import math
import threading
import time
from pathlib import Path

try:
    import propar
except ImportError:
    propar = None


class Bronkhorst:
    DRIVER = "bronkhorst"
    PARAM_MODEL, PARAM_SERIAL, PARAM_UNIT = 91, 92, 129
    PARAM_FLOW, PARAM_SETPOINT = 205, 206
    FIELDS = ("timestamp_ns", "run_elapsed_s", "digiflot_state", "stage_state",
              "stage_id", "stage_attempt", "flow", "setpoint", "unit", "control_state")

    def __init__(self, id, name="Air Flow", port=None, baudrate=38400, address=128,
                 sample_interval=1.0, enabled=True, control_enabled=False, max_flow_l_min=10.0,
                 connection=None, identity=None, output_dir="./data/bronkhorst", **_):
        self.id, self.name, self.port = str(id), str(name), str(port or "")
        self.baudrate, self.address = int(baudrate), int(address)
        self.sample_interval, self.max_flow_l_min = max(0.2, float(sample_interval)), float(max_flow_l_min)
        self.enabled, self.control_enabled = bool(enabled), bool(control_enabled)
        self.connection, self.identity = connection or {}, identity or {}
        self.output_dir = Path(output_dir)
        self.running = self.recording = self.writer_active = False
        self.status = "stopped"
        self.error = None
        self.value = self.setpoint = self.unit = None
        self.model = self.serial_number = None
        self.control_state = "disabled" if not self.control_enabled else "idle"
        self.sample_count = self.revision = 0
        self.timestamp_ns = None
        self._instrument = None
        self._pending = None
        self._thread = None
        self._stop_event = threading.Event()
        self._lock = threading.RLock()
        self._condition = threading.Condition(self._lock)
        self._writer = None
        self._writer_file = None
        self._context = lambda: {}

    @classmethod
    def from_config(cls, config):
        return cls(**config)

    def set_context_provider(self, provider):
        self._context = provider

    @staticmethod
    def _close_instrument(instrument):
        try:
            if instrument is not None and getattr(instrument, "master", None):
                instrument.master.stop()
        except Exception:
            pass

    @classmethod
    def _identify(cls, instrument):
        device_id = instrument.id
        flow = instrument.readParameter(cls.PARAM_FLOW)
        if device_id is None or flow is None or not math.isfinite(float(flow)):
            raise OSError("No valid Bronkhorst identification and flow response")
        def optional(number):
            try:
                return instrument.readParameter(number)
            except Exception:
                return None
        return {"device_id": str(device_id), "model": optional(cls.PARAM_MODEL),
                "device_serial": optional(cls.PARAM_SERIAL), "unit": optional(cls.PARAM_UNIT),
                "flow": float(flow)}

    @classmethod
    def discover_available(cls, ports, occupied=(), baudrate=38400, address=128):
        """Probe unclaimed serial endpoints using only read-only ProPar commands."""
        if propar is None:
            raise RuntimeError("Install bronkhorst-propar to discover a Bronkhorst controller")
        occupied = set(occupied)
        found = []
        for endpoint in ports:
            port = str(endpoint.get("port"))
            if port in occupied:
                continue
            instrument = None
            try:
                instrument = propar.instrument(port, address=int(address), baudrate=int(baudrate))
                data = cls._identify(instrument)
                found.append({**data, "port": port, "driver": cls.DRIVER, "detected": True,
                              "connection": endpoint.get("connection") or {},
                              "identity": {"protocol": "propar", "device_serial": data["device_serial"]}})
            except Exception:
                pass
            finally:
                cls._close_instrument(instrument)
        return found

    @staticmethod
    def _to_l_min(value, unit):
        unit = str(unit or "").strip().lower().replace(" ", "")
        if unit in ("l/min", "ln/min", "l(n)/min", "nl/min"):
            return float(value)
        if unit in ("ml/min", "mln/min", "ml(n)/min", "nml/min"):
            return float(value) / 1000.0
        return None

    @staticmethod
    def _from_l_min(value, unit):
        unit = str(unit or "").strip().lower().replace(" ", "")
        if unit in ("l/min", "ln/min", "l(n)/min", "nl/min"):
            return float(value)
        if unit in ("ml/min", "mln/min", "ml(n)/min", "nml/min"):
            return float(value) * 1000.0
        raise ValueError(f"Unknown Bronkhorst flow unit: {unit!r}. Control not enabled.")

    def start(self):
        if not self.enabled or self.running:
            return
        self._stop_event.clear()
        self.running = True
        self._thread = threading.Thread(target=self._loop, name=f"bronkhorst-{self.id}", daemon=True)
        self._thread.start()

    def stop(self):
        if self.control_enabled and self.status == "connected":
            self.stop_airflow()
            with self._condition:
                self._condition.wait_for(
                    lambda: self.control_state != "pending", timeout=2.5)
        self._stop_event.set()
        self.running = False
        if self._thread is not None:
            self._thread.join(timeout=3.0)
        self.stop_recording()
        self._close_instrument(self._instrument)
        self._instrument = None
        with self._condition:
            self._pending = None
            self.status = "stopped"
            self._condition.notify_all()

    def set_airflow(self, value_l_min):
        if not self.control_enabled:
            raise PermissionError("Bronkhorst control is disabled in Settings")
        value = float(value_l_min)
        if not math.isfinite(value) or not 0 <= value <= self.max_flow_l_min:
            raise ValueError(f"Airflow must be in [0, {self.max_flow_l_min:g}] L/min")
        with self._condition:
            if self.status != "connected" or not self.running:
                raise ConnectionError("Bronkhorst is offline; no setpoint was queued")
            self._from_l_min(value, self.unit)  # Reject unknown flow units before scheduling.
            self._pending = value
            self.control_state = "pending"
            self._condition.notify_all()
        return {"status": "pending", "target_l_min": value}

    def stop_airflow(self):
        """Request zero flow; never claim success until the device acknowledges it."""
        if not self.control_enabled:
            return {"status": "disabled"}
        with self._condition:
            if not self.running or self.status != "connected":
                self._pending = None
                self.control_state = "unconfirmed"
                self._condition.notify_all()
                return {"status": "unconfirmed", "error": "Controller offline; zero flow not verified"}
            self._pending = 0.0
            self.control_state = "pending"
            self._condition.notify_all()
        return {"status": "pending", "target_l_min": 0.0}

    def _publish(self, flow, setpoint):
        now = time.time_ns()
        context = dict(self._context() or {})
        with self._condition:
            self.value, self.setpoint = float(flow), float(setpoint)
            self.timestamp_ns, self.sample_count = now, self.sample_count + 1
            self.status, self.error = "connected", None
            self.revision += 1
            if self._writer:
                self._writer.writerow({"timestamp_ns": now, "run_elapsed_s": context.get("run_elapsed_s"),
                    "digiflot_state": context.get("digiflot_state"), "stage_state": context.get("stage_state"),
                    "stage_id": context.get("stage_id"), "stage_attempt": context.get("stage_attempt"),
                    "flow": flow, "setpoint": setpoint, "unit": self.unit,
                    "control_state": self.control_state})
                self._writer_file.flush()
            self._condition.notify_all()

    def _loop(self):
        while not self._stop_event.is_set():
            try:
                if self._instrument is None:
                    if propar is None:
                        raise RuntimeError("bronkhorst-propar package not installed")
                    instrument = propar.instrument(self.port, address=self.address, baudrate=self.baudrate)
                    info = self._identify(instrument)
                    expected = self.identity.get("device_serial")
                    if expected and info.get("device_serial") and str(expected) != str(info["device_serial"]):
                        self._close_instrument(instrument)
                        raise RuntimeError("Bronkhorst serial mismatch; refusing connection")
                    self._instrument = instrument
                    with self._condition:
                        self.model, self.serial_number, self.unit = info["model"], info["device_serial"], info["unit"]
                        self.control_state = "idle" if self.control_enabled else "disabled"
                with self._condition:
                    pending, self._pending = self._pending, None
                if pending is not None:
                    native_value = self._from_l_min(pending, self.unit)
                    if not self._instrument.writeParameter(self.PARAM_SETPOINT, native_value):
                        raise OSError("Bronkhorst rejected the setpoint")
                    accepted = self._instrument.readParameter(self.PARAM_SETPOINT)
                    if accepted is None or abs(float(accepted) - native_value) > max(0.01, 0.01 * abs(native_value)):
                        raise OSError("Bronkhorst setpoint readback does not match")
                    with self._condition:
                        self.control_state = "applied"
                flow = self._instrument.readParameter(self.PARAM_FLOW)
                setpoint = self._instrument.readParameter(self.PARAM_SETPOINT)
                if flow is None or setpoint is None:
                    raise OSError("Empty Bronkhorst reading")
                self._publish(flow, setpoint)
                self._stop_event.wait(self.sample_interval)
            except Exception as error:
                self._close_instrument(self._instrument)
                self._instrument = None
                with self._condition:
                    self._pending = None  # Never replay a nonzero setpoint on reconnect.
                    self.status, self.error = "offline", str(error)
                    self.value, self.setpoint = None, None
                    self.control_state = "unconfirmed" if self.control_enabled else "disabled"
                    self.revision += 1
                    self._condition.notify_all()
                self._stop_event.wait(3.0)

    def snapshot(self):
        with self._condition:
            flow_l_min = self._to_l_min(self.value, self.unit) if self.value is not None else None
            setpoint_l_min = self._to_l_min(self.setpoint, self.unit) if self.setpoint is not None else None
            return {"id": self.id, "name": self.name, "type": "bronkhorst", "source": "bronkhorst",
                    "interface": "ProPar / RS-232", "device": self.port, "status": self.status,
                    "value": flow_l_min if flow_l_min is not None else self.value,
                    "unit": "L/min" if flow_l_min is not None else (self.unit or ""),
                    "decimals": 2, "channels": {"flow": self.value, "setpoint": self.setpoint,
                                                "flow_l_min": flow_l_min, "setpoint_l_min": setpoint_l_min,
                                                "native_unit": self.unit},
                    "model": self.model, "device_serial": self.serial_number,
                    "control_enabled": self.control_enabled, "control_state": self.control_state,
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
            self._writer = csv.DictWriter(self._writer_file, fieldnames=self.FIELDS, delimiter="\t")
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
