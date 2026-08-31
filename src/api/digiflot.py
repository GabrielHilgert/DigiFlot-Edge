import json

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from lib.atlasScientific import AtlasScientific
from lib.camera import Camera
from lib.scale import Scale


router = APIRouter(
    prefix="/api/digiflot",
    tags=["DigiFlot"],
)


def get_digiflot(request: Request):
    return request.app.state.digiflot


def api_error(error: Exception):
    if isinstance(error, KeyError):
        return HTTPException(status_code=404, detail=str(error).strip("'"))
    if isinstance(error, ValueError):
        return HTTPException(status_code=400, detail=str(error))
    if isinstance(error, RuntimeError):
        return HTTPException(status_code=409, detail=str(error))
    return HTTPException(status_code=500, detail=str(error))


@router.post("/experiments/{storage_id}/start")
def select_experiment(storage_id: str, request: Request):
    digiflot = get_digiflot(request)
    try:
        status = digiflot.select_experiment(storage_id)
        return {
            "redirect_url": "/run",
            "status": status,
        }
    except Exception as error:
        raise api_error(error) from error


@router.get("/state")
def state(request: Request):
    return get_digiflot(request).status


def state_event_stream(digiflot):
    status = digiflot.status
    last_revision = status["revision"]
    yield "event: state\n" f"data: {json.dumps(status)}\n\n"

    while True:
        status = digiflot.wait_for_update(last_revision, timeout=0.5)
        last_revision = status["revision"]
        yield "event: state\n" f"data: {json.dumps(status)}\n\n"


