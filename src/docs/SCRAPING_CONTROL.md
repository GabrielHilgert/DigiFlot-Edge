# DigiFlot scraping control — timing, GPIO and operator alerts

The scraping controller uses **monotonic stage time**. Scraping is enabled for flotation and custom stages; conditioning has no scraping. Default interval: 5 s, minimum: 1 s. There is no attempt to replay scraping signals after a delay.

## Operator settings

In **Settings → Experiment behavior**:

| Setting | Options | Default | Meaning |
|---|---|---|---|
| Scraping interval | ≥1 s | 5 s | Interval between scheduled events |
| Scraping output | Audio (browser beep), GPIO (TTL) | Audio | Selects audible vs physical output |
| Show Scraping Alert | checkbox | On | Controls **only** the visual notification |
| Scraping alert display | Whole Screen Alert, Compact Banner | Whole Screen | Visual style when enabled |
| GPIO output | BCM GPIO pins 4,5,6,12,13,16–27 (excluding reserved) | BCM 17 | Physical TTL pin, shown only when output = GPIO |

Audio is generated in the Run browser, and requires an audio-capable browser tab and user interaction to unlock audio. A GPIO pulse occurs on the Raspberry Pi device, even when no Run page is open. The visual alert is independent of both output methods; disabling Show Scraping Alert does **not** disable timed events, GPIO pulses, or the audio mode.

Whole Screen Alert uses the existing full-screen orange display. Compact Banner is a smaller orange notification at the bottom right. Both end through a **0.8 s CSS animation**, not a JavaScript timer. Stale events (older than 1.7 s) are not shown when an SSE update arrives late. Pausing, transitioning or leaving an active stage clears the visual cue; background tabs do not accumulate events.

## GPIO installation on Raspberry Pi 5

DigiFlot uses **gpiozero OutputDevice with LGPIOFactory** and BCM numbering, not the Raspberry Pi physical pin number. The pulse is **active-high, 3.3 V logic, 200 ms**. GPIO 17 is physical header pin 11; use any suitable GND pin as the logic return.

**Electrical safety:** Pi GPIO is 3.3 V logic and not 5 V tolerant. Never connect a motor, valve, relay coil or 5 V control line directly to the Pi. Use an appropriate isolated TTL input / optocoupler / transistor or driver circuit rated for the controlled device, and add protection for inductive loads.

The standard `src/install.sh` now installs `python3-gpiozero` and `python3-lgpio` and adds the service account to group `gpio`. On an **existing** installation updated without rerunning the installer, apply these one-time prerequisites before enabling GPIO:

```bash
sudo apt-get install -y python3-gpiozero python3-lgpio
sudo usermod -aG gpio digiflot
sudo systemctl restart digiflot
```

Confirm that the service user has access to `/dev/gpiochip*` and that GPIO17 is not already owned by another process. The configured pin is initialized on the first GPIO signal; an unavailable/busy pin produces an error warning without stopping camera or sensor acquisition. Pin selection is restricted to a safe general-purpose list that avoids the EZO I2C pins GPIO2/3 and common UART/SPI pins.

## Timing and delivery guarantees

1. The actual stage clock starts **after** camera and encoder setup. Startup overhead cannot turn into overdue scraping.
2. The orchestrator checks stage completion **before** scraping, so it never deliberately emits a signal for an expired stage.
3. After each event, the next deadline is calculated with a fresh monotonic timestamp, skipping missed intervals.
4. GPIO pulses use a **dedicated worker thread** with a single pending slot. Requests that would queue behind a pending pulse are dropped.
5. The worker rejects pulses older than one second and discards pending pulses when a stage ends, pauses, aborts or enters recovery. A generation guard prevents a pulse that was waiting on GPIO initialization from starting after cancellation.
6. Every logical scraping event is logged in `events.jsonl` with `scheduled_monotonic_s`, `actual_monotonic_s` and `delay_s`. GPIO delivery is logged separately as `SCRAPING_GPIO_PULSE` with `sent`, `expired`, `cancelled` or `error` status.
7. Event logging remains synchronous to retain durable audit events. The comparatively expensive complete runtime snapshot is updated every five scraping events rather than every event; stage, pause and completion events always persist. This reduces write overhead without claiming hard real-time behavior.

The goal is **approximately one-second accuracy**, not deterministic sub-second control under arbitrary CPU, camera or SD-card load. Validate timing under the actual two-camera recording profile before using GPIO to control process hardware.

## Verification checklist

- Run a flotation stage while recording both main video streams and the virtual Froth sensor.
- Inspect `events.jsonl`: `SCRAPING_SIGNAL.data.delay_s` measures scheduler delay; `SCRAPING_GPIO_PULSE.data.delay_s` measures physical trigger delay.
- Test a short stage: it must complete without a scraping signal after its deadline.
- Test Pause/Resume and Abort during scraping; no queued GPIO pulse should fire after the state change.
- Compare Whole Screen and Compact Banner alerts with audio and GPIO output modes and with Show Scraping Alert disabled.
- Inspect `journalctl -u digiflot -f` for hardware errors and check CPU, FPS and storage utilization using the Performance page.

Hardware-independent regression tests: `tests/test_scraping_timing.py` and `tests/test_scraping_alert.js`.
