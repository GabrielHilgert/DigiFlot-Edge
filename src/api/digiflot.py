import json

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse


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
