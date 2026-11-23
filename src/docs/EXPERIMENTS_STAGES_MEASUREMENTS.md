# Experiments, stage acquisition and measurements

**Scope:** Edge orchestration and operator workflow, reviewed 2026-11-23. Source: `src/lib/digiflot.py`, `src/ui/js/run.js`.

## Operator workflow

1. Select a locally stored or Server-cached experiment in **Experiments**.
2. Select a registered **Flotation cell** or explicitly continue without one.
3. Complete/review required camera and sensor calibration; HIFIE requires matching approved context.
4. Supply the required execution inputs, including the working cell volume when applicable.
5. Review the first stage and its **Stage acquisition** configuration; start the run.
6. At each transition, inspect upcoming settings. If measurements are required, capture them in **Data acquisition** before advancing, or choose **Ignore and continue**.
7. When complete, inspect Results, events, measurements and Server synchronization status.

## Stage recipe fields

A stage retains its existing operating fields, plus optional `metadata.transition`, `metadata.acquisition` and `metadata.variables`. The additive example below is representative; IDs are device-specific.

```json
{
  "uid": "stage-sample-01",
  "name": "Manual sampling",
  "type": "custom",
  "duration": 0,
  "ph": 7,
  "airflow": 0,
  "rotor_speed": 700,
  "metadata": {
    "transition": {"auto_advance": true, "timeout_s": 15},
    "acquisition": {"version": 1, "mode": "custom",
      "enabled": {"video/all": false, "video/1": false, "atlas": true,
                  "sensor/scale_1": true, "virtual/froth_interface": true}},
    "variables": {
      "pulp_density": {"label": "Pulp density", "type": "continuous",
                       "unit": "g/L", "value": 1200, "required_measurement": true}
    }
  }
}
```

- `duration > 0`: timed stage, seconds. `duration = 0`: no automatic stage end. Negative or non-finite duration is invalid.
- `transition.auto_advance`: after the stage ends, start the following stage automatically after `timeout_s`, unless blocked by required measurements. Missing settings fall back to global orchestration settings.
- The timeout is **between** stages; it does not end an open-ended stage. Operators still explicitly finish a manual stage.
- `acquisition.mode: "defaults"` or absent: use type defaults. `mode: "custom"`: override individual recording channels. Missing channel flags inherit defaults.
- `video/all` controls recording for all cameras unless an individual `video/<camera-id>` overrides it.
- `atlas` controls the Atlas recorder; `sensor/<device-id>` controls named physical writers. `virtual/froth_interface` controls HIFIE processing. These keys do not power down equipment.

## Default acquisition by stage type

| Type | Video recorder | Physical recorders | HIFIE |
| --- | --- | --- | --- |
| Conditioning | Off | On | On **if approved** |
| Flotation | On | On | On **if approved** |
| Custom | Off | On | On **if approved** |

HIFIE may consume `lores` without saving a main camera video. Physical sensors can be disabled individually for a stage; default is to keep their recordings. `All` and `None` in the editor apply to acquisition flags, not to process safety.

## Manual stages and required measurements

Use the Server variable-editor checkbox **Require a saved measurement before starting the next stage** for a variable of a manual-duration stage. This persists `required_measurement: true` next to its definition; the planned `value` is **not** evidence.

At stage finish, the Edge enters `Transition`. Before it starts the next stage it checks `measurements.jsonl` for matching variable IDs/names, `stage_index` (or legacy UID/name context), **current attempt**, and a capture made during the active/transition stage. A measurement from a previous stage or retry does not meet the requirement.

- If every required variable was measured: manual **Start now** is permitted. With automatic advance enabled, the transition countdown begins after the final measurement is captured.
- If a measurement is missing: transition stays pending; the automatic deadline is disabled and **Start now** is blocked.
- **Open Data acquisition** opens the existing form and fills the first missing variable name. Saving the measurement updates the gate.
- **Ignore and continue** requires operator confirmation. The Edge records `STAGE_REQUIRED_MEASUREMENTS_IGNORED`, including the stage index/UID, attempt, missing names and reason; it then advances. This is not a hidden bypass.
- A skipped stage does not require a second waiver. The current implementation does not gate completion of the **last** stage because no following stage exists.
- This rule is applied to manual-duration stages only, not all timed stages.

The Run form currently does **not** automatically create every required variable as a ready-made input. The shortcut preselects its name; fully automatic creation is future work.

## Recording and provenance

At stage start, the controller computes desired camera IDs, physical recorder IDs and HIFIE activity. It preserves active writers when possible, stops unwanted channels and starts newly required channels. New sensor recording segments use unique names, avoiding TSV overwrite when a sensor is reactivated. Video segments are managed per camera.

The runtime records `STAGE_ACQUISITION_APPLIED` and stage history (requested/started channels, start/end, elapsed time). `effective_setup_snapshot.json` remains the frozen run-start snapshot; overrides and stage history live in `runtime.json` and the Server execution's mutable runtime metadata.

Measurements are saved append-only to `measurements.jsonl`. A record includes value/type/unit, source and sensor snapshot (where applicable), time, stage ID/UID/index, state and attempt. Sensor readings are **captured** on operator action; a live sensor display alone does not satisfy a required measurement.

## Recovery

A restart of an active experiment enters recovery. The runtime restores stage and measurement history, acquisition overrides and explicit waivers. Confirm the current stage and source calibration before continuing. Do not edit `runtime.json` to bypass a gate.

## Relevant endpoints

```text
GET  /api/digiflot/state
GET  /api/digiflot/stream                   (SSE)
POST /api/digiflot/stages/start
POST /api/digiflot/stages/finish-now
POST /api/digiflot/stages/skip
POST /api/digiflot/stages/acquisition/override
POST /api/digiflot/stages/measurements/ignore
GET  /api/digiflot/measurements
POST /api/digiflot/measurements
POST /api/digiflot/recovery/resume
```

See [HTTP API reference](HTTP_API_REFERENCE.md) for payloads. See [Troubleshooting](TROUBLESHOOTING.md) for an acceptance checklist.
