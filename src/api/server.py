from fastapi import APIRouter
from fastapi import HTTPException
from fastapi import Request


router = APIRouter(
    prefix="/api/server",
    tags=["server"],
)


@router.get("/experiments")
def get_available_experiments(
    request: Request,
):
    server = request.app.state.server

    try:
        experiments = (
            server.get_available_experiments()
        )

        return {
            "experiments": experiments,
        }

    except Exception as error:
        raise HTTPException(
            status_code=502,
            detail=str(error),
        ) from error


@router.get(
    "/experiments/{experiment_id}"
)
def get_experiment(
    experiment_id: int,
    request: Request,
):
    server = request.app.state.server

    try:
        experiment = server.get_experiment(
            experiment_id
        )

        if experiment is None:
            raise HTTPException(
                status_code=404,
                detail="Experiment not found.",
            )

        return experiment

    except HTTPException:
        raise

    except Exception as error:
        raise HTTPException(
            status_code=502,
            detail=str(error),
        ) from error