@router.get("/stream")
def stream(request: Request):
    return StreamingResponse(
        state_event_stream(get_digiflot(request)),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/calibration/cameras/{camera_id}/start")
def start_camera_calibration(camera_id: int, request: Request):
    try:
        return get_digiflot(request).start_camera_calibration(camera_id)
    except Exception as error:
        raise api_error(error) from error


@router.post("/calibration/cameras/{camera_id}/confirm")
def confirm_camera_calibration(camera_id: int, request: Request):
    try:
        status = get_digiflot(request).confirm_camera_calibration(camera_id)
        return {
            "status": status,
            "redirect_url": "/run",
        }
    except Exception as error:
        raise api_error(error) from error


@router.post("/calibration/cameras/{camera_id}/skip")
def skip_camera_calibration(camera_id: int, request: Request, payload: dict | None = None):
    try:
        reason = (payload or {}).get("reason", "Operator skipped calibration")
        return get_digiflot(request).skip_camera_calibration(camera_id, reason=reason)
    except Exception as error:
        raise api_error(error) from error


@router.post("/calibration/sensors/{sensor_id}/start")
def start_sensor_calibration(sensor_id: str, request: Request, payload: dict | None = None):
    try:
        return get_digiflot(request).start_sensor_calibration(
            sensor_id,
            **(payload or {}),
        )
    except Exception as error:
        raise api_error(error) from error


@router.post("/calibration/sensors/{sensor_id}/confirm")
def confirm_sensor_calibration(sensor_id: str, request: Request):
    try:
        return get_digiflot(request).confirm_sensor_calibration(sensor_id)
    except Exception as error:
        raise api_error(error) from error




@router.post("/calibration/sensors/{sensor_id}/skip")
def skip_sensor_calibration(sensor_id: str, request: Request, payload: dict | None = None):
    try:
        reason = (payload or {}).get("reason", "Operator skipped calibration")
        return get_digiflot(request).skip_sensor_calibration(sensor_id, reason=reason)
    except Exception as error:
        raise api_error(error) from error


@router.post("/calibration/sensors/complete")
def complete_sensor_calibration(request: Request):
    try:
        return get_digiflot(request).complete_sensor_calibration()
    except Exception as error:
        raise api_error(error) from error


@router.post("/stages/start")
def start_stage(request: Request):
    try:
        return get_digiflot(request).start_next_stage()
    except Exception as error:
        raise api_error(error) from error


@router.post("/stages/finish-now")
def finish_stage_now(request: Request, payload: dict | None = None):
    try:
        reason = (payload or {}).get("reason", "Operator finished stage early")
        return get_digiflot(request).finish_stage_now(reason)
    except Exception as error:
        raise api_error(error) from error


@router.post("/stages/skip")
def skip_stage(request: Request, payload: dict | None = None):
    try:
        reason = (payload or {}).get("reason", "Operator skipped stage")
        return get_digiflot(request).skip_current_stage(reason)
    except Exception as error:
        raise api_error(error) from error


@router.post("/pause")
def pause(request: Request):
    try:
        return get_digiflot(request).pause()
    except Exception as error:
        raise api_error(error) from error


@router.post("/resume")
def resume(request: Request):
    try:
        return get_digiflot(request).resume()
    except Exception as error:
        raise api_error(error) from error


@router.post("/abort")
def abort(request: Request, payload: dict | None = None):
    try:
        reason = (payload or {}).get("reason", "Operator aborted experiment")
        return get_digiflot(request).abort_experiment(reason)
    except Exception as error:
        raise api_error(error) from error


@router.post("/recovery/retry-devices")
def retry_devices(request: Request):
    try:
        return get_digiflot(request).retry_devices()
    except Exception as error:
        raise api_error(error) from error


@router.post("/recovery/resume")
def resume_recovery(request: Request):
    try:
        return get_digiflot(request).resume_recovery()
    except Exception as error:
        raise api_error(error) from error


@router.post("/recovery/restart-stage")
def restart_stage(request: Request, payload: dict | None = None):
    try:
        reason = (payload or {}).get("reason", "Operator restarted stage")
        return get_digiflot(request).restart_current_stage(reason)
    except Exception as error:
        raise api_error(error) from error


@router.get("/settings")
def settings(request: Request):
    return get_digiflot(request).settings_payload()


@router.patch("/settings")
def update_settings(request: Request, payload: dict | None = None):
    try:
        return get_digiflot(request).update_system_settings(payload or {})
    except Exception as error:
        raise api_error(error) from error


@router.post("/devices/discover")
def discover_devices(request: Request):
    digiflot = get_digiflot(request)
    if digiflot.state != digiflot.IDLE:
        raise HTTPException(
            status_code=409,
            detail="Device discovery is only available while DigiFlot is idle.",
        )

    configured_cameras = digiflot.config.get("cameras", [])
    configured_camera_ids = {int(item["id"]) for item in configured_cameras}
    configured_camera_by_id = {int(item["id"]): item for item in configured_cameras}

    sensor_config = digiflot.config.get("sensors", {})
    configured_scales = sensor_config.get("scales", [])
    configured_ports = {str(item.get("port")) for item in configured_scales}
    configured_scale_by_port = {str(item.get("port")): item for item in configured_scales}

    atlas_config = sensor_config.get("atlas_scientific") or {}
    atlas_bus = int(atlas_config.get("bus", 1))
    configured_atlas = atlas_config.get("sensors", [])
    configured_atlas_by_address = {int(item["address"]): item for item in configured_atlas}

    result = {
        "cameras": [],
        "scales": [],
        "atlas": [],
        "atlas_bus": atlas_bus,
        "errors": [],
    }

    try:
        result["cameras"] = Camera.discover_available(configured_camera_ids)
        detected_ids = {int(item["id"]) for item in result["cameras"]}
        for item in result["cameras"]:
            camera_id = int(item["id"])
            item["config"] = configured_camera_by_id.get(camera_id)
            runtime_camera = digiflot.cameras.get(camera_id)
            if runtime_camera is not None:
                item["sensor_resolution"] = list(runtime_camera.picam2.sensor_resolution)
                item["max_fps"] = runtime_camera.max_sensor_fps()
        for camera_id, config in configured_camera_by_id.items():
            if camera_id not in detected_ids:
                result["cameras"].append({
                    "id": camera_id,
                    "model": None,
                    "configured": True,
                    "detected": False,
                    "sensor_resolution": None,
                    "max_fps": None,
                    "config": config,
                    "error": "Configured camera was not detected.",
                })
    except Exception as error:
        result["errors"].append({"source": "cameras", "error": str(error)})
        for camera_id, config in configured_camera_by_id.items():
            result["cameras"].append({
                "id": camera_id, "configured": True, "detected": False,
                "config": config, "error": str(error),
            })

    try:
        result["scales"] = Scale.discover_available(configured_ports)
        detected_ports = {str(item["port"]) for item in result["scales"]}
        for item in result["scales"]:
            item["config"] = configured_scale_by_port.get(str(item["port"]))
        for port, config in configured_scale_by_port.items():
            if port not in detected_ports:
                result["scales"].append({
                    "port": port,
                    "configured": True,
                    "detected": False,
                    "probable_scale": True,
                    "config": config,
                    "error": "Configured serial device was not detected.",
                })
    except Exception as error:
        result["errors"].append({"source": "scales", "error": str(error)})
        for port, config in configured_scale_by_port.items():
            result["scales"].append({
                "port": port, "configured": True, "detected": False,
                "probable_scale": True, "config": config, "error": str(error),
            })

    try:
        if digiflot.atlas is not None:
            atlas_found = digiflot.atlas.discover_available()
        else:
            atlas_found = AtlasScientific.discover_bus(bus=atlas_bus)
        result["atlas"] = atlas_found
        detected_addresses = {int(item["address"]) for item in atlas_found}
        for item in result["atlas"]:
            item["config"] = configured_atlas_by_address.get(int(item["address"]))
        for address, config in configured_atlas_by_address.items():
            if address not in detected_addresses:
                result["atlas"].append({
                    "address": address,
                    "type": config.get("type"),
                    "name": config.get("name"),
                    "configured": True,
                    "detected": False,
                    "config": config,
                    "error": "Configured Atlas sensor was not detected.",
                })
    except Exception as error:
        result["errors"].append({"source": "atlas", "error": str(error)})
        for address, config in configured_atlas_by_address.items():
            result["atlas"].append({
                "address": address, "type": config.get("type"),
                "name": config.get("name"), "configured": True,
                "detected": False, "config": config, "error": str(error),
            })

    return result


@router.post("/devices/save")
def save_devices(request: Request, payload: dict | None = None):
    try:
        return get_digiflot(request).save_discovered_devices(payload or {})
    except Exception as error:
        raise api_error(error) from error


@router.get("/performance")
def performance_status(request: Request):
    manager = get_digiflot(request).performance
    if manager is None:
        return {"state": "Unavailable", "profile": None, "system": None}
    return manager.status


@router.post("/performance/evaluate")
def performance_evaluate(request: Request, payload: dict | None = None):
    payload = payload or {}
    try:
        return get_digiflot(request).evaluate_camera_performance(
            camera_id=payload.get("camera_id"),
            frame_rate=payload.get("frame_rate"),
            camera_config=payload.get("camera_config"),
        )
    except Exception as error:
        raise api_error(error) from error


@router.post("/performance/benchmark/start")
def performance_benchmark_start(request: Request, payload: dict | None = None):
    digiflot = get_digiflot(request)
    if digiflot.performance is None:
        raise HTTPException(status_code=503, detail="Performance module is unavailable.")
    payload = payload or {}
    try:
        return digiflot.performance.start_benchmark(
            digiflot,
            rates=payload.get("rates"),
            duration_s=payload.get("duration_s"),
        )
    except Exception as error:
        raise api_error(error) from error


@router.post("/performance/benchmark/abort")
def performance_benchmark_abort(request: Request):
    manager = get_digiflot(request).performance
    if manager is None:
        raise HTTPException(status_code=503, detail="Performance module is unavailable.")
    return manager.abort_benchmark()


def performance_event_stream(manager):
    status = manager.status
    last_revision = status["revision"]
    yield "event: performance\n" f"data: {json.dumps(status)}\n\n"
    while True:
        status = manager.wait_for_update(last_revision, timeout=1.0)
        last_revision = status["revision"]
        yield "event: performance\n" f"data: {json.dumps(status)}\n\n"


@router.get("/performance/stream")
def performance_stream(request: Request):
    manager = get_digiflot(request).performance
    if manager is None:
        raise HTTPException(status_code=503, detail="Performance module is unavailable.")
    return StreamingResponse(
        performance_event_stream(manager),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/reset")
def reset(request: Request):
    try:
        return get_digiflot(request).reset()
    except Exception as error:
        raise api_error(error) from error
