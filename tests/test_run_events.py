import json
import sqlite3

import pytest

from agentops.database import connection, init_db, workflow_registry
from agentops.database import run_events


@pytest.fixture
def test_db(tmp_path, monkeypatch):
    database_path = tmp_path / "test_agentops.db"

    monkeypatch.setattr(
        connection,
        "DATABASE_PATH",
        database_path,
    )

    temporary_connection = lambda: connection.get_connection(database_path)

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
        run_events,
        "get_connection",
        temporary_connection,
    )

    init_db.initialize_database()

    workflow_id = workflow_registry.register_workflow(
        "Test Workflow",
        "A workflow used for run event tests.",
    )

    with connection.get_connection(database_path) as conn:
        conn.execute(
            """
            INSERT INTO workflow_runs (
                id,
                workflow_id,
                status,
                created_at
            )
            VALUES (?, ?, ?, ?)
            """,
            (
                "run-test",
                workflow_id,
                "running",
                "2026-10-17T00:00:00+00:00",
            ),
        )

    return database_path


def test_valid_event_is_saved_and_retrieved(test_db):
    run_events.record_run_event(
        run_id="run-test",
        event_type="order_imported",
        severity="info",
        message="Order imported successfully.",
    )

    with connection.get_connection(test_db) as conn:
        row = conn.execute(
            """
            SELECT run_id, severity, message
            FROM run_events
            WHERE run_id = ?
            """,
            ("run-test",),
        ).fetchone()

    assert row is not None
    assert row["run_id"] == "run-test"
    assert row["severity"] == "info"
    assert row["message"] == "Order imported successfully."


def test_event_details_are_stored_as_json(test_db):
    details = {
        "order_id": "ORD-001",
        "amount": 25.50,
        "currency": "USD",
    }

    run_events.record_run_event(
        run_id="run-test",
        event_type="order_imported",
        severity="info",
        message="Order imported successfully.",
        details=details,
    )

    with connection.get_connection(test_db) as conn:
        row = conn.execute(
            """
            SELECT details
            FROM run_events
            WHERE run_id = ?
            """,
            ("run-test",),
        ).fetchone()

    assert row is not None
    assert isinstance(row["details"], str)
    assert json.loads(row["details"]) == details


def test_event_with_nonexistent_run_is_rejected(test_db):
    with pytest.raises(sqlite3.IntegrityError):
        run_events.record_run_event(
            run_id="nonexistent-run",
            event_type="order_imported",
            severity="info",
            message="This event should not be saved.",
        )
