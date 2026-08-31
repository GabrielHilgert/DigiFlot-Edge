import hashlib
import json
import shutil


from datetime import datetime
from pathlib import Path

from fastapi import APIRouter
from fastapi import HTTPException
from fastapi import Request
from pydantic import BaseModel


router = APIRouter(
    prefix="/api/local",
    tags=["local"],
)


BASE_DIR = Path(__file__).resolve().parent.parent

LOCAL_STORAGE_DIR = (
    BASE_DIR.parent
    / "local_storage"
)


class ExperimentStatePayload(
    BaseModel
):
    state: str


def get_experiment_hash(
    experiment: dict,
) -> str:

    experiment_id = (
        experiment.get("id")
    )

    name = str(
        experiment.get(
            "name",
            "",
        )
    ).strip()


    hash_source = (
        f"{experiment_id}:{name}"
    )


    return hashlib.sha256(
        hash_source.encode(
            "utf-8"
        )
    ).hexdigest()[:12]


def get_local_directory(
    storage_id: str,
) -> Path:

    if (
        not storage_id
        or
        Path(storage_id).name
        != storage_id
    ):
        raise HTTPException(
            status_code=404,
            detail=(
                "Local experiment "
                "not found."
            ),
        )


    directory = (
        LOCAL_STORAGE_DIR
        / storage_id
    )


    if not directory.is_dir():
        raise HTTPException(
            status_code=404,
            detail=(
                "Local experiment "
                "not found."
            ),
        )


    return directory


def write_local_experiment(
    directory: Path,
    experiment: dict,
):

    experiment_path = (
        directory
        / "experiment.json"
    )


    with experiment_path.open(
        "w",
        encoding="utf-8",
    ) as file:

        json.dump(
            experiment,
            file,
            indent=4,
            ensure_ascii=False,
        )


def read_local_experiment(
    directory: Path,
) -> dict:

    experiment_path = (
        directory
        / "experiment.json"
    )


    if not experiment_path.is_file():
        raise FileNotFoundError(
            "experiment.json not found."
        )


    with experiment_path.open(
        "r",
        encoding="utf-8",
    ) as file:

        experiment = (
            json.load(file)
        )


    changed = False


    if not experiment.get(
        "state"
    ):
        experiment["state"] = (
            "Created"
        )

        changed = True


    if not experiment.get(
        "local_created"
    ):
        experiment["local_created"] = (
            datetime.fromtimestamp(
                experiment_path
                .stat()
                .st_ctime
            )
            .replace(
                microsecond=0
            )
            .isoformat()
        )

        changed = True


    if changed:
        write_local_experiment(
            directory,
            experiment,
        )


    return experiment



def read_runtime_state(directory: Path):
    runtime_path = directory / "runtime.json"
    if not runtime_path.is_file():
        return None, None

    try:
        with runtime_path.open("r", encoding="utf-8") as file:
            runtime = json.load(file)
    except (OSError, json.JSONDecodeError):
        return None, None

    return runtime.get("state"), runtime

def local_experiment_response(
    directory: Path,
    experiment: dict,
) -> dict:

    storage_id = directory.name
    experiment_hash = storage_id.rsplit("_", 1)[-1]
    runtime_state, runtime = read_runtime_state(directory)
    effective_state = runtime_state or experiment.get("state", "Created")

    response_experiment = dict(experiment)
    response_experiment["state"] = effective_state

    return {
        "storage_id": storage_id,
        "hash": experiment_hash,
        "state": effective_state,
        "source": experiment.get("source"),
        "local_created": experiment.get("local_created"),
        "runtime": runtime,
        "experiment": response_experiment,
    }


@router.get(
    "/experiments"
)
def get_local_experiments():

    LOCAL_STORAGE_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )


    experiments = []


    directories = sorted(
        (
            directory

            for directory
            in LOCAL_STORAGE_DIR.iterdir()

            if directory.is_dir()
        ),

        key=lambda directory: (
            directory.name
        ),

        reverse=True,
    )


    for directory in directories:

        try:
            experiment = (
                read_local_experiment(
                    directory
                )
            )


            experiments.append(
                local_experiment_response(
                    directory,
                    experiment,
                )
            )


        except (
            FileNotFoundError,
            json.JSONDecodeError,
        ):
            continue


    return {
        "experiments": experiments,
    }


