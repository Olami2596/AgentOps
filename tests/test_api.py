
import os
from unittest.mock import patch
from fastapi.testclient import TestClient
from agentops.api import app

READ_KEY = "test-read-key"
OPERATOR_KEY = "test-operator-key"

os.environ["AGENTOPS_READ_KEY"] = READ_KEY
os.environ["AGENTOPS_OPERATOR_KEY"] = OPERATOR_KEY

client = TestClient(app, raise_server_exceptions=False)

def get_read_headers():
    return {"X-API-Key": READ_KEY}


def get_operator_headers():
    return {"X-API-Key": OPERATOR_KEY}


def test_get_workflows_returns_success():
    expected_workflows = [
        {
            "id": "workflow-123",
            "name": "Order Import",
            "description": "Imports customer orders.",
            "enabled": 1,
            "created_at": "2026-10-20",
        }
    ]

    with patch(
        "agentops.api.list_workflows_service",
        return_value=expected_workflows,
    ):
        response = client.get(
            "/workflows",
            headers=get_read_headers(),
        )

    assert response.status_code == 200
    assert isinstance(response.json(), list)
    assert response.json() == [
        {
            **expected_workflows[0],
            "enabled": True,
        }
    ]


def test_get_workflow_run_returns_run():
    expected_run = {
        "id": "run-123",
        "workflow_id": "workflow-123",
        "status": "failed",
        "started_at": "2026-10-20T10:00:00+00:00",
        "finished_at": "2026-10-20T10:01:00+00:00",
        "summary": "Test run",
        "retry_of_run_id": None,
        "created_at": "2026-10-20T10:00:00+00:00",
    }

    with patch(
        "agentops.api.get_run_service",
        return_value=expected_run,
    ):
        response = client.get(
            "/runs/run-123",
            headers=get_read_headers(),
        )

    assert response.status_code == 200
    assert response.json() == expected_run


def test_get_workflow_run_returns_404_when_missing():
    with patch(
        "agentops.api.get_run_service",
        return_value=None,
    ):
        response = client.get(
            "/runs/missing-run",
            headers=get_read_headers(),
        )

    assert response.status_code == 404
    assert response.json() == {"detail": "Workflow run not found"}


def test_request_workflow_retry_returns_pending_approval():
    with patch(
        "agentops.api.request_retry_service",
        return_value="approval-123",
    ):
        response = client.post(
            "/runs/run-123/retry",
            headers=get_operator_headers(),
        )

    assert response.status_code == 200
    assert response.json() == {
        "approval_id": "approval-123",
        "status": "pending",
        "message": "Retry approval request created successfully.",
    }


def test_request_workflow_retry_returns_404_when_run_missing():
    with patch(
        "agentops.api.request_retry_service",
        side_effect=LookupError(
            "Workflow run 'missing' does not exist."
        ),
    ):
        response = client.post(
            "/runs/missing/retry",
            headers=get_operator_headers(),
        )

    assert response.status_code == 404
    assert response.json() == {
        "detail": "Workflow run 'missing' does not exist."
    }


def test_request_workflow_retry_returns_409_when_ineligible():
    with patch(
        "agentops.api.request_retry_service",
        side_effect=ValueError(
            "Workflow run is not eligible for retry."
        ),
    ):
        response = client.post(
            "/runs/run-123/retry",
            headers=get_operator_headers(),
        )

    assert response.status_code == 409
    assert response.json() == {
        "detail": "Workflow run is not eligible for retry."
    }


def test_get_workflows_handles_unexpected_error():
    with patch(
        "agentops.api.list_workflows_service",
        side_effect=RuntimeError("Internal database details"),
    ):
        response = client.get(
            "/workflows",
            headers=get_read_headers(),
        )

    assert response.status_code == 500
    assert response.text == "Internal Server Error"
    assert "Internal database details" not in response.text


def test_get_workflows_rejects_missing_api_key():
    response = client.get("/workflows")

    assert response.status_code == 401
    assert response.json() == {
        "detail": "Invalid or missing API key"
    }


