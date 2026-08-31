import subprocess
import time
from copy import deepcopy
from pathlib import Path
from threading import Condition, RLock
from typing import Any

from picamera2 import Picamera2
from picamera2.encoders import JpegEncoder
from picamera2.outputs import Output


ALLOWED_PIXEL_FORMATS = (
    "YUV420",
    "RGB888",
)

EDITABLE_CONTROLS = (
    "Brightness",
    "Contrast",
    "Saturation",
    "Sharpness",
    "AwbEnable",
    "AwbMode",
)

AWB_MODE_LABELS = {
    0: "Auto",
    1: "Incandescent",
    2: "Tungsten",
    3: "Fluorescent",
    4: "Indoor",
    5: "Daylight",
    6: "Cloudy",
    7: "Custom",
}


class FFmpegOutput(Output):
    def __init__(self, process):
        super().__init__()
        self.process = process
        self.frame_count = 0
        self.byte_count = 0
        self.started_monotonic = time.monotonic()
        self.last_frame_monotonic = None

    def outputframe(
        self,
        frame,
        keyframe=True,
        timestamp=None,
        packet=None,
        audio=False,
    ):
        try:
            if self.process.stdin:
                self.process.stdin.write(frame)
                self.frame_count += 1
                self.byte_count += len(frame)
                self.last_frame_monotonic = time.monotonic()
        except BrokenPipeError:
            pass


class PreviewOutput(Output):
    def __init__(self):
        super().__init__()
        self.condition = Condition()
        self.frame = None
        self.sequence = 0
        self.closed = False

    def outputframe(
        self,
        frame,
        keyframe=True,
        timestamp=None,
        packet=None,
        audio=False,
    ):
        with self.condition:
            self.frame = bytes(frame)
            self.sequence += 1
            self.condition.notify_all()

    def close_stream(self):
        with self.condition:
            self.closed = True
            self.condition.notify_all()