@router.get(
    "/experiments/{storage_id}"
)
def get_local_experiment(
    storage_id: str,
):

    try:
        directory = (
            get_local_directory(
                storage_id
            )
        )


        experiment = (
            read_local_experiment(
                directory
            )
        )


        return local_experiment_response(
            directory,
            experiment,
        )


    except HTTPException:
        raise


    except Exception as error:
        raise HTTPException(
            status_code=500,

            detail=(
                "Could not load local "
                f"experiment: {error}"
            ),

        ) from error


@router.post(
    "/experiments"
)
def save_local_experiment(
    experiment: dict,
):

    try:
        LOCAL_STORAGE_DIR.mkdir(
            parents=True,
            exist_ok=True,
        )


        name = str(
            experiment.get(
                "name",
                "",
            )
        ).strip()


        if not name:
            raise HTTPException(
                status_code=422,

                detail=(
                    "Experiment name "
                    "cannot be empty."
                ),
            )


        experiment["name"] = (
            name
        )


        if not experiment.get(
            "state"
        ):
            experiment["state"] = (
                "Created"
            )


        experiment_hash = (
            get_experiment_hash(
                experiment
            )
        )


        now = (
            datetime.now()
        )


        datetime_string = (
            now.strftime(
                "%Y%m%d-%H%M%S-%f"
            )
        )


        storage_id = (
            f"{datetime_string}_"
            f"{experiment_hash}"
        )


        experiment_dir = (
            LOCAL_STORAGE_DIR
            / storage_id
        )


        experiment_dir.mkdir(
            parents=True,
            exist_ok=False,
        )


        current_time = (
            now
            .replace(
                microsecond=0
            )
            .isoformat()
        )


        experiment[
            "local_created"
        ] = current_time


        experiment[
            "last_modified"
        ] = current_time


        write_local_experiment(
            experiment_dir,
            experiment,
        )


        return local_experiment_response(
            experiment_dir,
            experiment,
        )


    except HTTPException:
        raise


    except FileExistsError:
        raise HTTPException(
            status_code=409,

            detail=(
                "Local experiment "
                "already exists."
            ),
        )


    except Exception as error:
        raise HTTPException(
            status_code=500,

            detail=(
                "Could not save local "
                f"experiment: {error}"
            ),

        ) from error


@router.delete(
    "/experiments/{storage_id}"
)
def delete_local_experiment(
    storage_id: str,
    request: Request,
):

    try:
        directory = (
            get_local_directory(
                storage_id
            )
        )


        experiment = (
            read_local_experiment(
                directory
            )
        )


        runtime_state, _ = read_runtime_state(directory)
        experiment_state = runtime_state or experiment.get(
            "state",
            "Created",
        )

        digiflot = getattr(request.app.state, "digiflot", None)
        if digiflot is not None and digiflot.storage_id == storage_id:
            terminal_states = {
                digiflot.COMPLETED,
                digiflot.ABORTED,
                digiflot.ERROR,
            }
            if digiflot.state in terminal_states:
                digiflot.reset()
            elif digiflot.state != digiflot.IDLE:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        "The active experiment cannot be deleted. "
                        "Abort or finish it first."
                    ),
                )

        shutil.rmtree(
            directory
        )


        return {
            "storage_id": storage_id,
            "message": (
                "Local experiment deleted."
            ),
        }


    except HTTPException:
        raise


    except Exception as error:
        raise HTTPException(
            status_code=500,

            detail=(
                "Could not delete local "
                f"experiment: {error}"
            ),

        ) from error


@router.patch(
    "/experiments/{storage_id}/state"
)
def update_local_experiment_state(
    storage_id: str,
    payload: ExperimentStatePayload,
):

    try:
        new_state = (
            payload.state.strip()
        )


        if not new_state:
            raise HTTPException(
                status_code=422,

                detail=(
                    "Experiment state "
                    "cannot be empty."
                ),
            )


        directory = (
            get_local_directory(
                storage_id
            )
        )


        experiment = (
            read_local_experiment(
                directory
            )
        )


        experiment["state"] = (
            new_state
        )


        experiment["last_modified"] = (
            datetime.now()
            .replace(
                microsecond=0
            )
            .isoformat()
        )


        write_local_experiment(
            directory,
            experiment,
        )


        return local_experiment_response(
            directory,
            experiment,
        )


    except HTTPException:
        raise


    except Exception as error:
        raise HTTPException(
            status_code=500,

            detail=(
                "Could not update local "
                "experiment state: "
                f"{error}"
            ),

        ) from error