"""Non-blocking, best-effort 3.3 V scraping TTL output for Raspberry Pi GPIO.

This is a control signal, not a motor driver. Pulses use BCM pin numbering.
The worker has a single pending slot: missed signals are dropped, never replayed.
"""
import queue
import threading
import time

# Avoid I2C 2/3 (Atlas), UART 14/15, SPI 7-11 and HAT EEPROM 0/1.
ALLOWED_GPIO_PINS = (4, 5, 6, 12, 13, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27)


def validate_gpio_pin(pin):
    if isinstance(pin, bool):
        raise ValueError("GPIO pin must be a BCM number, not a boolean.")
    try:
        value = int(pin)
    except (TypeError, ValueError) as error:
        raise ValueError("GPIO pin must be a BCM number.") from error
    if value not in ALLOWED_GPIO_PINS:
        raise ValueError("Unsupported or reserved BCM GPIO pin. Use a pin listed in Settings.")
    return value


def _output_device(pin):
    # Imported in the background worker so DigiFlot also works off the Pi.
    from gpiozero import OutputDevice
    from gpiozero.pins.lgpio import LGPIOFactory
    return OutputDevice(pin, active_high=True, initial_value=False, pin_factory=LGPIOFactory())


class ScrapingGPIO:
    """One dedicated output worker; it never blocks the experiment scheduler."""

    def __init__(self, pin=17, pulse_s=0.2, report=None, output_factory=None, max_age_s=1.0):
        self.pin = validate_gpio_pin(pin)
        self.pulse_s = float(pulse_s)
        if not 0.02 <= self.pulse_s <= 1.0:
            raise ValueError("GPIO pulse duration must be between 0.02 and 1.0 s.")
        self.max_age_s = float(max_age_s)
        self.report = report
        self.factory = output_factory or _output_device
        self._queue = queue.Queue(maxsize=1)
        self._stop = threading.Event()
        self._thread = None
        self._lock = threading.Lock()
        self._epoch = 0
        self.last_error = None
        self.last_delay_s = None
        self.dropped = 0

    def schedule(self, scheduled_at, stage_id=None, stage_attempt=None):
        """Queue at most one current request; never replay older missed slots."""
        with self._lock:
            if self._stop.is_set():
                return False
            if self._thread is None:
                self._thread = threading.Thread(target=self._run, daemon=True, name="digiflot-scraping-gpio")
                self._thread.start()
            try:
                self._queue.put_nowait((float(scheduled_at), stage_id, stage_attempt, self._epoch))
                return True
            except queue.Full:
                self.dropped += 1
                return False

    def _run(self):
        device = None
        while not self._stop.is_set():
            try:
                scheduled_at, stage_id, stage_attempt, epoch = self._queue.get(timeout=0.2)
            except queue.Empty:
                continue
            result = {"pin": self.pin, "scheduled_monotonic_s": scheduled_at,
                      "stage_id": stage_id, "stage_attempt": stage_attempt}
            try:
                if time.monotonic() - scheduled_at <= self.max_age_s and device is None:
                    device = self.factory(self.pin)
                triggered_at = time.monotonic()
                delay = max(0.0, triggered_at - scheduled_at)
                result.update(actual_monotonic_s=triggered_at, delay_s=delay)
                if delay > self.max_age_s:
                    result["status"] = "expired"
                else:
                    # Atomic with cancellation: the worker cannot start an old
                    # pulse after a stage has ended or the operator has paused.
                    with self._lock:
                        cancelled = epoch != self._epoch or self._stop.is_set()
                        if not cancelled:
                            device.on()
                    if cancelled:
                        result["status"] = "cancelled"
                    else:
                        self._stop.wait(self.pulse_s)
                        device.off()
                        result["status"] = "sent"
                        self.last_error = None
                self.last_delay_s = delay
            except Exception as error:
                self.last_error = str(error)
                result.update(status="error", error=self.last_error)
                if device is not None:
                    try: device.off()
                    except Exception: pass
                    try: device.close()
                    except Exception: pass
                    device = None
            finally:
                self._queue.task_done()
                if self.report is not None:
                    try: self.report(result)
                    except Exception: pass
        if device is not None:
            try: device.off()
            finally: device.close()

    def cancel_pending(self):
        """Invalidate queued/in-flight-but-not-started pulses after stage exit."""
        with self._lock:
            self._epoch += 1
            while True:
                try:
                    self._queue.get_nowait()
                    self._queue.task_done()
                except queue.Empty:
                    break

    def close(self):
        self.cancel_pending()
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=max(2.0, self.pulse_s + 1.0))
        self._thread = None

    def status(self):
        return {"pin": self.pin, "pulse_s": self.pulse_s, "pending": self._queue.qsize(),
                "last_error": self.last_error, "last_delay_s": self.last_delay_s, "dropped": self.dropped}
