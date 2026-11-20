# DigiFlot-Edge plugins: reusable sensor templates

Plugins are **trusted local Python code**. They are not sandboxed. Copy only code
you trust into `src/plugins/<plugin_name>/<plugin_name>.py`.

## Minimal contract

One file named exactly as its directory. It declares a **literal** `PLUGIN`
dictionary and a `create_sensor(config)` factory. New plugins are **disabled
by default** even when the files exist. Enable them in **Settings → Plugins**
and restart DigiFlot. Disabled modules are not imported. The `Templates`
directory is excluded from discovery.

The `PLUGIN` dictionary must contain `id` (same as the directory) and
`name`. Optional entries: `version`, `description`, `calibration`
(`none`, `optional`, `required`; defaults to `none`) and `display`.

`display` is a list of up to eight reusable components:
- `{"type": "metric", "key": "temperature_c", "label": "Temperature", "unit": "°C", "decimals": 2}`
- `{"type": "gauge", "key": "signal_pct", "label": "Signal", "min": 0, "max": 100, "unit": "%"}`

The same display declaration is used on **Sensors**, in **optional calibration
checks**, and in the **Run** live view. The generic card already includes the
primary reading and a timeline plot.

`create_sensor(config)` returns one sensor instance with the assigned ID
`plugin_<plugin_name>` and methods:
`start()`, `stop()`, `snapshot()`,
`wait_for_update(last_revision, timeout=5)`,
`start_recording(output_dir, file_stem)`, `stop_recording()`,
and `set_context_provider(callback)`.

`snapshot()` returns an ID, name, status, current value, unit, timestamp,
revision, sample count, and numerical `channels`. The DigiFlot plugin
catalog adds `display` and `calibration_policy` automatically.

For regular sensors, subclass `Templates/sampled_sensor.py` and implement
`read_channels()`. For passive newline-based serial devices, subclass
`Templates/serial_sensor.py` and implement `parse_line()`. Neither template
implements actuator control.

## Calibration policy

- `none`: no calibration step.
- `optional`: a manual verification entry starts **skipped** and never blocks
  a run; operators may reopen it to perform a check.
- `required`: the generic verification must be confirmed or explicitly skipped
  under the existing DigiFlot rules.

## Hardware / safety

Do not probe unknown serial interfaces with write commands. Do not implement
actuator control by altering the DigiFlot state machine. Recording must be
bounded, stop cleanly, and never replace real measurements with zeros on error.
The plugin toggle does not delete the plugin files. Only trusted local code
can be loaded; there is no remote installation endpoint.

See `../test_sensor/test_sensor.py` for a functioning simulated example.
