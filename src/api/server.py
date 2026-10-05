from fastapi import APIRouter, HTTPException, Request


router = APIRouter(
    prefix="/api/server",
    tags=["server"],
)


def get_sync(request: Request):
    manager = getattr(request.app.state, "server_sync", None)
    if manager is None:
        raise HTTPException(status_code=503, detail="Server synchronization is unavailable.")
    return manager


@router.get("/status")
def server_status(request: Request):
    return get_sync(request).status_payload()


@router.post("/sync", status_code=202)
def sync_now(request: Request):
    manager = get_sync(request)
    manager.force_sync()
    return {
        "accepted": True,
        "status": manager.status_payload(),
    }


@router.get("/catalog")
def get_catalog(request: Request):
    manager = get_sync(request)
    return {
        "catalog": manager.catalog_payload(),
        "sync": manager.status_payload(),
    }


# Backward-compatible local browser endpoint. New UI uses /catalog, but keeping
# this flat endpoint avoids breaking cached JS or older Edge pages during an
# update/restart.
@router.get("/experiments")
def get_available_experiments(request: Request):
    manager = get_sync(request)
    catalog = manager.catalog_payload()
    experiments = []
    for user in catalog.get("users") or []:
        for campaign in user.get("campaigns") or []:
            for experiment in campaign.get("experiments") or []:
                item = dict(experiment)
                item.setdefault("user_name", user.get("name"))
                item.setdefault("campaign_name", campaign.get("name"))
                item.setdefault("campaign_id", campaign.get("id"))
                experiments.append(item)
    return {
        "experiments": experiments,
        "sync": manager.status_payload(),
    }


@router.get("/experiments/{experiment_id}")
def get_experiment(experiment_id: int, request: Request):
    manager = get_sync(request)
    try:
        experiment = manager.get_experiment(experiment_id)
        if experiment is None:
            raise HTTPException(status_code=404, detail="Experiment not found.")
        return experiment
    except HTTPException:
        raise
    except RuntimeError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except Exception as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