class Camera:
    IDLE = "Idle"
    PREVIEW = "Preview"
    RECORDING = "Recording"

    def __init__(
        self,
        config: dict,
        output_config: dict,
        hardware_info: dict | None = None,
    ):
        self.config = config
        self.output_config = output_config
        self.hardware_info = hardware_info or {}

        self.id = int(config["id"])
        self.picam2 = Picamera2(self.id)

        self.preview_encoder = None
        self.preview_output = None

        self.encoder = None
        self.output = None
        self.ffmpeg = None

        self.state = self.IDLE
        self.lock = RLock()

        self.refresh_from_config()
        self.validate_config(self.config)

    def refresh_from_config(self):
        self.name = str(self.config["name"])
        self.frame_rate = float(self.config["frame_rate"])
        self.format = str(self.config["format"])
        self.crop_region = self.validate_crop_region(
            self.config.get("crop_region")
        )
        self.frame_size = self.output_size_from_crop(
            self.crop_region
        )

        # The acquisition output is always the selected sensor region.
        # frame_size is retained in config.json for readability/backward
        # compatibility, but it is derived from crop_region and is not an
        # independent scaling target.
        self.config["frame_size"] = list(self.frame_size)
        self.config["crop_region"] = (
            list(self.crop_region)
            if self.crop_region is not None
            else None
        )

        recording = self.config.setdefault(
            "recording",
            {"output_type": "mjpeg"},
        )
        self.recording_output_type = str(
            recording.get("output_type", "mjpeg")
        )

        preview = self.config.setdefault(
            "preview",
            {},
        )
        self.preview_size = self.native_preview_size(
            preview.get(
                "size",
                [640, 480],
            )
        )
        preview["size"] = list(self.preview_size)
        self.preview_frame_rate = float(
            preview.get(
                "frame_rate",
                min(10.0, self.frame_rate),
            )
        )
        self.preview_quality = int(
            preview.get("quality", 75)
        )
        self.preview_encoder_threads = int(
            preview.get("encoder_threads", 1)
        )

        exposure = self.config.setdefault(
            "exposure",
            {},
        )
        self.exposure_time_us = exposure.get(
            "exposure_time_us"
        )
        self.analogue_gain = exposure.get(
            "analogue_gain"
        )
        self.exposure_calibration_frames = int(
            exposure.get("calibration_frames", 30)
        )
        self.exposure_settle_frames = int(
            exposure.get("settle_frames", 5)
        )

        self.controls = self.config.setdefault(
            "controls",
            {},
        )

        self.quality = int(
            self.output_config.get("quality", 90)
        )

    @staticmethod
    def _normalise_value(value):
        if hasattr(value, "value"):
            return value.value

        if isinstance(value, tuple):
            return [
                Camera._normalise_value(item)
                for item in value
            ]

        if isinstance(value, list):
            return [
                Camera._normalise_value(item)
                for item in value
            ]

        if isinstance(value, dict):
            return {
                key: Camera._normalise_value(item)
                for key, item in value.items()
            }

        return value

    @staticmethod
    def _rectangle_to_tuple(rectangle):
        if rectangle is None:
            return None

        if isinstance(rectangle, (tuple, list)):
            if len(rectangle) == 4:
                return tuple(int(value) for value in rectangle)

        attributes = ("x", "y", "width", "height")
        if all(hasattr(rectangle, name) for name in attributes):
            return tuple(
                int(getattr(rectangle, name))
                for name in attributes
            )

        return None

    def full_sensor_crop(self):
        sensor_width, sensor_height = self.picam2.sensor_resolution
        fallback = (0, 0, sensor_width, sensor_height)

        crops = []
        try:
            for mode in self.picam2.sensor_modes:
                crop = self._rectangle_to_tuple(
                    mode.get("crop_limits")
                )
                if crop is not None:
                    crops.append(crop)
        except Exception:
            pass

        if not crops:
            return fallback

        return max(
            crops,
            key=lambda crop: crop[2] * crop[3],
        )

    def full_fov_sensor_modes(self):
        full = self.full_sensor_crop()
        modes = []

        try:
            for mode in self.picam2.sensor_modes:
                crop = self._rectangle_to_tuple(
                    mode.get("crop_limits")
                )
                if crop == full:
                    modes.append(mode)
        except Exception:
            pass

        return modes

    @staticmethod
    def _mode_contains_crop(mode, crop_region):
        limits = Camera._rectangle_to_tuple(
            mode.get("crop_limits")
        )
        if limits is None:
            return False

        lx, ly, lw, lh = limits
        x, y, width, height = crop_region

        return (
            x >= lx
            and y >= ly
            and x + width <= lx + lw
            and y + height <= ly + lh
        )

    def select_sensor_mode(
        self,
        crop_region=None,
        require_full_fov=False,
    ):
        target_crop = (
            self.full_sensor_crop()
            if crop_region is None
            else tuple(crop_region)
        )

        candidates = []
        try:
            for mode in self.picam2.sensor_modes:
                fps = mode.get("fps")
                size = mode.get("size")
                bit_depth = mode.get("bit_depth")
                if fps is None or size is None or bit_depth is None:
                    continue

                if float(fps) + 0.01 < self.frame_rate:
                    continue

                if require_full_fov:
                    if self._rectangle_to_tuple(
                        mode.get("crop_limits")
                    ) != self.full_sensor_crop():
                        continue
                elif not self._mode_contains_crop(
                    mode,
                    target_crop,
                ):
                    continue

                candidates.append(mode)
        except Exception:
            candidates = []

        if not candidates:
            mode_type = (
                "full-field-of-view"
                if require_full_fov
                else "crop-compatible"
            )
            raise RuntimeError(
                f"No {mode_type} sensor mode supports "
                f"{self.frame_rate:g} fps for {self.name}."
            )

        # Prefer the smallest sensor output that still covers the requested
        # field of view. This minimizes preview/recording bandwidth while
        # keeping the selected crop valid.
        return min(
            candidates,
            key=lambda mode: (
                int(mode["size"][0]) * int(mode["size"][1]),
                -int(mode.get("bit_depth", 0)),
            ),
        )

    def native_preview_size(self, requested_size):
        full_x, full_y, full_width, full_height = (
            self.full_sensor_crop()
        )
        del full_x, full_y

        requested_width = max(2, int(requested_size[0]))
        requested_width = min(requested_width, full_width)
        requested_width -= requested_width % 2

        height = round(
            requested_width * full_height / full_width
        )
        if height % 2:
            height += 1

        if height > full_height:
            height = full_height - (full_height % 2)
            requested_width = round(
                height * full_width / full_height
            )
            requested_width -= requested_width % 2

        return (requested_width, max(2, height))

    def crop_capabilities(self):
        full = self.full_sensor_crop()

        # ScalerCrop minima depend on the currently configured sensor mode.
        # The UI works in stable full-sensor coordinates, so only expose a
        # small positive minimum here and validate the final region again
        # after the recording mode is configured.
        return {
            "minimum": [full[0], full[1], 2, 2],
            "maximum": list(full),
            "default": list(full),
        }

    def validate_crop_region(self, crop_region):
        if crop_region is None:
            return None

        if len(crop_region) != 4:
            raise ValueError(
                "crop_region must contain x, y, width and height."
            )

        x, y, width, height = (
            int(round(float(value)))
            for value in crop_region
        )

        full_x, full_y, full_width, full_height = (
            self.full_sensor_crop()
        )
        full_right = full_x + full_width
        full_bottom = full_y + full_height

        if width <= 0 or height <= 0:
            raise ValueError(
                "Crop width and height must be positive."
            )

        # Browser-to-sensor conversion can differ by a pixel after rounding.
        # Accept that numerical tolerance, then clamp to the real sensor area.
        tolerance = 2
        if (
            x < full_x - tolerance
            or y < full_y - tolerance
            or x + width > full_right + tolerance
            or y + height > full_bottom + tolerance
        ):
            raise ValueError(
                "Crop region is outside the full sensor area."
            )

        x = max(full_x, min(x, full_right - 2))
        y = max(full_y, min(y, full_bottom - 2))
        width = max(2, min(width, full_right - x))
        height = max(2, min(height, full_bottom - y))

        # The saved acquisition stream uses the crop dimensions directly.
        # Keep output dimensions even so YUV420/JPEG pipelines do not need
        # an additional one-pixel resize. At most one pixel is removed from
        # the right/bottom edge of a mouse selection.
        width -= width % 2
        height -= height % 2
        width = max(2, width)
        height = max(2, height)

        return (x, y, width, height)

    def output_size_from_crop(self, crop_region):
        if crop_region is None:
            _, _, width, height = self.full_sensor_crop()
            return (int(width), int(height))

        _, _, width, height = crop_region
        return (int(width), int(height))

    def normalise_geometry_config(self, config: dict):
        crop = self.validate_crop_region(
            config.get("crop_region")
        )
        config["crop_region"] = (
            list(crop)
            if crop is not None
            else None
        )
        config["frame_size"] = list(
            self.output_size_from_crop(crop)
        )
        return config

    def max_sensor_fps(self):
        values = []

        try:
            for mode in self.picam2.sensor_modes:
                fps = mode.get("fps")
                if fps is not None:
                    values.append(float(fps))
        except Exception:
            pass

        return max(values) if values else 120.0

    def validate_config(self, config: dict):
        name = str(config.get("name", "")).strip()
        if not name:
            raise ValueError("Camera name cannot be empty.")
        if len(name) > 64:
            raise ValueError(
                "Camera name must contain at most 64 characters."
            )

        frame_size = config.get("frame_size")
        if not frame_size or len(frame_size) != 2:
            raise ValueError(
                "frame_size must contain width and height."
            )

        width, height = (
            int(value)
            for value in frame_size
        )
        sensor_width, sensor_height = self.picam2.sensor_resolution

        if width <= 0 or height <= 0:
            raise ValueError(
                "Frame dimensions must be positive."
            )
        if width > sensor_width or height > sensor_height:
            raise ValueError(
                "Frame dimensions cannot exceed the sensor resolution."
            )

        crop = self.validate_crop_region(
            config.get("crop_region")
        )
        expected_size = self.output_size_from_crop(crop)
        if (width, height) != expected_size:
            raise ValueError(
                "frame_size is derived from crop_region and must equal "
                f"{expected_size[0]}x{expected_size[1]}."
            )

        pixel_format = str(config.get("format", ""))
        if pixel_format not in ALLOWED_PIXEL_FORMATS:
            raise ValueError(
                "Unsupported pixel format. Allowed values: "
                + ", ".join(ALLOWED_PIXEL_FORMATS)
            )

        if pixel_format == "YUV420" and (
            width % 2 != 0 or height % 2 != 0
        ):
            raise ValueError(
                "YUV420 frame dimensions must be even."
            )

        frame_rate = float(config.get("frame_rate", 0))
        if frame_rate <= 0:
            raise ValueError("frame_rate must be greater than zero.")
        if frame_rate > self.max_sensor_fps() + 0.01:
            raise ValueError(
                "frame_rate exceeds the maximum reported sensor rate."
            )

        recording = config.get("recording", {})
        output_type = recording.get("output_type", "mjpeg")
        if output_type not in ("mjpeg", "mp4"):
            raise ValueError(
                "recording.output_type must be 'mjpeg' or 'mp4'."
            )

        preview = config.get("preview", {})
        preview_size = preview.get("size", [640, 360])
        if len(preview_size) != 2:
            raise ValueError(
                "preview.size must contain width and height."
            )

        preview_width, preview_height = (
            int(value)
            for value in preview_size
        )
        if preview_width <= 0 or preview_height <= 0:
            raise ValueError(
                "Preview dimensions must be positive."
            )
        full_x, full_y, full_width, full_height = (
            self.full_sensor_crop()
        )
        del full_x, full_y

        if (
            preview_width > full_width
            or preview_height > full_height
        ):
            raise ValueError(
                "Preview dimensions cannot exceed the full sensor area."
            )
        if preview_width % 2 or preview_height % 2:
            raise ValueError(
                "Preview dimensions must be even for YUV420."
            )

        expected_preview = self.native_preview_size(
            (preview_width, preview_height)
        )
        if (preview_width, preview_height) != expected_preview:
            raise ValueError(
                "Preview size must preserve the native sensor aspect ratio. "
                f"For width {preview_width}, use height "
                f"{expected_preview[1]}."
            )

        preview_rate = float(
            preview.get("frame_rate", min(10.0, frame_rate))
        )
        if preview_rate <= 0 or preview_rate > frame_rate:
            raise ValueError(
                "preview.frame_rate must be > 0 and <= frame_rate."
            )

        quality = int(preview.get("quality", 75))
        if quality < 1 or quality > 100:
            raise ValueError(
                "preview.quality must be between 1 and 100."
            )

        encoder_threads = int(
            preview.get("encoder_threads", 1)
        )
        if encoder_threads < 1 or encoder_threads > 4:
            raise ValueError(
                "preview.encoder_threads must be between 1 and 4."
            )

        exposure = config.get("exposure", {})
        calibration_frames = int(
            exposure.get("calibration_frames", 30)
        )
        settle_frames = int(
            exposure.get("settle_frames", 5)
        )
        if calibration_frames < 1 or calibration_frames > 300:
            raise ValueError(
                "exposure.calibration_frames must be between 1 and 300."
            )
        if settle_frames < 0 or settle_frames > 100:
            raise ValueError(
                "exposure.settle_frames must be between 0 and 100."
            )

        exposure_time = exposure.get("exposure_time_us")
        analogue_gain = exposure.get("analogue_gain")
        if exposure_time is not None or analogue_gain is not None:
            if exposure_time is None or analogue_gain is None:
                raise ValueError(
                    "Exposure time and analogue gain must be stored together."
                )
            self.validate_exposure_values(
                exposure_time,
                analogue_gain,
            )

        self.validate_controls(
            config.get("controls", {})
        )

    def validate_exposure_values(
        self,
        exposure_time_us,
        analogue_gain,
    ):
        exposure_time_us = int(exposure_time_us)
        analogue_gain = float(analogue_gain)

        if exposure_time_us <= 0:
            raise ValueError(
                "Exposure time must be greater than zero."
            )
        if analogue_gain <= 0:
            raise ValueError(
                "Analogue gain must be greater than zero."
            )

        for name, value in (
            ("ExposureTime", exposure_time_us),
            ("AnalogueGain", analogue_gain),
        ):
            capability = self.picam2.camera_controls.get(name)
            if not capability or len(capability) < 2:
                continue

            minimum = self._normalise_value(capability[0])
            maximum = self._normalise_value(capability[1])

            if isinstance(minimum, (int, float)) and value < minimum:
                raise ValueError(
                    f"{name} is below the camera minimum ({minimum})."
                )
            if isinstance(maximum, (int, float)) and value > maximum:
                raise ValueError(
                    f"{name} is above the camera maximum ({maximum})."
                )

    def validate_controls(self, controls: dict):
        for name, value in controls.items():
            if name not in EDITABLE_CONTROLS:
                raise ValueError(
                    f"Control '{name}' is not editable in DigiFlot."
                )

            if name not in self.picam2.camera_controls:
                # Optional UI controls can differ between camera models.
                # Keep the stored value, but do not make the whole camera
                # configuration invalid when a control is unavailable.
                continue

            if name == "AwbEnable":
                if not isinstance(value, bool):
                    raise ValueError("AwbEnable must be boolean.")
                continue

            if name == "AwbMode":
                value = int(value)
            else:
                value = float(value)

            capability = self.picam2.camera_controls[name]
            if len(capability) >= 2:
                minimum = self._normalise_value(capability[0])
                maximum = self._normalise_value(capability[1])

                if isinstance(minimum, (int, float)) and value < minimum:
                    raise ValueError(
                        f"{name} is below the supported minimum ({minimum})."
                    )
                if isinstance(maximum, (int, float)) and value > maximum:
                    raise ValueError(
                        f"{name} is above the supported maximum ({maximum})."
                    )

    def update_config(self, updates: dict):
        with self.lock:
            if self.state != self.IDLE:
                raise RuntimeError(
                    "Camera configuration can only be changed while Idle."
                )

            candidate = deepcopy(self.config)
            self._deep_update(candidate, updates)
            self.normalise_geometry_config(candidate)
            self.validate_config(candidate)

            self.config.clear()
            self.config.update(candidate)
            self.refresh_from_config()

            return self.config

    @staticmethod
    def _deep_update(target: dict, updates: dict):
        for key, value in updates.items():
            if (
                isinstance(value, dict)
                and isinstance(target.get(key), dict)
            ):
                Camera._deep_update(target[key], value)
            else:
                target[key] = deepcopy(value)

    @property
    def recording(self):
        return self.state == self.RECORDING

    @property
    def exposure(self):
        return {
            "exposure_time_us": self.exposure_time_us,
            "analogue_gain": self.analogue_gain,
        }

    @property
    def status(self):
        return {
            "id": self.id,
            "name": self.name,
            "state": self.state,
            "exposure": self.exposure,
        }

    def hardware_metadata(self):
        sensor_width, sensor_height = self.picam2.sensor_resolution
        properties = self.picam2.camera_properties

        return {
            "id": self.id,
            "model": (
                self.hardware_info.get("Model")
                or properties.get("Model")
                or "Unknown"
            ),
            "location": self._normalise_value(
                self.hardware_info.get("Location")
            ),
            "rotation": self._normalise_value(
                self.hardware_info.get("Rotation")
            ),
            "sensor_resolution": [sensor_width, sensor_height],
            "sensor_format": str(
                getattr(self.picam2, "sensor_format", "")
            ),
            "colour_filter_arrangement": self._normalise_value(
                properties.get("ColorFilterArrangement")
            ),
        }

    def control_capabilities(self):
        result = {}

        for name in EDITABLE_CONTROLS:
            capability = self.picam2.camera_controls.get(name)
            if not capability:
                continue

            minimum = self._normalise_value(capability[0])
            maximum = self._normalise_value(capability[1])
            default = (
                self._normalise_value(capability[2])
                if len(capability) > 2
                else None
            )

            value = self.controls.get(name, default)

            item = {
                "value": value,
                "minimum": minimum,
                "maximum": maximum,
                "default": default,
                "type": "number",
            }

            if name == "AwbEnable":
                item["type"] = "boolean"

            if name == "AwbMode":
                item["type"] = "enum"
                start = int(minimum) if isinstance(minimum, int) else 0
                end = int(maximum) if isinstance(maximum, int) else 7
                item["options"] = [
                    {
                        "value": mode,
                        "label": AWB_MODE_LABELS.get(
                            mode,
                            f"Mode {mode}",
                        ),
                    }
                    for mode in range(start, end + 1)
                ]

            result[name] = item

        return result

    def exposure_capabilities(self):
        result = {}

        for name in ("ExposureTime", "AnalogueGain"):
            capability = self.picam2.camera_controls.get(name)
            if not capability:
                continue

            result[name] = {
                "minimum": self._normalise_value(capability[0]),
                "maximum": self._normalise_value(capability[1]),
                "default": (
                    self._normalise_value(capability[2])
                    if len(capability) > 2
                    else None
                ),
            }

        return result

    def configuration_payload(self):
        return {
            "id": self.id,
            "name": self.name,
            "state": self.state,
            "hardware": self.hardware_metadata(),
            "frame_size": list(self.frame_size),
            "frame_rate": self.frame_rate,
            "format": self.format,
            "crop_region": (
                list(self.crop_region)
                if self.crop_region is not None
                else None
            ),
            "recording": deepcopy(
                self.config["recording"]
            ),
            "preview": deepcopy(
                self.config["preview"]
            ),
            "exposure": deepcopy(
                self.config["exposure"]
            ),
            "controls": deepcopy(self.controls),
            "capabilities": {
                "pixel_formats": list(ALLOWED_PIXEL_FORMATS),
                "recording_output_types": ["mjpeg", "mp4"],
                "max_sensor_fps": self.max_sensor_fps(),
                "crop": self.crop_capabilities(),
                "exposure": self.exposure_capabilities(),
                "controls": self.control_capabilities(),
            },
        }

    def _sensor_config_from_mode(self, mode):
        return {
            "output_size": tuple(mode["size"]),
            "bit_depth": int(mode["bit_depth"]),
        }

    def create_preview_configuration(self):
        mode = self.select_sensor_mode(
            require_full_fov=True
        )

        return self.picam2.create_video_configuration(
            main={
                "size": self.preview_size,
                "format": "YUV420",
            },
            lores={
                "size": self.preview_size,
                "format": "YUV420",
            },
            controls={
                "FrameRate": self.frame_rate,
            },
            sensor=self._sensor_config_from_mode(mode),
            display=None,
            encode="lores",
        )

    def create_recording_configuration(self):
        mode = self.select_sensor_mode(
            crop_region=self.crop_region,
            require_full_fov=(self.crop_region is None),
        )

        return self.picam2.create_video_configuration(
            main={
                # frame_size is exactly the selected crop size. This avoids
                # imposing a second, unrelated aspect ratio on the saved image.
                "size": self.frame_size,
                "format": self.format,
            },
            controls={
                "FrameRate": self.frame_rate,
            },
            sensor=self._sensor_config_from_mode(mode),
            display=None,
            encode="main",
        )

    def _base_runtime_controls(self):
        controls = {
            "FrameRate": self.frame_rate,
        }

        for name, value in self.controls.items():
            if name in self.picam2.camera_controls:
                controls[name] = value

        return controls

    def apply_preview_controls(self):
        controls = self._base_runtime_controls()
        controls["ScalerCrop"] = self.full_sensor_crop()
        self.picam2.set_controls(controls)

    def apply_recording_controls(self):
        controls = self._base_runtime_controls()

        if self.crop_region is not None:
            controls["ScalerCrop"] = self.crop_region
        else:
            controls["ScalerCrop"] = self.full_sensor_crop()

        self.picam2.set_controls(controls)

    def apply_saved_exposure(self):
        if (
            self.exposure_time_us is None
            or self.analogue_gain is None
        ):
            self.picam2.set_controls({
                "AeEnable": True,
            })
            return False

        self.picam2.set_controls({
            "AeEnable": False,
            "ExposureTime": int(self.exposure_time_us),
            "AnalogueGain": float(self.analogue_gain),
        })
        return True

    def update_exposure_from_metadata(self):
        metadata = self.picam2.capture_metadata()

        self.exposure_time_us = int(
            metadata["ExposureTime"]
        )
        self.analogue_gain = float(
            metadata["AnalogueGain"]
        )

        exposure = self.config.setdefault("exposure", {})
        exposure["exposure_time_us"] = self.exposure_time_us
        exposure["analogue_gain"] = self.analogue_gain

        return self.exposure

    def start_preview(self):
        with self.lock:
            if self.state == self.PREVIEW:
                return self.status

            if self.state != self.IDLE:
                raise RuntimeError(
                    f"{self.name} cannot enter Preview from {self.state}."
                )

            preview_output = PreviewOutput()
            preview_encoder = JpegEncoder(
                num_threads=self.preview_encoder_threads,
                q=self.preview_quality,
            )

            preview_encoder.frame_skip_count = max(
                1,
                round(
                    self.frame_rate
                    / self.preview_frame_rate
                ),
            )

            try:
                self.picam2.configure(
                    self.create_preview_configuration()
                )
                self.apply_preview_controls()
                self.apply_saved_exposure()

                self.picam2.start()

                self.preview_output = preview_output
                self.preview_encoder = preview_encoder

                self.picam2.start_encoder(
                    encoder=self.preview_encoder,
                    output=self.preview_output,
                    name="lores",
                )

                self.state = self.PREVIEW

            except Exception:
                try:
                    if self.preview_encoder is not None:
                        self.picam2.stop_encoder(
                            self.preview_encoder
                        )
                except Exception:
                    pass

                try:
                    self.picam2.stop()
                except Exception:
                    pass

                preview_output.close_stream()
                self.preview_encoder = None
                self.preview_output = None
                self.state = self.IDLE
                raise

            return self.status

    def stop_preview(self):
        with self.lock:
            if self.state != self.PREVIEW:
                return self.status

            output = self.preview_output
            if output is not None:
                output.close_stream()

            encoder_error = None

            try:
                if self.preview_encoder is not None:
                    try:
                        self.picam2.stop_encoder(
                            self.preview_encoder
                        )
                    except Exception as error:
                        encoder_error = error
            finally:
                self.preview_encoder = None
                self.preview_output = None

                try:
                    self.picam2.stop()
                finally:
                    self.state = self.IDLE

            if encoder_error is not None:
                raise encoder_error

            return self.status

    def calibrate_exposure(self):
        with self.lock:
            if self.state != self.PREVIEW:
                raise RuntimeError(
                    "Exposure calibration requires Preview state."
                )

            self.picam2.set_controls({
                "AeEnable": True,
            })

            metadata = None
            for _ in range(self.exposure_calibration_frames):
                metadata = self.picam2.capture_metadata()

            self.exposure_time_us = int(
                metadata["ExposureTime"]
            )
            self.analogue_gain = float(
                metadata["AnalogueGain"]
            )

            self.picam2.set_controls({
                "AeEnable": False,
                "ExposureTime": self.exposure_time_us,
                "AnalogueGain": self.analogue_gain,
            })

            for _ in range(self.exposure_settle_frames):
                metadata = self.picam2.capture_metadata()

            self.exposure_time_us = int(
                metadata["ExposureTime"]
            )
            self.analogue_gain = float(
                metadata["AnalogueGain"]
            )

            exposure = self.config.setdefault("exposure", {})
            exposure["exposure_time_us"] = self.exposure_time_us
            exposure["analogue_gain"] = self.analogue_gain

            return self.exposure

    def set_exposure(
        self,
        exposure_time_us: int,
        analogue_gain: float,
    ):
        with self.lock:
            if self.state != self.PREVIEW:
                raise RuntimeError(
                    "Manual exposure can only be applied in Preview state."
                )

            self.validate_exposure_values(
                exposure_time_us,
                analogue_gain,
            )

            self.picam2.set_controls({
                "AeEnable": False,
                "ExposureTime": int(exposure_time_us),
                "AnalogueGain": float(analogue_gain),
            })

            metadata = None
            for _ in range(self.exposure_settle_frames):
                metadata = self.picam2.capture_metadata()

            if metadata is None:
                metadata = self.picam2.capture_metadata()

            self.exposure_time_us = int(
                metadata["ExposureTime"]
            )
            self.analogue_gain = float(
                metadata["AnalogueGain"]
            )

            exposure = self.config.setdefault("exposure", {})
            exposure["exposure_time_us"] = self.exposure_time_us
            exposure["analogue_gain"] = self.analogue_gain

            return self.exposure

    def set_controls(self, controls: dict):
        with self.lock:
            self.validate_controls(controls)

            self.controls.update(controls)

            if self.state == self.PREVIEW:
                self.picam2.set_controls(controls)

            return deepcopy(self.controls)

    def start_recording(
        self,
        output_base: Path,
        output_type: str | None = None,
    ):
        with self.lock:
            if self.state != self.IDLE:
                raise RuntimeError(
                    f"{self.name} cannot enter Recording from {self.state}."
                )

            if (
                self.exposure_time_us is None
                or self.analogue_gain is None
            ):
                raise RuntimeError(
                    f"{self.name} must be calibrated before recording."
                )

            output_type = (
                output_type
                or self.recording_output_type
            )

            if output_type not in ("mjpeg", "mp4"):
                raise ValueError(
                    f"Invalid output type: {output_type}"
                )

            output_base = Path(output_base)
            output_base.parent.mkdir(
                parents=True,
                exist_ok=True,
            )

            output_path = (
                output_base.with_suffix(".avi")
                if output_type == "mjpeg"
                else output_base.with_suffix(".mp4")
            )

            command = [
                "ffmpeg",
                "-y",
                "-loglevel",
                self.output_config.get(
                    "ffmpeg_log_level",
                    "warning",
                ),
                "-f",
                "mjpeg",
                "-framerate",
                str(self.frame_rate),
                "-i",
                "pipe:0",
                "-an",
                "-c:v",
                "copy",
            ]

            if output_type == "mjpeg":
                command += [
                    "-f",
                    "avi",
                    str(output_path),
                ]
            else:
                command += [
                    str(output_path),
                ]

            try:
                self.picam2.configure(
                    self.create_recording_configuration()
                )
                self.apply_recording_controls()

                self.picam2.set_controls({
                    "AeEnable": False,
                    "ExposureTime": int(
                        self.exposure_time_us
                    ),
                    "AnalogueGain": float(
                        self.analogue_gain
                    ),
                })

                self.picam2.start()

                self.ffmpeg = subprocess.Popen(
                    command,
                    stdin=subprocess.PIPE,
                )

                self.encoder = JpegEncoder(
                    q=self.quality
                )
                self.output = FFmpegOutput(
                    self.ffmpeg
                )

                self.picam2.start_encoder(
                    encoder=self.encoder,
                    output=self.output,
                    name="main",
                )

                self.state = self.RECORDING

            except Exception:
                self.cleanup_failed_recording()
                raise

            return output_path

    def cleanup_failed_recording(self):
        try:
            if self.encoder is not None:
                self.picam2.stop_encoder(
                    self.encoder
                )
        except Exception:
            pass

        if self.ffmpeg is not None:
            try:
                if self.ffmpeg.stdin:
                    self.ffmpeg.stdin.close()
            except Exception:
                pass

            try:
                self.ffmpeg.terminate()
                self.ffmpeg.wait(timeout=2)
            except Exception:
                try:
                    self.ffmpeg.kill()
                except Exception:
                    pass

        try:
            self.picam2.stop()
        except Exception:
            pass

        self.encoder = None
        self.output = None
        self.ffmpeg = None
        self.state = self.IDLE

    def stop_recording(self):
        with self.lock:
            if self.state != self.RECORDING:
                return self.status

            encoder_error = None
            return_code = None

            try:
                try:
                    if self.encoder is not None:
                        self.picam2.stop_encoder(
                            self.encoder
                        )
                except Exception as error:
                    encoder_error = error

                if (
                    self.ffmpeg is not None
                    and self.ffmpeg.stdin
                ):
                    self.ffmpeg.stdin.close()

                if self.ffmpeg is not None:
                    return_code = self.ffmpeg.wait()

            finally:
                self.encoder = None
                self.output = None
                self.ffmpeg = None

                try:
                    self.picam2.stop()
                finally:
                    self.state = self.IDLE

            if encoder_error is not None:
                raise encoder_error

            if return_code not in (None, 0):
                raise RuntimeError(
                    f"FFmpeg failed for {self.name}: {return_code}"
                )

            return self.status

    def recording_metrics(self):
        output = self.output
        if output is None or not hasattr(output, "frame_count"):
            return {
                "frame_count": 0,
                "byte_count": 0,
                "elapsed_s": 0.0,
                "actual_fps": 0.0,
                "write_rate_mbps": 0.0,
                "last_frame_age_s": None,
            }

        now = time.monotonic()
        elapsed = max(0.0, now - output.started_monotonic)
        last_age = (
            None
            if output.last_frame_monotonic is None
            else max(0.0, now - output.last_frame_monotonic)
        )
        return {
            "frame_count": int(output.frame_count),
            "byte_count": int(output.byte_count),
            "elapsed_s": elapsed,
            "actual_fps": (output.frame_count / elapsed) if elapsed > 0 else 0.0,
            "write_rate_mbps": (output.byte_count / elapsed / 1_000_000.0) if elapsed > 0 else 0.0,
            "last_frame_age_s": last_age,
        }

    def close(self):
        with self.lock:
            if self.state == self.PREVIEW:
                self.stop_preview()
            elif self.state == self.RECORDING:
                self.stop_recording()

            self.picam2.close()
