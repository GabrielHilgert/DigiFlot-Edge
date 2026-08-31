from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from api.cameras import router as camera_router
from api.digiflot import router as digiflot_router
from api.local import router as local_router
from api.sensors import router as sensor_router
from api.server import router as server_router
from lib.digiflot import DigiFlot, load_config
from lib.server import Server


BASE_DIR = Path(__file__).resolve().parent
UI_DIR = BASE_DIR / "ui"
LOCAL_STORAGE_DIR = BASE_DIR.parent / "local_storage"

templates = Jinja2Templates(directory=UI_DIR / "html")


@asynccontextmanager
async def lifespan(app: FastAPI):
    config = load_config()

    digiflot = DigiFlot(
        config,
        local_storage_dir=LOCAL_STORAGE_DIR,
    )
    digiflot.start()

    app.state.digiflot = digiflot

    # Compatibility aliases for existing sensor API routes.
    app.state.scales = digiflot.scales
    app.state.atlas = digiflot.atlas

    app.state.server = Server(
        ip=config["server"]["ip"],
        id=config["server"]["id"],
        name=config["server"]["name"],
        token=config["server"]["token"],
    )
    app.state.server.login()

    try:
        yield
    finally:
        digiflot.close()


app = FastAPI(title="DigiFlot", lifespan=lifespan)

app.mount(
    "/static",
    StaticFiles(directory=UI_DIR),
    name="static",
)

app.include_router(server_router)
app.include_router(local_router)
app.include_router(camera_router)
app.include_router(sensor_router)
app.include_router(digiflot_router)


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="experiments.html",
    )


@app.get("/run", response_class=HTMLResponse)
def run(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="run.html",
        context={
            "digiflot_state": request.app.state.digiflot.state,
        },
    )


@app.get("/cameras", response_class=HTMLResponse)
def cameras(request: Request):
    digiflot = request.app.state.digiflot
    return templates.TemplateResponse(
        request=request,
        name="config_camera.html",
        context={
            "cameras": digiflot.camera_summaries(),
            "digiflot_state": digiflot.state,
            "calibration_mode": digiflot.state == digiflot.CAMERA_CALIBRATION,
        },
    )


@app.get("/sensors", response_class=HTMLResponse)
def sensors_view(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="sensors.html",
        context={},
    )


@app.get("/performance", response_class=HTMLResponse)
def performance(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="performance.html",
        context={},
    )


@app.get("/health")
def health(request: Request):
    digiflot = request.app.state.digiflot
    return {
        "status": "ok",
        "digiflot": digiflot.status,
    }
