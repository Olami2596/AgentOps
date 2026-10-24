from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Query
from pydantic import BaseModel

from agentops.auth import AccessLevel, get_access_level
from agentops.database.workflow_registry import (
    list_workflows as list_workflows_service,
)
from agentops.database.workflow_runs import (
    get_run as get_run_service,
    list_runs as list_runs_service,
    get_retry_history as get_retry_history_service,
)
from agentops.workflows.retry_service import (
    request_retry as request_retry_service,
)
from agentops.database.workflow_health import (
    get_workflow_health as get_workflow_health_service,
    get_stale_runs as get_stale_runs_service,
)

class WorkflowResponse(BaseModel):
    id: str
    name: str
    description: str
    enabled: bool
    created_at: str


class WorkflowRunResponse(BaseModel):
    id: str
    workflow_id: str
    status: str
    started_at: str | None
    finished_at: str | None
    summary: str | None
    retry_of_run_id: str | None
    created_at: str

class WorkflowHealthResponse(BaseModel):
    workflow_id: str
    workflow_name: str
    workflow_enabled: bool
    total_runs: int
    pending_runs: int
    running_runs: int
    succeeded_runs: int
    partially_succeeded_runs: int
    failed_runs: int
    cancelled_runs: int
    average_duration_seconds: float | None
    success_rate: float | None
    has_repeated_failures: bool
class RetryRequestResponse(BaseModel):
    approval_id: str
    status: str
    message: str

class StaleRunResponse(BaseModel):
    run_id: str
    workflow_id: str
    workflow_name: str
    status: str
    started_at: str
    created_at: str
    retry_of_run_id: str | None
    running_duration_minutes: float
    stale_after_minutes: int
    diagnostic_status: str

app = FastAPI(title="AgentOps API")


@app.get("/workflows", response_model=list[WorkflowResponse])
def get_workflows(
    access_level: Annotated[AccessLevel, Depends(get_access_level)],
) -> list[WorkflowResponse]:
    return list_workflows_service()

@app.get(
    "/workflows/health",
    response_model=list[WorkflowHealthResponse],
)
def get_workflows_health(
    access_level: Annotated[AccessLevel, Depends(get_access_level)],
    window_hours: Annotated[int, Query(ge=1, le=720)] = 24,
) -> list[WorkflowHealthResponse]:
    return get_workflow_health_service(window_hours=window_hours)

@app.get("/runs", response_model=list[WorkflowRunResponse])
def get_workflow_runs(
    access_level: Annotated[AccessLevel, Depends(get_access_level)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[WorkflowRunResponse]:
    return list_runs_service(limit=limit)

@app.get(
    "/workflows/stale-runs",
    response_model=list[StaleRunResponse],
)
def get_stale_workflow_runs(
    access_level: Annotated[
        AccessLevel,
        Depends(get_access_level),
    ],
    stale_after_minutes: Annotated[
        int,
        Query(ge=1, le=10080),
    ] = 30,
) -> list[StaleRunResponse]:
    """List potentially stale runs without modifying their status."""
    return get_stale_runs_service(
        stale_after_minutes=stale_after_minutes,
    )

@app.get("/runs/{run_id}", response_model=WorkflowRunResponse)
def get_workflow_run(
    run_id: str,
    access_level: Annotated[AccessLevel, Depends(get_access_level)],
) -> WorkflowRunResponse:
    run = get_run_service(run_id)

    if run is None:
        raise HTTPException(
            status_code=404,
            detail="Workflow run not found",
        )

    return run


@app.get(
    "/runs/{run_id}/retry-history",
    response_model=list[WorkflowRunResponse],
)
def get_workflow_run_retry_history(
    run_id: str,
    access_level: Annotated[AccessLevel, Depends(get_access_level)],
) -> list[WorkflowRunResponse]:
    """Retrieve the complete retry family for a workflow run."""
    history = get_retry_history_service(run_id)

    if history is None:
        raise HTTPException(
            status_code=404,
            detail="Workflow run not found",
        )

    return history


@app.post(
    "/runs/{run_id}/retry",
    response_model=RetryRequestResponse,
)
def request_workflow_retry(
    run_id: str,
    access_level: Annotated[AccessLevel, Depends(get_access_level)],
) -> RetryRequestResponse:
    if access_level != "operator":
        raise HTTPException(
            status_code=403,
            detail="Operator access required",
        )

    try:
        approval_id = request_retry_service(run_id)
    except LookupError as exc:
        raise HTTPException(
            status_code=404,
            detail=str(exc),
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=409,
            detail=str(exc),
        ) from exc

    return {
        "approval_id": approval_id,
        "status": "pending",
        "message": "Retry approval request created successfully.",
    }
