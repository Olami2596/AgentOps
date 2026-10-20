import json
import sqlite3
from datetime import datetime

import pytest

from agentops.database import audit_events, connection, init_db


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
        audit_events,
        "get_connection",
        temporary_connection,
    )

    init_db.initialize_database()

    return database_path


def test_audit_event_is_saved_with_correct_fields(test_db):
    audit_events.record_audit_event(
        actor="retry_service",
        action="retry_approval_requested",
        target_id="run-test",
        outcome="success",
    )

    with connection.get_connection(test_db) as conn:
        row = conn.execute(
            """
            SELECT actor, action, target_id, outcome, created_at
            FROM audit_events
            WHERE target_id = ?
            """,
            ("run-test",),
        ).fetchone()

    assert row is not None
    assert row["actor"] == "retry_service"
    assert row["action"] == "retry_approval_requested"
    assert row["target_id"] == "run-test"
    assert row["outcome"] == "success"

    assert row["created_at"]
    timestamp = datetime.fromisoformat(row["created_at"])
    assert timestamp.tzinfo is not None


def test_audit_event_details_are_stored_as_json(test_db):
    details = {
        "approval_id": "approval-001",
        "decision": "approved",
        "retry_number": 1,
    }

    audit_events.record_audit_event(
        actor="retry_service",
        action="retry_approval_decided",
        target_id="approval-001",
        outcome="success",
        details=details,
    )

    with connection.get_connection(test_db) as conn:
        row = conn.execute(
            """
            SELECT details
            FROM audit_events
            WHERE target_id = ?
            """,
            ("approval-001",),
        ).fetchone()

    assert row is not None
    assert isinstance(row["details"], str)
    assert json.loads(row["details"]) == details


def test_audit_event_with_no_details_stores_null(test_db):
    audit_events.record_audit_event(
        actor="workflow_registry",
        action="workflow_disabled",
        target_id="workflow-001",
        outcome="success",
        details=None,
    )

    with connection.get_connection(test_db) as conn:
        row = conn.execute(
            """
            SELECT details
            FROM audit_events
            WHERE target_id = ?
            """,
            ("workflow-001",),
        ).fetchone()

    assert row is not None
    assert row["details"] is None


def test_supplied_connection_remains_under_callers_control(test_db):
    conn = sqlite3.connect(test_db)
    conn.row_factory = sqlite3.Row

    try:
        audit_events.record_audit_event(
            actor="retry_service",
            action="retry_started",
            target_id="run-rollback-test",
            outcome="success",
            connection=conn,
        )

        # The helper must leave the connection open.
        result = conn.execute("SELECT 1").fetchone()
        assert result[0] == 1

        # The helper must not commit the caller's transaction.
        assert conn.in_transaction

        conn.rollback()
    finally:
        conn.close()

    with connection.get_connection(test_db) as verification_conn:
        row = verification_conn.execute(
            """
            SELECT id
            FROM audit_events
            WHERE target_id = ?
            """,
            ("run-rollback-test",),
        ).fetchone()

    assert row is None
