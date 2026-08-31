import json

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse


router = APIRouter(
    prefix="/api/sensors",
    tags=["Sensors"],
)


def get_scales(request: Request):
    return getattr(request.app.state, "scales", {})


def get_atlas(request: Request):
    return getattr(request.app.state, "atlas", None)


def scale_snapshot(scale):
    snapshot = scale.snapshot()
    snapshot.update({
        "source": "scale",
        "interface": "Serial",
        "device": snapshot.get("port") or "—",
        "connection": (
            f'{snapshot.get("baudrate")} baud'
            if snapshot.get("baudrate") is not None
            else "—"
        ),
        "decimals": 2,
    })
    return snapshot


def list_all_sensors(request: Request):
    snapshots = [
        scale_snapshot(scale)
        for scale in get_scales(request).values()
    ]

    atlas = get_atlas(request)
    if atlas is not None:
        snapshots.extend(atlas.sensor_snapshots())

    return snapshots


def get_sensor(request: Request, sensor_id: str):
    scale = get_scales(request).get(sensor_id)
    if scale is not None:
        return "scale", scale

    atlas = get_atlas(request)
    if atlas is not None:
        try:
            atlas.snapshot(sensor_id)
            return "atlas", atlas
        except KeyError:
            pass

    raise HTTPException(status_code=404, detail="Sensor not found.")


def sensor_snapshot(kind, source, sensor_id):
    if kind == "scale":
        return scale_snapshot(source)
    return source.snapshot(sensor_id)


def sensor_event_stream(kind, source, sensor_id):
    snapshot = sensor_snapshot(kind, source, sensor_id)
    last_revision = snapshot["revision"]

    yield "event: measurement\n" f"data: {json.dumps(snapshot)}\n\n"

    while True:
        if kind == "scale":
            snapshot = source.wait_for_update(last_revision, timeout=5.0)
            snapshot.update({
                "source": "scale",
                "interface": "Serial",
                "device": snapshot.get("port") or "—",
                "connection": (
                    f'{snapshot.get("baudrate")} baud'
                    if snapshot.get("baudrate") is not None
                    else "—"
                ),
                "decimals": 2,
            })
        else:
            snapshot = source.wait_for_update(sensor_id, last_revision, timeout=5.0)

        if snapshot["revision"] == last_revision:
            yield ": keepalive\n\n"
            continue

        last_revision = snapshot["revision"]
        yield "event: measurement\n" f"data: {json.dumps(snapshot)}\n\n"


@router.get("")
def sensors(request: Request):
    return {"sensors": list_all_sensors(request)}


@router.get("/{sensor_id}")
def sensor_status(sensor_id: str, request: Request):
    kind, source = get_sensor(request, sensor_id)
    return sensor_snapshot(kind, source, sensor_id)


@router.get("/{sensor_id}/stream")
def sensor_stream(sensor_id: str, request: Request):
    kind, source = get_sensor(request, sensor_id)

    return StreamingResponse(
        sensor_event_stream(kind, source, sensor_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# Backward-compatible scale routes.
@router.get("/scales/{sensor_id}", include_in_schema=False)
def old_scale_status(sensor_id: str, request: Request):
    scale = get_scales(request).get(sensor_id)
    if scale is None:
        raise HTTPException(status_code=404, detail="Scale not found.")
    return scale_snapshot(scale)


@router.get("/scales/{sensor_id}/stream", include_in_schema=False)
def old_scale_stream(sensor_id: str, request: Request):
    scale = get_scales(request).get(sensor_id)
    if scale is None:
        raise HTTPException(status_code=404, detail="Scale not found.")

    return StreamingResponse(
        sensor_event_stream("scale", scale, sensor_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