def test_get_workflows_rejects_invalid_api_key():
    response = client.get(
        "/workflows",
        headers={"X-API-Key": "invalid-test-key"},
    )

    assert response.status_code == 401
    assert response.json() == {
        "detail": "Invalid or missing API key"
    }


def test_read_only_key_cannot_request_retry():
    with patch("agentops.api.request_retry_service") as mock_retry:
        response = client.post(
            "/runs/run-123/retry",
            headers=get_read_headers(),
        )

    assert response.status_code == 403
    assert response.json() == {
        "detail": "Operator access required"
    }
    mock_retry.assert_not_called()


def test_get_workflow_runs_returns_recent_runs():
    expected_runs = [
        {
            "id": "run-new",
            "workflow_id": "workflow-123",
            "status": "succeeded",
            "started_at": None,
            "finished_at": None,
            "summary": "Latest run",
            "retry_of_run_id": None,
            "created_at": "2026-10-20T12:00:00+00:00",
        }
    ]

    with patch(
        "agentops.api.list_runs_service",
        return_value=expected_runs,
    ) as mock_list_runs:
        response = client.get(
            "/runs",
            headers=get_read_headers(),
        )

    assert response.status_code == 200
    assert response.json() == expected_runs
    mock_list_runs.assert_called_once_with(limit=50)


def test_get_workflow_runs_accepts_custom_limit():
    with patch(
        "agentops.api.list_runs_service",
        return_value=[],
    ) as mock_list_runs:
        response = client.get(
            "/runs?limit=10",
            headers=get_read_headers(),
        )

    assert response.status_code == 200
    assert response.json() == []
    mock_list_runs.assert_called_once_with(limit=10)


def test_get_workflow_runs_rejects_invalid_limit():
    response = client.get(
        "/runs?limit=0",
        headers=get_read_headers(),
    )

    assert response.status_code == 422


def test_get_retry_history_returns_complete_family():
    original_run = {
        "id": "run-original",
        "workflow_id": "workflow-123",
        "status": "failed",
        "started_at": "2026-10-20T10:00:00+00:00",
        "finished_at": "2026-10-20T10:01:00+00:00",
        "summary": "Original execution failed",
        "retry_of_run_id": None,
        "created_at": "2026-10-20T10:00:00+00:00",
    }

    retry_one = {
        "id": "run-retry-1",
        "workflow_id": "workflow-123",
        "status": "failed",
        "started_at": "2026-10-20T10:05:00+00:00",
        "finished_at": "2026-10-20T10:06:00+00:00",
        "summary": "First retry failed",
        "retry_of_run_id": "run-original",
        "created_at": "2026-10-20T10:05:00+00:00",
    }

    retry_two = {
        "id": "run-retry-2",
        "workflow_id": "workflow-123",
        "status": "succeeded",
        "started_at": "2026-10-20T10:10:00+00:00",
        "finished_at": "2026-10-20T10:11:00+00:00",
        "summary": "Second retry succeeded",
        "retry_of_run_id": "run-retry-1",
        "created_at": "2026-10-20T10:10:00+00:00",
    }

    expected_history = [
        original_run,
        retry_one,
        retry_two,
    ]

    with patch(
        "agentops.api.get_retry_history_service",
        return_value=expected_history,
    ) as mock_history:
        response = client.get(
            "/runs/run-retry-2/retry-history",
            headers=get_read_headers(),
        )

    assert response.status_code == 200
    assert response.json() == expected_history
    mock_history.assert_called_once_with("run-retry-2")


def test_get_retry_history_returns_404_when_run_missing():
    with patch(
        "agentops.api.get_retry_history_service",
        return_value=None,
    ) as mock_history:
        response = client.get(
            "/runs/missing-run/retry-history",
            headers=get_read_headers(),
        )

    assert response.status_code == 404
    assert response.json() == {
        "detail": "Workflow run not found"
    }
    mock_history.assert_called_once_with("missing-run")


def test_get_retry_history_rejects_missing_api_key():
    with patch(
        "agentops.api.get_retry_history_service"
    ) as mock_history:
        response = client.get(
            "/runs/run-123/retry-history",
        )

    assert response.status_code == 401
    assert response.json() == {
        "detail": "Invalid or missing API key"
    }
    mock_history.assert_not_called()
