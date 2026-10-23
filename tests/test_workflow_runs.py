
import pytest

from agentops.database import connection, init_db, workflow_registry
from agentops.database import workflow_runs


@pytest.fixture
def test_db(tmp_path, monkeypatch):
    database_path = tmp_path / "test_agentops.db"

    monkeypatch.setattr(
        connection,
        "DATABASE_PATH",
        database_path,
    )

    temporary_connection = lambda: connection.get_connection(
        database_path
    )

    monkeypatch.setattr(
        init_db,
        "get_connection",
        temporary_connection,
    )
    monkeypatch.setattr(
        workflow_registry,
        "get_connection",
        temporary_connection,
    )
    monkeypatch.setattr(
        workflow_runs,
        "get_connection",
        temporary_connection,
    )

    init_db.initialize_database()

    workflow_id = workflow_registry.register_workflow(
        "Test Workflow",
        "A workflow used for run-management tests.",
    )

    return database_path, workflow_id


def test_new_run_has_pending_status(test_db):
    _, workflow_id = test_db

    run_id = workflow_runs.create_run(workflow_id)

    run = workflow_runs.get_run(run_id)

    assert run is not None
    assert run["id"] == run_id
    assert run["workflow_id"] == workflow_id
    assert run["status"] == "pending"
    assert run["created_at"] is not None
    assert run["started_at"] is None
    assert run["finished_at"] is None
    assert run["retry_of_run_id"] is None


def test_run_transitions_from_pending_to_running_to_succeeded(test_db):
    _, workflow_id = test_db

    run_id = workflow_runs.create_run(workflow_id)

    workflow_runs.update_run_status(
        run_id,
        "running",
        summary="Workflow execution started.",
    )

    running_run = workflow_runs.get_run(run_id)

    assert running_run["status"] == "running"
    assert running_run["started_at"] is not None
    assert running_run["finished_at"] is None
    assert running_run["summary"] == "Workflow execution started."

    workflow_runs.update_run_status(
        run_id,
        "succeeded",
        summary="Workflow completed successfully.",
    )

    completed_run = workflow_runs.get_run(run_id)

    assert completed_run["status"] == "succeeded"
    assert completed_run["started_at"] is not None
    assert completed_run["finished_at"] is not None
    assert (
        completed_run["summary"]
        == "Workflow completed successfully."
    )


def test_nonexistent_run_raises_lookup_error(test_db):
    with pytest.raises(LookupError, match="does not exist"):
        workflow_runs.update_run_status(
            "missing-run",
            "running",
        )


def test_get_run_returns_none_for_nonexistent_run(test_db):
    assert workflow_runs.get_run("missing-run") is None


def test_invalid_status_transition_is_rejected(test_db):
    _, workflow_id = test_db

    run_id = workflow_runs.create_run(workflow_id)

    with pytest.raises(ValueError, match="Invalid run status transition"):
        workflow_runs.update_run_status(
            run_id,
            "succeeded",
        )

    run = workflow_runs.get_run(run_id)

    assert run["status"] == "pending"
    assert run["started_at"] is None
    assert run["finished_at"] is None


def test_invalid_status_value_is_rejected(test_db):
    _, workflow_id = test_db

    run_id = workflow_runs.create_run(workflow_id)

    with pytest.raises(ValueError, match="Invalid run status"):
        workflow_runs.update_run_status(
            run_id,
            "unknown",
        )


def test_retry_run_references_original_run(test_db):
    _, workflow_id = test_db

    original_run_id = workflow_runs.create_run(workflow_id)

    retry_run_id = workflow_runs.create_run(
        workflow_id,
        retry_of_run_id=original_run_id,
    )

    original_run = workflow_runs.get_run(original_run_id)
    retry_run = workflow_runs.get_run(retry_run_id)

    assert original_run["id"] == original_run_id
    assert retry_run["id"] == retry_run_id
    assert retry_run["retry_of_run_id"] == original_run_id
    assert retry_run["status"] == "pending"
    assert retry_run_id != original_run_id


def test_get_retry_history_returns_complete_retry_family(test_db):
    _, workflow_id = test_db

    original_id = workflow_runs.create_run(workflow_id)
    retry_one_id = workflow_runs.create_run(
        workflow_id,
        retry_of_run_id=original_id,
    )
    retry_two_id = workflow_runs.create_run(
        workflow_id,
        retry_of_run_id=retry_one_id,
    )

    history = workflow_runs.get_retry_history(original_id)

    assert history is not None
    assert {run["id"] for run in history} == {
        original_id,
        retry_one_id,
        retry_two_id,
    }
    assert len(history) == 3


def test_get_retry_history_from_middle_retry_includes_ancestors_and_descendants(
    test_db,
):
    _, workflow_id = test_db

    original_id = workflow_runs.create_run(workflow_id)
    retry_one_id = workflow_runs.create_run(
        workflow_id,
        retry_of_run_id=original_id,
    )
    retry_two_id = workflow_runs.create_run(
        workflow_id,
        retry_of_run_id=retry_one_id,
    )

    history = workflow_runs.get_retry_history(retry_one_id)

    assert history is not None
    assert {run["id"] for run in history} == {
        original_id,
        retry_one_id,
        retry_two_id,
    }


def test_get_retry_history_returns_single_run_without_retries(test_db):
    _, workflow_id = test_db

    run_id = workflow_runs.create_run(workflow_id)

    history = workflow_runs.get_retry_history(run_id)

    assert history is not None
    assert len(history) == 1
    assert history[0]["id"] == run_id
    assert history[0]["retry_of_run_id"] is None


def test_get_retry_history_returns_none_for_missing_run(test_db):
    history = workflow_runs.get_retry_history("missing-run")

    assert history is None


def test_get_retry_history_handles_circular_relationships(test_db):
    database_path, workflow_id = test_db

    run_a_id = workflow_runs.create_run(workflow_id)
    run_b_id = workflow_runs.create_run(
        workflow_id,
        retry_of_run_id=run_a_id,
    )

    # Create a cycle directly in the test database:
    # run A -> run B -> run A.
    # This represents corrupted data, not a valid retry workflow.
    with connection.get_connection(database_path) as conn:
        conn.execute(
            """
            UPDATE workflow_runs
            SET retry_of_run_id = ?
            WHERE id = ?
            """,
            (run_b_id, run_a_id),
        )

    history = workflow_runs.get_retry_history(run_a_id)

    assert history is not None
    assert {run["id"] for run in history} == {
        run_a_id,
        run_b_id,
    }
    assert len(history) == 2
