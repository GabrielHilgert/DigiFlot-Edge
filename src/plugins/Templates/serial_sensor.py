"""Template for newline-based serial sensors connected directly by USB or adapter.

Copy the subclass into your plugin. A concrete sensor must define CHANNELS and
parse_line(); this template never sends commands to an unknown serial device.
"""
from plugins.Templates.sampled_sensor import SampledSensor

try:
    import serial
except ImportError:
    serial = None


class SerialLineSensor(SampledSensor):
    def __init__(self, id, port, baudrate=9600, timeout=0.5, **kwargs):
        super().__init__(id=id, **kwargs)
        self.port, self.baudrate, self.timeout = str(port), int(baudrate), float(timeout)
        self._serial = None

    def parse_line(self, line):
        """Return {channel: numeric value}. Implement in your own driver."""
        raise NotImplementedError

    def read_channels(self):
        if serial is None:
            raise RuntimeError("pyserial is required")
        if self._serial is None or not self._serial.is_open:
            self._serial = serial.Serial(self.port, self.baudrate, timeout=self.timeout)
        line = self._serial.readline().decode("ascii", errors="replace").strip()
        if not line:
            raise TimeoutError("Serial sensor did not return a sample")
        return self.parse_line(line)

    def stop(self):
        super().stop()
        if self._serial is not None:
            self._serial.close()
            self._serial = None
