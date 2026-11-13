"""Local, optional Cell Vision APIs; does not alter experiment execution routes."""
from fastapi import APIRouter, HTTPException, Request

router = APIRouter(prefix="/api/vision", tags=["Cell Vision"])


def service(request):
    return request.app.state.vision


def _invoke(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc).strip("'")) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/status")
def status(request: Request):
    return _invoke(service(request).status)


@router.get("/settings")
def settings(request: Request):
    return service(request).registry.settings()


@router.put("/settings")
def save_settings(request: Request, payload: dict):
    return _invoke(service(request).save_settings, payload)


@router.get("/virtual-sensors/froth-interface/profile")
def froth_interface_profile(request: Request):
    return _invoke(service(request).virtual_profile)


@router.put("/virtual-sensors/froth-interface/profile")
def save_froth_interface_profile(request: Request, payload: dict):
    return _invoke(service(request).save_virtual_profile, payload)


@router.post("/virtual-sensors/froth-interface/benchmark")
def benchmark_froth_interface(request: Request, payload: dict | None = None):
    return _invoke(service(request).benchmark_virtual_sensor, (payload or {}).get("samples", 20))


@router.post("/virtual-sensors/froth-interface/monitor")
def froth_interface_monitor(request: Request, payload: dict | None = None):
    options = payload or {}
    return _invoke(service(request).monitor_preview, int(options.get("width") or 320),
                   int(options.get("last_revision") or 0))


@router.post("/virtual-sensors/froth-interface/diagnostics")
def froth_interface_diagnostics(request: Request, payload: dict | None = None):
    options = payload or {}
    return _invoke(service(request).diagnostic_preview, bool(options.get("enabled", True)),
                   int(options.get("last_revision") or 0), request.headers.get("X-DigiFlot-Tab-Id"))


@router.get("/virtual-sensors/froth-interface/detection-roi-preview")
def froth_detection_roi_preview(request: Request):
    return _invoke(service(request).virtual_detection_roi_preview, request.headers.get("X-DigiFlot-Tab-Id"))


@router.get("/cells")
def list_cells(request: Request):
    return service(request).registry.list_cells()


@router.post("/cells")
def save_cell(request: Request, payload: dict):
    if request.app.state.digiflot.execution_locked:
        raise HTTPException(status_code=409, detail="Cell definitions cannot change during an experiment")
    return _invoke(service(request).registry.save_cell, payload)


@router.get("/cells/{cell_id}")
def get_cell(cell_id: str, request: Request):
    return _invoke(service(request).registry.get_cell, cell_id)


@router.put("/cells/{cell_id}")
def update_cell(cell_id: str, request: Request, payload: dict):
    if request.app.state.digiflot.execution_locked:
        raise HTTPException(status_code=409, detail="Cell definitions cannot change during an experiment")
    return _invoke(service(request).registry.save_cell, {**payload, "id": cell_id})


@router.get("/cells/{cell_id}/reference-points")
def list_reference_points(cell_id: str, request: Request):
    return _invoke(service(request).registry.reference_points, cell_id)


@router.put("/cells/{cell_id}/reference-points")
def save_reference_points(cell_id: str, request: Request, payload: dict):
    return _invoke(service(request).save_reference_points, cell_id, payload)


@router.put("/cells/{cell_id}/vertical-reference")
def save_cell_vertical_reference(cell_id: str, request: Request, payload: dict):
    return _invoke(service(request).save_cell_vertical_reference, cell_id, payload)


@router.get("/cameras/{camera_id}/profile")
def camera_profile(camera_id: int, request: Request):
    return _invoke(service(request).camera_profile, camera_id)


@router.put("/cameras/{camera_id}/profile")
def update_camera_profile(camera_id: int, request: Request, payload: dict):
    return _invoke(service(request).save_camera_profile, camera_id, payload)


@router.get("/cameras/{camera_id}/snapshot")
def camera_snapshot(camera_id: int, request: Request, cell_id: str | None = None):
    return _invoke(service(request).snapshot, camera_id, cell_id)


@router.get("/associations/{camera_id}/{cell_id}")
def association(camera_id: int, cell_id: str, request: Request):
    return _invoke(service(request).registry.association, camera_id, cell_id)


@router.put("/associations/{camera_id}/{cell_id}/roi")
def save_analysis_roi(camera_id: int, cell_id: str, request: Request, payload: dict):
    return _invoke(service(request).save_analysis_roi, camera_id, cell_id, payload)


@router.post("/associations/{camera_id}/{cell_id}/detect")
def detect(camera_id: int, cell_id: str, request: Request):
    return _invoke(service(request).detect, camera_id, cell_id)


@router.post("/associations/{camera_id}/{cell_id}/confirm")
def confirm(camera_id: int, cell_id: str, request: Request, payload: dict):
    return _invoke(service(request).confirm, camera_id, cell_id, str(payload.get("token", "")))


@router.get("/associations/{camera_id}/{cell_id}/rectified")
def rectified(camera_id: int, cell_id: str, request: Request):
    return _invoke(service(request).rectified_snapshot, camera_id, cell_id)
