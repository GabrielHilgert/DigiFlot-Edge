"""Built-in, disabled-by-default demonstration of sampled sensors and shared displays."""
import math
import time
from plugins.Templates.sampled_sensor import SampledSensor

# Literal metadata: Settings can list this plugin without executing this module.
PLUGIN = {
    "id": "test_sensor",
    "name": "Synthetic sensor · Template test",
    "version": "1.0",
    "description": "Generates repeatable temperature and signal values to test shared sensor displays.",
    "calibration": "optional",
    "display": [
        {"type": "metric", "key": "temperature_c", "label": "Temperature", "unit": "°C", "decimals": 2},
        {"type": "metric", "key": "signal_pct", "label": "Signal quality", "unit": "%", "decimals": 1},
        {"type": "gauge", "key": "signal_pct", "label": "Signal level", "unit": "%", "min": 0, "max": 100}
    ]
}


class SyntheticSensor(SampledSensor):
    CHANNELS = {"temperature_c": "°C", "signal_pct": "%"}
    PRIMARY = "temperature_c"

    def read_channels(self):
        elapsed = time.monotonic()
        return {"temperature_c": 23.0 + 1.2 * math.sin(elapsed / 17.0),
                "signal_pct": 50.0 + 35.0 * math.sin(elapsed / 8.0)}


def create_sensor(config):
    return SyntheticSensor(id=config["id"], name=PLUGIN["name"],
                           sample_interval=config.get("sample_interval", 1.0))
