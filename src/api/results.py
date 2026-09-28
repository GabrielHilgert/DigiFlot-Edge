import csv
import json
import math
import mimetypes
import re
from pathlib import Path
from typing import Iterable
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse

from api.local import get_local_directory, read_local_experiment, read_runtime_state


router = APIRouter(
    prefix="/api/results",
    tags=["results"],
)

_NUMBER_PATTERN = re.compile(r"[-+]?(?:\d+(?:[.,]\d*)?|[.,]\d+)(?:[eE][-+]?\d+)?")
_VIDEO_SUFFIXES = {".mp4", ".avi", ".mjpeg", ".mov", ".mkv", ".webm"}
_TEXT_SUFFIXES = {".json", ".jsonl", ".tsv", ".csv", ".txt", ".log"}
_MAX_TEXT_PREVIEW_BYTES = 512 * 1024
_SENSOR_META_CACHE = {}


def _read_json(path: Path, default=None):
    try:
        with path.open("r", encoding="utf-8") as file:
            return json.load(file)
    except (OSError, json.JSONDecodeError):
        return default


def _read_jsonl(path: Path, limit: int | None = None):
    rows = []
    if not path.is_file():
        return rows
    try:
        with path.open("r", encoding="utf-8") as file:
            for line in file:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
                if limit is not None and len(rows) >= limit:
                    break
    except OSError:
        return []
    return rows


def _safe_relative_path(directory: Path, relative: str) -> Path:
    relative = str(relative or "").strip().replace("\\", "/")
    if not relative or relative.startswith("/"):
        raise HTTPException(status_code=400, detail="Invalid file path.")

    root = directory.resolve()
    path = (directory / relative).resolve()
    try:
        path.relative_to(root)
    except ValueError as error:
        raise HTTPException(status_code=400, detail="Invalid file path.") from error

    if not path.is_file():
        raise HTTPException(status_code=404, detail="File not found.")
    return path


def _relative(directory: Path, path: Path) -> str:
    return path.relative_to(directory).as_posix()


