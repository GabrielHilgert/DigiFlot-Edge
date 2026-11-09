"""Low-cost, stage-aware storage estimates for DigiFlot Edge.

Profiles are updated only after a completed acquisition. No video is opened or
decoded; camera byte/frame counters are provided by the existing recorder.
"""
import json
import math
import os
import shutil
from pathlib import Path

GIB = 1024 ** 3
DEFAULT_BYTES_PER_PIXEL = 0.5
DEFAULT_AUX_BYTES_PER_SECOND = 8 * 1024
FIXED_BYTES = 64 * 1024
VIDEO_SUFFIXES = {".mp4", ".m4v", ".avi", ".mjpeg", ".mjpg", ".mov", ".mkv", ".webm"}


def _positive(value, fallback):
    try:
        value = float(value)
        return value if math.isfinite(value) and value > 0 else fallback
    except (TypeError, ValueError, OverflowError):
        return fallback


def _save_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
    os.replace(temporary, path)


class StorageEstimator:
    def __init__(self, storage_root):
        self.storage_root = Path(storage_root)
        self.profile_path = self.storage_root / "performance" / "storage_profiles.json"
        try:
            with self.profile_path.open(encoding="utf-8") as handle:
                data = json.load(handle)
            self.profiles = data if isinstance(data, dict) and data.get("version") == 1 else {}
        except (OSError, ValueError, TypeError):
            self.profiles = {}
        self.profiles.setdefault("version", 1)
        self.profiles.setdefault("cameras", {})
        self.profiles.setdefault("auxiliary", {"bytes_per_second": DEFAULT_AUX_BYTES_PER_SECOND, "samples": 0})

    @staticmethod
    def camera_signature(camera, output_quality=90):
        if isinstance(camera, dict):
            ident = camera.get("id")
            size = camera.get("frame_size") or camera.get("size") or [640, 480]
            fps = camera.get("frame_rate", 10)
            quality = camera.get("quality", output_quality)
            output_type = (camera.get("recording") or {}).get("output_type", "mp4")
        else:
            ident = camera.id
            size = camera.frame_size
            fps = camera.frame_rate
            quality = camera.quality
            output_type = camera.recording_output_type
        width, height = (int(size[0]), int(size[1])) if size and len(size) == 2 else (640, 480)
        return {"camera_id": str(ident), "width": max(1, width), "height": max(1, height),
                "fps": _positive(fps, 10), "quality": int(quality), "output_type": str(output_type)}

    @staticmethod
    def _key(signature):
        return json.dumps(signature, sort_keys=True, separators=(",", ":"))

    def camera_bytes_per_frame(self, signature):
        profile = self.profiles["cameras"].get(self._key(signature), {})
        recorded = _positive(profile.get("bytes_per_frame"), None)
        if recorded is not None:
            return recorded, "history"
        pixels = signature["width"] * signature["height"]
        return max(64 * 1024, pixels * DEFAULT_BYTES_PER_PIXEL), "default"

    def disk(self):
        try:
            usage = shutil.disk_usage(self.storage_root)
            return {"total_bytes": usage.total, "used_bytes": usage.used, "free_bytes": usage.free,
                    "total_gb": usage.total / GIB, "free_gb": usage.free / GIB, "used_gb": usage.used / GIB}
        except (OSError, ValueError):
            return {"total_bytes": None, "used_bytes": None, "free_bytes": None,
                    "total_gb": None, "used_gb": None, "free_gb": None}

    def estimate(self, experiment, cameras, camera_required, auto_advance=False,
                 transition_delay_s=0, min_free_gb=2, safety_margin_pct=30):
        stages = experiment.get("stages") if isinstance(experiment, dict) else None
        if not isinstance(stages, list) or not stages:
            raise ValueError("The experiment does not define any stages.")
        durations, active = [], []
        for index, stage in enumerate(stages):
            if not isinstance(stage, dict):
                raise ValueError(f"Invalid stage {index + 1}.")
            duration = _positive(stage.get("duration"), None)
            if duration is None:
                raise ValueError(f"Stage {index + 1} has an invalid duration.")
            durations.append(duration)
            active.append(bool(camera_required(stage)))
        total_s = sum(durations)
        video_s = sum(seconds for seconds, enabled in zip(durations, active) if enabled)
        if auto_advance and len(stages) > 1:
            delay = max(0, float(transition_delay_s))
            total_s += delay * (len(stages) - 1)
            video_s += delay * sum(active[i] and active[i + 1] for i in range(len(active) - 1))
        cameras_info = []
        video_bytes = 0
        for camera in cameras:
            signature = self.camera_signature(camera)
            bpf, source = self.camera_bytes_per_frame(signature)
            rate = bpf * signature["fps"]
            size = math.ceil(rate * video_s)
            video_bytes += size
            cameras_info.append({"camera_id": signature["camera_id"], "bytes_per_frame": round(bpf),
                                 "rate_bytes_s": round(rate), "estimated_bytes": size, "source": source})
        auxiliary = self.profiles["auxiliary"]
        aux_rate = _positive(auxiliary.get("bytes_per_second"), DEFAULT_AUX_BYTES_PER_SECOND)
        aux_bytes = math.ceil(aux_rate * total_s + FIXED_BYTES)
        estimated = video_bytes + aux_bytes
        margin = max(0, float(safety_margin_pct)) / 100
        reserve = max(0, float(min_free_gb)) * GIB
        required = math.ceil(estimated * (1 + margin) + reserve)
        disk = self.disk()
        available = disk["free_bytes"]
        return {"estimated_bytes": estimated, "video_bytes": video_bytes, "auxiliary_bytes": aux_bytes,
                "auxiliary_rate_bytes_s": round(aux_rate), "camera_recording_s": round(video_s, 3),
                "experiment_duration_s": round(total_s, 3), "cameras": cameras_info, "disk": disk,
                "required_free_bytes": required, "reserve_bytes": math.ceil(reserve),
                "margin_percent": float(safety_margin_pct), "sufficient": None if available is None else available >= required,
                "unplanned_transitions": not auto_advance and len(stages) > 1}

    @staticmethod
    def _auxiliary_size(directory):
        total = 0
        for root, folders, files in os.walk(directory):
            folders[:] = [name for name in folders if name not in {"_results_cache", "__pycache__"}]
            for name in files:
                path = Path(root) / name
                if path.suffix.lower() in VIDEO_SUFFIXES:
                    continue
                try:
                    total += path.stat().st_size
                except OSError:
                    pass
        return total

    def record_completed(self, run_directory, measurements, duration_s):
        """Update simple moving averages once, after camera and sensor writers stop."""
        updated = False
        for item in measurements:
            frames = int(item.get("frame_count") or 0)
            size = int(item.get("byte_count") or 0)
            signature = item.get("signature")
            if not isinstance(signature, dict) or frames <= 0 or size <= 0:
                continue
            key = self._key(signature)
            cameras = self.profiles["cameras"]
            previous = cameras.get(key, {})
            current = size / frames
            count = int(previous.get("samples") or 0)
            old = _positive(previous.get("bytes_per_frame"), current)
            cameras[key] = {"bytes_per_frame": (old * min(count, 4) + current) / (min(count, 4) + 1),
                            "samples": count + 1}
            updated = True
        duration = _positive(duration_s, None)
        if duration is not None:
            auxiliary_size = self._auxiliary_size(Path(run_directory))
            rate = max(0.0, (auxiliary_size - FIXED_BYTES) / duration)
            old_profile = self.profiles["auxiliary"]
            count = int(old_profile.get("samples") or 0)
            old_rate = _positive(old_profile.get("bytes_per_second"), rate)
            old_profile["bytes_per_second"] = (old_rate * min(count, 4) + rate) / (min(count, 4) + 1)
            old_profile["samples"] = count + 1
            updated = True
        if updated:
            _save_json(self.profile_path, self.profiles)
        return updated
