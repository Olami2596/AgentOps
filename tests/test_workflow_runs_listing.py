from unittest.mock import MagicMock, patch

import pytest

from agentops.database.workflow_runs import list_runs


def test_list_runs_returns_newest_runs_first():
    newest_run = {
        "id": "run-new",
        "workflow_id": "workflow-123",
        "status": "succeeded",
        "started_at": None,
        "finished_at": None,
        "summary": None,
        "retry_of_run_id": None,
        "created_at": "2026-10-20T12:00:00+00:00",
    }

    older_run = {
        "id": "run-old",
        "workflow_id": "workflow-123",
        "status": "failed",
        "started_at": None,
        "finished_at": None,
        "summary": None,
        "retry_of_run_id": None,
        "created_at": "2026-10-19T12:00:00+00:00",
    }

    mock_connection = MagicMock()
    mock_connection.execute.return_value.fetchall.return_value = [
        newest_run,
        older_run,
    ]

    with patch("agentops.database.workflow_runs.get_connection") as mock_get_connection:
        mock_get_connection.return_value.__enter__.return_value = mock_connection

        result = list_runs()

    assert result == [newest_run, older_run]

    query = mock_connection.execute.call_args.args[0]
    assert "ORDER BY created_at DESC, id DESC" in query
    assert mock_connection.execute.call_args.args[1] == (50,)


@pytest.mark.parametrize("limit", [0, -1, 201])
def test_list_runs_rejects_invalid_limit(limit):
    with pytest.raises(ValueError, match="Limit must be between 1 and 200"):
        list_runs(limit=limit)