def _file_kind(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in _VIDEO_SUFFIXES:
        return "video"
    if suffix == ".json":
        return "json"
    if suffix == ".jsonl":
        return "jsonl"
    if suffix in {".tsv", ".csv"}:
        return "table"
    if suffix in {".txt", ".log"}:
        return "text"
    return "file"


def _iter_files(directory: Path) -> Iterable[Path]:
    for path in sorted(directory.rglob("*")):
        if path.is_file():
            yield path


def _file_manifest(directory: Path):
    files = []
    total_size = 0
    for path in _iter_files(directory):
        try:
            size = path.stat().st_size
        except OSError:
            size = 0
        total_size += size
        rel = _relative(directory, path)
        files.append({
            "path": rel,
            "name": path.name,
            "directory": str(Path(rel).parent).replace(".", ""),
            "size_bytes": size,
            "kind": _file_kind(path),
            "modified_at": path.stat().st_mtime if path.exists() else None,
        })
    return files, total_size


def _parse_number(value):
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    match = _NUMBER_PATTERN.search(text)
    if not match:
        return None
    try:
        return float(match.group(0).replace(",", "."))
    except ValueError:
        return None


def _atlas_config(config: dict):
    sensors = config.get("sensors") or {}
    atlas = sensors.get("atlas") or config.get("atlas") or {}
    return atlas if isinstance(atlas, dict) else {}


def _scale_configs(config: dict):
    sensors = config.get("sensors") or {}
    scales = sensors.get("scales") or []
    return scales if isinstance(scales, list) else []


def _series_unit_for_sensor(config: dict, sensor_name: str):
    atlas = _atlas_config(config)
    for sensor in atlas.get("sensors") or []:
        if str(sensor.get("name", "")).strip() == str(sensor_name).strip():
            unit = sensor.get("unit")
            if unit is not None:
                return str(unit)
            sensor_type = str(sensor.get("type", ""))
            return {
                "pH": "",
                "ORP": "mV",
                "EC": "µS/cm",
                "RTD": "°C",
            }.get(sensor_type, "")
    return {
        "pH": "",
        "ORP": "mV",
        "EC": "µS/cm",
        "RTD": "°C",
    }.get(str(sensor_name), "")


def _scale_unit_for_file(config: dict, filename: str):
    stem = Path(filename).stem
    for scale in _scale_configs(config):
        if stem in {str(scale.get("id", "")), str(scale.get("name", ""))}:
            return str(scale.get("unit") or "")
    return ""


def _sensor_file_metadata(path: Path, directory: Path, config: dict):
    rel = _relative(directory, path)
    stat = path.stat()
    cache_key = (str(path.resolve()), stat.st_size, stat.st_mtime_ns)
    cached = _SENSOR_META_CACHE.get(cache_key)
    if cached is not None:
        return cached

    # Drop stale entries for the same file when it changes.
    for key in list(_SENSOR_META_CACHE):
        if key[0] == cache_key[0] and key != cache_key:
            _SENSOR_META_CACHE.pop(key, None)

    result = {
        "id": rel,
        "path": rel,
        "name": path.stem,
        "size_bytes": path.stat().st_size,
        "columns": [],
        "series": [],
        "sample_count": 0,
        "start_elapsed_s": None,
        "end_elapsed_s": None,
    }

    series_stats = {}
    try:
        with path.open("r", encoding="utf-8", errors="replace", newline="") as file:
            reader = csv.DictReader(file, delimiter="\t")
            result["columns"] = reader.fieldnames or []
            atlas_style = "sensor" in result["columns"]

            for row in reader:
                result["sample_count"] += 1
                elapsed = _parse_number(row.get("run_elapsed_s"))
                if elapsed is not None:
                    if result["start_elapsed_s"] is None:
                        result["start_elapsed_s"] = elapsed
                    result["end_elapsed_s"] = elapsed

                key = str(row.get("sensor") or "value") if atlas_style else "value"
                value = _parse_number(row.get("value"))
                stats = series_stats.setdefault(key, {
                    "count": 0,
                    "numeric_count": 0,
                    "min": None,
                    "max": None,
                    "sum": 0.0,
                    "first_elapsed_s": None,
                    "last_elapsed_s": None,
                })
                stats["count"] += 1
                if elapsed is not None:
                    if stats["first_elapsed_s"] is None:
                        stats["first_elapsed_s"] = elapsed
                    stats["last_elapsed_s"] = elapsed
                if value is not None and math.isfinite(value):
                    stats["numeric_count"] += 1
                    stats["sum"] += value
                    stats["min"] = value if stats["min"] is None else min(stats["min"], value)
                    stats["max"] = value if stats["max"] is None else max(stats["max"], value)
    except OSError as error:
        result["error"] = str(error)
        return result

    atlas_style = "sensor" in result["columns"]
    for key, stats in sorted(series_stats.items()):
        numeric_count = stats["numeric_count"]
        unit = (
            _series_unit_for_sensor(config, key)
            if atlas_style
            else _scale_unit_for_file(config, path.name)
        )
        result["series"].append({
            "id": key,
            "name": path.stem if key == "value" else key,
            "unit": unit,
            "count": stats["count"],
            "numeric_count": numeric_count,
            "min": stats["min"],
            "max": stats["max"],
            "mean": (stats["sum"] / numeric_count) if numeric_count else None,
            "start_elapsed_s": stats["first_elapsed_s"],
            "end_elapsed_s": stats["last_elapsed_s"],
        })

    _SENSOR_META_CACHE[cache_key] = result
    return result


def _sensor_metadata(directory: Path, config: dict):
    sensors_dir = directory / "sensors"
    if not sensors_dir.is_dir():
        return []
    result = []
    for path in sorted(sensors_dir.glob("*.tsv")):
        if path.is_file():
            result.append(_sensor_file_metadata(path, directory, config))
    return result


def _measurement_summary(records):
    variables = {}
    for record in records:
        variable_id = str(record.get("variable_id") or record.get("variable_name") or "measurement")
        item = variables.setdefault(variable_id, {
            "id": variable_id,
            "name": record.get("variable_name") or variable_id,
            "unit": record.get("unit"),
            "count": 0,
            "latest": None,
            "min": None,
            "max": None,
        })
        item["count"] += 1
        item["latest"] = record
        value = _parse_number(record.get("value"))
        if value is not None and math.isfinite(value):
            item["min"] = value if item["min"] is None else min(item["min"], value)
            item["max"] = value if item["max"] is None else max(item["max"], value)
        if record.get("unit") not in (None, ""):
            item["unit"] = record.get("unit")
    return list(variables.values())


def _video_manifest(directory: Path, events: list | None = None):
    videos = []
    events = events or []
    for path in _iter_files(directory):
        if path.suffix.lower() not in _VIDEO_SUFFIXES:
            continue
        rel = _relative(directory, path)
        sidecar = path.with_suffix(path.suffix + ".json")
        metadata = _read_json(sidecar, {}) if sidecar.is_file() else {}
        camera_name = metadata.get("camera_name") or path.parent.name

        start_elapsed_s = None
        end_elapsed_s = None
        for event in events:
            event_name = str(event.get("event") or "")
            data = event.get("data") or {}
            event_path = str(data.get("path") or "")
            same_video = bool(event_path) and (
                event_path.endswith(rel)
                or Path(event_path).name == path.name
            )
            if not same_video:
                continue
            if event_name == "CAMERA_RECORDING_STARTED":
                start_elapsed_s = _parse_number(event.get("run_elapsed_s"))
            elif event_name == "CAMERA_RECORDING_STOPPED":
                end_elapsed_s = _parse_number(event.get("run_elapsed_s"))

        videos.append({
            "id": rel,
            "path": rel,
            "name": path.name,
            "camera_id": metadata.get("camera_id"),
            "camera_name": camera_name,
            "segment": metadata.get("segment"),
            "size_bytes": path.stat().st_size,
            "start_timestamp": metadata.get("start_timestamp"),
            "end_timestamp": metadata.get("end_timestamp"),
            "start_stage_id": metadata.get("start_stage_id"),
            "end_stage_id": metadata.get("end_stage_id"),
            "stage_attempt": metadata.get("stage_attempt"),
            "start_monotonic_ns": metadata.get("start_monotonic_ns"),
            "end_monotonic_ns": metadata.get("end_monotonic_ns"),
            "start_elapsed_s": start_elapsed_s,
            "end_elapsed_s": end_elapsed_s,
            "metadata": metadata,
            "stream_url": f"/api/results/{quote(directory.name, safe='')}/file?path={quote(rel, safe='')}",
        })
    return videos


def _timeline_payload(experiment: dict, runtime: dict, events: list, measurements: list, videos: list):
    duration = _parse_number((runtime or {}).get("run_elapsed_s")) or 0.0
    items = []

    for event in events:
        elapsed = _parse_number(event.get("run_elapsed_s"))
        if elapsed is not None:
            duration = max(duration, elapsed)
        items.append({
            "kind": "event",
            "elapsed_s": elapsed,
            "event": event.get("event"),
            "timestamp": event.get("timestamp"),
            "stage_id": event.get("stage_id"),
            "stage_name": event.get("stage_name"),
            "stage_type": event.get("stage_type"),
            "state": event.get("state"),
            "data": event.get("data") or {},
        })

    for record in measurements:
        elapsed = _parse_number(record.get("run_elapsed_s"))
        if elapsed is not None:
            duration = max(duration, elapsed)
        items.append({
            "kind": "measurement",
            "elapsed_s": elapsed,
            "timestamp": record.get("captured_at") or record.get("timestamp"),
            "stage_id": record.get("stage_id"),
            "stage_name": record.get("stage_name"),
            "variable_id": record.get("variable_id"),
            "variable_name": record.get("variable_name"),
            "value": record.get("value"),
            "unit": record.get("unit"),
        })

    stages = []
    active = {}
    for event in events:
        event_name = str(event.get("event") or "")
        elapsed = _parse_number(event.get("run_elapsed_s"))
        stage_id = event.get("stage_id")
        data = event.get("data") or {}
        if event_name in {"STAGE_STARTED", "STAGE_RESTARTED"}:
            sid = data.get("stage_id", stage_id)
            active[(str(sid), event.get("stage_attempt"))] = {
                "stage_id": sid,
                "stage_name": event.get("stage_name") or data.get("stage_name"),
                "stage_type": event.get("stage_type") or data.get("stage_type"),
                "stage_attempt": event.get("stage_attempt"),
                "start_s": elapsed,
                "end_s": None,
            }
        elif event_name in {"STAGE_COMPLETED", "STAGE_FINISHED_EARLY", "STAGE_SKIPPED"}:
            sid = data.get("stage_id", stage_id)
            candidates = [key for key in active if key[0] == str(sid)]
            if candidates:
                key = candidates[-1]
                stage = active.pop(key)
                stage["end_s"] = elapsed
                stage["outcome"] = event_name
                stages.append(stage)

    for stage in active.values():
        stage["end_s"] = duration or stage.get("start_s")
        stage["outcome"] = "OPEN"
        stages.append(stage)

    if not stages:
        cursor = 0.0
        for index, stage in enumerate(experiment.get("stages") or []):
            stage_duration = _parse_number(stage.get("duration")) or 0.0
            stages.append({
                "stage_id": stage.get("id", index + 1),
                "stage_name": stage.get("name") or f"Stage {index + 1}",
                "stage_type": stage.get("type"),
                "stage_attempt": 1,
                "start_s": cursor,
                "end_s": cursor + stage_duration,
                "outcome": "PLANNED",
            })
            cursor += stage_duration
        duration = max(duration, cursor)

    return {
        "duration_s": duration,
        "stages": sorted(stages, key=lambda item: (item.get("start_s") or 0.0)),
        "items": sorted(
            items,
            key=lambda item: (
                item.get("elapsed_s") is None,
                item.get("elapsed_s") or 0.0,
            ),
        ),
        "videos": videos,
    }


def _overview(directory: Path):
    experiment = read_local_experiment(directory)
    _, runtime = read_runtime_state(directory)
    runtime = runtime or {}
    config = _read_json(directory / "config_snapshot.json", {}) or {}
    server = config.get("server")
    if isinstance(server, dict):
        server.pop("token", None)

    events = _read_jsonl(directory / "events.jsonl")
    measurements = _read_jsonl(directory / "measurements.jsonl")
    sensors = _sensor_metadata(directory, config)
    videos = _video_manifest(directory, events)
    files, total_size = _file_manifest(directory)
    timeline = _timeline_payload(experiment, runtime, events, measurements, videos)

    return {
        "storage_id": directory.name,
        "experiment": experiment,
        "runtime": runtime,
        "config": config,
        "summary": {
            "status": runtime.get("state") or experiment.get("state") or "Unknown",
            "duration_s": timeline["duration_s"],
            "sensor_files": len(sensors),
            "sensor_series": sum(len(item.get("series") or []) for item in sensors),
            "sensor_samples": sum(int(item.get("sample_count") or 0) for item in sensors),
            "measurements": len(measurements),
            "measurement_variables": len(_measurement_summary(measurements)),
            "events": len(events),
            "videos": len(videos),
            "files": len(files),
            "size_bytes": total_size,
        },
        "sensors": sensors,
        "measurement_variables": _measurement_summary(measurements),
        "videos": videos,
        "timeline": timeline,
        "files": files,
    }


@router.get("/{storage_id}")
def get_results_overview(storage_id: str):
    directory = get_local_directory(storage_id)
    try:
        return _overview(directory)
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except HTTPException:
        raise
    except Exception as error:
        raise HTTPException(status_code=500, detail=f"Could not read experiment results: {error}") from error


@router.get("/{storage_id}/series")
def get_sensor_series(
    storage_id: str,
    path: str = Query(...),
    series: str = Query("value"),
    start: float | None = Query(None),
    end: float | None = Query(None),
    max_points: int = Query(1600, ge=100, le=8000),
):
    directory = get_local_directory(storage_id)
    file_path = _safe_relative_path(directory, path)
    if file_path.suffix.lower() != ".tsv" or file_path.parent.name != "sensors":
        raise HTTPException(status_code=400, detail="Only sensor TSV files can be plotted.")

    # One streaming pass. When the bounded buffer grows too large, thin it
    # and increase the sampling stride. This keeps memory independent of the
    # TSV size while preserving the full time range.
    matching_count = 0
    stride = 1
    points = []
    last_point = None

    with file_path.open("r", encoding="utf-8", errors="replace", newline="") as file:
        reader = csv.DictReader(file, delimiter="\t")
        atlas_style = "sensor" in (reader.fieldnames or [])
        for row in reader:
            if atlas_style and str(row.get("sensor")) != str(series):
                continue
            elapsed = _parse_number(row.get("run_elapsed_s"))
            value = _parse_number(row.get("value"))
            if elapsed is None or value is None:
                continue
            if start is not None and elapsed < start:
                continue
            if end is not None and elapsed > end:
                continue

            point = {
                "x": elapsed,
                "y": value,
                "stage_id": row.get("stage_id") or None,
                "stage_state": row.get("stage_state") or None,
                "timestamp_ns": row.get("timestamp_ns") or None,
            }
            if matching_count % stride == 0:
                points.append(point)
            last_point = point
            matching_count += 1

            if len(points) > max_points * 2:
                points = points[::2]
                stride *= 2

    if len(points) > max_points:
        step = max(1, math.ceil(len(points) / max_points))
        points = points[::step]

    if last_point is not None and (not points or points[-1]["x"] != last_point["x"]):
        if len(points) >= max_points:
            points[-1] = last_point
        else:
            points.append(last_point)

    return {
        "path": path,
        "series": series,
        "count": matching_count,
        "returned": len(points),
        "start": start,
        "end": end,
        "points": points,
    }


@router.get("/{storage_id}/table")
def get_table_rows(
    storage_id: str,
    path: str = Query(...),
    series: str | None = Query(None),
    offset: int = Query(0, ge=0),
    limit: int = Query(200, ge=1, le=1000),
):
    directory = get_local_directory(storage_id)
    file_path = _safe_relative_path(directory, path)
    if file_path.suffix.lower() not in {".tsv", ".csv"}:
        raise HTTPException(status_code=400, detail="Only TSV/CSV files can be opened as a table.")

    delimiter = "\t" if file_path.suffix.lower() == ".tsv" else ","
    rows = []
    columns = []
    known_total = None

    # Sensor metadata already contains exact row counts and is cached by
    # size/mtime. Use it so paginating a huge TSV does not rescan to EOF.
    if file_path.suffix.lower() == ".tsv" and file_path.parent.name == "sensors":
        config = _read_json(directory / "config_snapshot.json", {}) or {}
        metadata = _sensor_file_metadata(file_path, directory, config)
        if series is not None and "sensor" in (metadata.get("columns") or []):
            match = next((item for item in metadata.get("series") or [] if str(item.get("id")) == str(series)), None)
            known_total = int((match or {}).get("count") or 0)
        else:
            known_total = int(metadata.get("sample_count") or 0)

    matched = 0
    with file_path.open("r", encoding="utf-8", errors="replace", newline="") as file:
        reader = csv.DictReader(file, delimiter=delimiter)
        columns = reader.fieldnames or []
        for row in reader:
            if series is not None and "sensor" in columns and str(row.get("sensor")) != str(series):
                continue
            if matched >= offset and len(rows) < limit:
                rows.append(row)
            matched += 1
            if known_total is not None and len(rows) >= limit:
                break

    total = known_total if known_total is not None else matched
    if known_total is None and len(rows) >= limit:
        # For non-sensor files we still need the exact total for pagination.
        with file_path.open("r", encoding="utf-8", errors="replace", newline="") as file:
            reader = csv.DictReader(file, delimiter=delimiter)
            total = 0
            for row in reader:
                if series is not None and "sensor" in columns and str(row.get("sensor")) != str(series):
                    continue
                total += 1

    return {
        "path": path,
        "series": series,
        "columns": columns,
        "offset": offset,
        "limit": limit,
        "total": total,
        "rows": rows,
    }


@router.get("/{storage_id}/measurements")
def get_measurements(storage_id: str):
    directory = get_local_directory(storage_id)
    records = _read_jsonl(directory / "measurements.jsonl")
    return {
        "variables": _measurement_summary(records),
        "observations": records,
    }


@router.get("/{storage_id}/events")
def get_events(
    storage_id: str,
    offset: int = Query(0, ge=0),
    limit: int = Query(500, ge=1, le=5000),
):
    directory = get_local_directory(storage_id)
    path = directory / "events.jsonl"
    all_events = _read_jsonl(path)
    return {
        "total": len(all_events),
        "offset": offset,
        "limit": limit,
        "events": all_events[offset:offset + limit],
    }


@router.get("/{storage_id}/system")
def get_system_metrics(
    storage_id: str,
    max_points: int = Query(1200, ge=100, le=5000),
):
    directory = get_local_directory(storage_id)
    path = directory / "system_metrics.tsv"
    if not path.is_file():
        return {"columns": [], "rows": []}

    rows = []
    with path.open("r", encoding="utf-8", errors="replace", newline="") as file:
        reader = csv.DictReader(file, delimiter="\t")
        columns = reader.fieldnames or []
        for row in reader:
            parsed = {}
            for key, value in row.items():
                number = _parse_number(value)
                parsed[key] = number if number is not None else value
            rows.append(parsed)

    if len(rows) > max_points:
        stride = math.ceil(len(rows) / max_points)
        sampled = rows[::stride]
        if sampled[-1] is not rows[-1]:
            sampled.append(rows[-1])
        rows = sampled

    return {"columns": columns, "rows": rows}


@router.get("/{storage_id}/file")
def get_result_file(
    storage_id: str,
    path: str = Query(...),
    download: bool = Query(False),
):
    directory = get_local_directory(storage_id)
    file_path = _safe_relative_path(directory, path)
    media_type, _ = mimetypes.guess_type(file_path.name)
    disposition = "attachment" if download else "inline"
    return FileResponse(
        file_path,
        media_type=media_type or "application/octet-stream",
        filename=file_path.name if download else None,
        content_disposition_type=disposition,
    )


@router.get("/{storage_id}/preview")
def preview_result_file(
    storage_id: str,
    path: str = Query(...),
):
    directory = get_local_directory(storage_id)
    file_path = _safe_relative_path(directory, path)
    if file_path.suffix.lower() not in _TEXT_SUFFIXES:
        raise HTTPException(status_code=400, detail="This file type does not have a text preview.")

    try:
        size = file_path.stat().st_size
        with file_path.open("rb") as file:
            raw = file.read(_MAX_TEXT_PREVIEW_BYTES)
        text = raw.decode("utf-8", errors="replace")
    except OSError as error:
        raise HTTPException(status_code=500, detail=str(error)) from error

    truncated = size > len(raw)
    if file_path.suffix.lower() == ".json" and not truncated:
        try:
            payload = json.loads(text)
            if isinstance(payload, dict) and isinstance(payload.get("server"), dict):
                payload["server"].pop("token", None)
            return JSONResponse({
                "path": path,
                "kind": "json",
                "truncated": False,
                "content": payload,
            })
        except json.JSONDecodeError:
            pass

    return {
        "path": path,
        "kind": _file_kind(file_path),
        "truncated": truncated,
        "content": text,
    }
