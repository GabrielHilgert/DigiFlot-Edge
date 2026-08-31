from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field


router = APIRouter(
    prefix="/api/cameras",
    tags=["Cameras"],
)


class RecordingConfig(BaseModel):
    output_type: Literal["mjpeg", "mp4"]


class PreviewConfig(BaseModel):
    size: tuple[int, int]
    frame_rate: float = Field(gt=0)
    quality: int = Field(ge=1, le=100)
    encoder_threads: int = Field(default=1, ge=1, le=4)


class ExposureConfig(BaseModel):
    exposure_time_us: int | None = None
    analogue_gain: float | None = None
    calibration_frames: int = Field(ge=1, le=300)
    settle_frames: int = Field(ge=0, le=100)


class CameraConfigUpdate(BaseModel):
    name: str
    frame_size: tuple[int, int]
    frame_rate: float = Field(gt=0)
    format: Literal["YUV420", "RGB888"]
    crop_region: tuple[int, int, int, int] | None = None
    recording: RecordingConfig
    preview: PreviewConfig
    exposure: ExposureConfig
    controls: dict[str, Any]


class ExposureUpdate(BaseModel):
    exposure_time_us: int = Field(gt=0)
    analogue_gain: float = Field(gt=0)


class ControlsUpdate(BaseModel):
    controls: dict[str, Any]


def get_digiflot(request: Request):
    return request.app.state.digiflot


def api_error(error: Exception):
    if isinstance(error, KeyError):
        return HTTPException(
            status_code=404,
            detail=str(error).strip("'"),
        )

    if isinstance(error, ValueError):
        return HTTPException(
            status_code=400,
            detail=str(error),
        )

    if isinstance(error, RuntimeError):
        return HTTPException(
            status_code=409,
            detail=str(error),
        )

    return HTTPException(
        status_code=500,
        detail=str(error),
    )


@router.get("")
def list_cameras(request: Request):
    digiflot = get_digiflot(request)

    return {
        "state": digiflot.state,
        "preview_camera_id": (
            digiflot.preview_camera_id
        ),
        "cameras": digiflot.camera_summaries(),
    }


@router.get("/{camera_id}")
def get_camera(
    camera_id: int,
    request: Request,
):
    digiflot = get_digiflot(request)

    try:
        return digiflot.get_camera_payload(
            camera_id
        )
    except Exception as error:
        raise api_error(error) from error


@router.put("/{camera_id}")
@router.patch("/{camera_id}")
def update_camera(
    camera_id: int,
    payload: CameraConfigUpdate,
    request: Request,
):
    digiflot = get_digiflot(request)

    try:
        return digiflot.update_camera_config(
            camera_id,
            payload.model_dump(),
        )
    except Exception as error:
        raise api_error(error) from error


@router.post("/{camera_id}/preview/start")
def start_preview(
    camera_id: int,
    request: Request,
):
    digiflot = get_digiflot(request)

    try:
        status = digiflot.start_preview(
            camera_id
        )

        return {
            "camera_id": camera_id,
            "state": status["state"],
            "preview_camera_id": (
                status["preview_camera_id"]
            ),
        }
    except Exception as error:
        raise api_error(error) from error


@router.post("/preview/stop")
@router.delete("/preview")
def stop_preview(request: Request):
    digiflot = get_digiflot(request)

    try:
        return digiflot.stop_preview()
    except Exception as error:
        raise api_error(error) from error


def mjpeg_stream(camera):
    output = camera.preview_output

    if output is None:
        return

    sequence = -1

    while (
        camera.state == camera.PREVIEW
        and camera.preview_output is output
    ):
        with output.condition:
            output.condition.wait_for(
                lambda: (
                    output.sequence != sequence
                    or output.closed
                    or camera.state != camera.PREVIEW
                ),
                timeout=1.0,
            )

            if output.closed or camera.state != camera.PREVIEW:
                break

            if output.frame is None or output.sequence == sequence:
                continue

            frame = output.frame
            sequence = output.sequence

        yield (
            b"--frame\r\n"
            b"Content-Type: image/jpeg\r\n"
            + f"Content-Length: {len(frame)}\r\n".encode()
            + b"\r\n"
            + frame
            + b"\r\n"
        )


@router.get("/{camera_id}/stream")
def camera_stream(
    camera_id: int,
    request: Request,
):
    digiflot = get_digiflot(request)

    try:
        camera = digiflot.get_camera(
            camera_id
        )

        if (
            digiflot.preview_camera_id != camera.id
            or camera.state != camera.PREVIEW
            or camera.preview_output is None
        ):
            raise RuntimeError(
                "Start preview for this camera before opening the stream."
            )

        return StreamingResponse(
            mjpeg_stream(camera),
            media_type=(
                "multipart/x-mixed-replace; "
                "boundary=frame"
            ),
            headers={
                "Cache-Control": "no-cache, private",
                "Pragma": "no-cache",
            },
        )

    except Exception as error:
        raise api_error(error) from error


@router.post("/{camera_id}/exposure/calibrate")
def calibrate_exposure(
    camera_id: int,
    request: Request,
):
    digiflot = get_digiflot(request)

    try:
        exposure = (
            digiflot.calibrate_exposure(
                camera_id
            )
        )

        return {
            "camera_id": camera_id,
            **exposure,
        }
    except Exception as error:
        raise api_error(error) from error


@router.patch("/{camera_id}/exposure")
def set_exposure(
    camera_id: int,
    payload: ExposureUpdate,
    request: Request,
):
    digiflot = get_digiflot(request)

    try:
        exposure = digiflot.set_exposure(
            camera_id,
            payload.exposure_time_us,
            payload.analogue_gain,
        )

        return {
            "camera_id": camera_id,
            **exposure,
        }
    except Exception as error:
        raise api_error(error) from error


@router.get("/{camera_id}/controls")
def get_controls(
    camera_id: int,
    request: Request,
):
    digiflot = get_digiflot(request)

    try:
        camera = digiflot.get_camera(
            camera_id
        )

        return {
            "values": camera.controls,
            "capabilities": (
                camera.control_capabilities()
            ),
        }
    except Exception as error:
        raise api_error(error) from error


@router.patch("/{camera_id}/controls")
def set_controls(
    camera_id: int,
    payload: ControlsUpdate,
    request: Request,
):
    digiflot = get_digiflot(request)

    try:
        values = (
            digiflot.set_camera_controls(
                camera_id,
                payload.controls,
            )
        )

        return {
            "camera_id": camera_id,
            "controls": values,
        }
    except Exception as error:
        raise api_error(error) from error
