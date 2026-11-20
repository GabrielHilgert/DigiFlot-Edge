"""Optional DigiFlot sensor plugins. Native devices remain unchanged.

One plugin lives in plugins/<slug>/<slug>.py and exposes a literal PLUGIN
manifest plus create_sensor(config). Disabled plugins are inspected through AST
only: their Python modules are not imported or executed.
"""
import ast
import importlib.util
import re
from pathlib import Path

_SLUG = re.compile(r"^[a-z][a-z0-9_]{1,47}$")
_CALIBRATION = {"none", "optional", "required"}
_DISPLAY_TYPES = {"metric", "gauge"}
_REQUIRES = ("start", "stop", "snapshot", "wait_for_update",
             "start_recording", "stop_recording", "set_context_provider")


def _manifest(path, slug):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    assignment = next((node for node in tree.body if isinstance(node, ast.Assign)
                       and any(isinstance(target, ast.Name) and target.id == "PLUGIN"
                               for target in node.targets)), None)
    if assignment is None:
        raise ValueError("Missing literal PLUGIN manifest")
    meta = ast.literal_eval(assignment.value)
    if not isinstance(meta, dict) or meta.get("id") != slug:
        raise ValueError("Manifest id must match the plugin directory")
    if not isinstance(meta.get("name"), str) or not meta["name"].strip():
        raise ValueError("Plugin name is required")
    if meta.get("calibration", "none") not in _CALIBRATION:
        raise ValueError("Calibration must be none, optional or required")
    display = meta.get("display", [])
    if not isinstance(display, list) or len(display) > 8:
        raise ValueError("Display must be a list of at most eight components")
    for item in display:
        if not isinstance(item, dict) or item.get("type") not in _DISPLAY_TYPES:
            raise ValueError("Unknown display type")
        if not isinstance(item.get("key"), str) or not _SLUG.fullmatch(item["key"]):
            raise ValueError("Display key must be a valid channel identifier")
        if not isinstance(item.get("label"), str) or len(item["label"]) > 80:
            raise ValueError("Invalid display label")
        if item["type"] == "gauge":
            low, high = float(item.get("min", 0)), float(item.get("max", 100))
            if not low < high:
                raise ValueError("Gauge minimum must be smaller than maximum")
    return {key: meta[key] for key in ("id", "name", "version", "description",
                                      "calibration", "display") if key in meta}


class PluginCatalog:
    """Conservative, local-only plugin scanner and optional sensor instances."""

    def __init__(self, root, config=None):
        self.root = Path(root)
        self.config = config if isinstance(config, dict) else {}
        self.installed = {}
        self.sensors = {}
        self.errors = {}
        self.refresh()
        self._load_enabled()

    def refresh(self):
        result = {}
        if self.root.is_dir():
            for folder in sorted(self.root.iterdir()):
                slug = folder.name
                if not folder.is_dir() or not _SLUG.fullmatch(slug) or slug == "Templates":
                    continue
                script = folder / f"{slug}.py"
                if not script.is_file() or script.is_symlink():
                    continue
                try:
                    result[slug] = {"manifest": _manifest(script, slug), "path": script}
                except (SyntaxError, ValueError, TypeError, UnicodeError, MemoryError) as error:
                    result[slug] = {"error": str(error), "path": script}
        self.installed = result
        return result

    def _load_enabled(self):
        for slug, entry in self.installed.items():
            if not bool((self.config.get(slug) or {}).get("enabled", False)):
                continue
            if "error" in entry:
                self.errors[slug] = entry["error"]
                continue
            try:
                spec = importlib.util.spec_from_file_location(f"digiflot_plugin_{slug}", entry["path"])
                if spec is None or spec.loader is None:
                    raise ImportError(f"Cannot load plugin {slug}")
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                maker = getattr(module, "create_sensor", None)
                if not callable(maker):
                    raise TypeError("Plugin must define create_sensor(config)")
                config = dict(self.config.get(slug) or {})
                config["id"] = f"plugin_{slug}"
                sensor = maker(config)
                if str(getattr(sensor, "id", "")) != config["id"]:
                    raise ValueError(f"Plugin sensor ID must be {config['id']}")
                if any(not callable(getattr(sensor, attr, None)) for attr in _REQUIRES):
                    raise TypeError("Plugin sensor does not implement the required interface")
                self.sensors[sensor.id] = sensor
            except Exception as error:
                self.errors[slug] = f"{type(error).__name__}: {error}"

    def snapshot(self, device):
        data = dict(device.snapshot())
        slug = str(device.id)[len("plugin_"):]
        meta = self.installed[slug]["manifest"]
        data.update({"plugin_id": slug, "type": "plugin_sensor",
                     "display": meta.get("display", []),
                     "calibration_policy": meta.get("calibration", "none")})
        return data

    def sensors_snapshots(self):
        return [self.snapshot(device) for device in self.sensors.values()]

    def list_installed(self):
        self.refresh()  # Local files installed after startup appear without executing them.
        items = []
        for slug, entry in self.installed.items():
            config = self.config.get(slug) or {}
            meta = entry.get("manifest", {})
            items.append({"id": slug, "name": meta.get("name", slug),
                "version": meta.get("version", ""), "description": meta.get("description", ""),
                "calibration": meta.get("calibration", "none"),
                "display": meta.get("display", []),
                "enabled": bool(config.get("enabled", False)),
                "loaded": f"plugin_{slug}" in self.sensors,
                "error": self.errors.get(slug) or entry.get("error")})
        return items

    def contains(self, slug):
        self.refresh()
        return slug in self.installed and "error" not in self.installed[slug]
