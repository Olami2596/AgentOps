import json

import pytest

from agentops.database import audit_events
from agentops.database import connection, init_db, workflow_registry
from agentops.database.workflow_registry import (
    get_workflow,
    list_workflows,
    register_workflow,
    set_workflow_enabled,
)


@pytest.fixture
def test_db(tmp_path, monkeypatch):
    database_path = tmp_path / "test_agentops.db"

    monkeypatch.setattr(
        connection,
        "DATABASE_PATH",
        database_path,
    )
    monkeypatch.setattr(
        init_db,
        "get_connection",
        lambda: connection.get_connection(database_path),
    )
    monkeypatch.setattr(
        workflow_registry,
        "get_connection",
        lambda: connection.get_connection(database_path),
    )

    init_db.initialize_database()
    return database_path


def test_register_and_get_workflow(test_db):
    workflow_id = register_workflow(
        "Order Import",
        "Imports and validates customer orders.",
    )

    workflow = get_workflow(workflow_id)

    assert workflow is not None
    assert workflow["id"] == workflow_id
    assert workflow["name"] == "Order Import"
    assert workflow["enabled"] == 1


def test_list_workflows(test_db):
    register_workflow("Order Import", "Imports orders.")
    register_workflow("Customer Report", "Generates customer reports.")

    workflows = list_workflows()

    assert len(workflows) == 2
    assert [workflow["name"] for workflow in workflows] == [
        "Customer Report",
        "Order Import",
    ]


def test_get_missing_workflow_returns_none(test_db):
    assert get_workflow("does-not-exist") is None


def test_register_workflow_creates_audit_event(test_db):
    workflow_id = register_workflow(
        "Order Import",
        "Imports and validates customer orders.",
    )

    workflow = get_workflow(workflow_id)
    assert workflow is not None

    with connection.get_connection(test_db) as conn:
        audit_event = conn.execute(
            """
            SELECT actor, action, target_id, outcome, details
            FROM audit_events
            WHERE action = ?
              AND target_id = ?
            """,
            ("workflow_registered", workflow_id),
        ).fetchone()

    assert audit_event is not None
    assert audit_event["actor"] == "workflow_registry"
    assert audit_event["action"] == "workflow_registered"
    assert audit_event["target_id"] == workflow_id
    assert audit_event["outcome"] == "success"
    assert json.loads(audit_event["details"]) == {
        "name": "Order Import",
    }


def test_audit_failure_rolls_back_workflow_registration(
    test_db,
    monkeypatch,
):
    def fail_audit(*args, **kwargs):
        raise RuntimeError("Audit write failed")

    monkeypatch.setattr(
        audit_events,
        "record_audit_event",
        fail_audit,
    )

    with pytest.raises(
        RuntimeError,
        match="Audit write failed",
    ):
        register_workflow(
            "Order Import",
            "Imports and validates customer orders.",
        )

    with connection.get_connection(test_db) as conn:
        workflow = conn.execute(
            """
            SELECT id
            FROM workflows
            WHERE name = ?
            """,
            ("Order Import",),
        ).fetchone()

        audit_event = conn.execute(
            """
            SELECT id
            FROM audit_events
            WHERE action = ?
            """,
            ("workflow_registered",),
        ).fetchone()

    assert workflow is None
    assert audit_event is None


@pytest.mark.parametrize(
    ("enabled", "expected_action"),
    [
        (False, "workflow_disabled"),
        (True, "workflow_enabled"),
    ],
)
def test_set_workflow_enabled_updates_state_and_audits_change(
    test_db,
    enabled,
    expected_action,
):
    workflow_id = register_workflow(
        "Order Import",
        "Imports customer orders.",
    )

    set_workflow_enabled(workflow_id, enabled)

    workflow = get_workflow(workflow_id)
    assert workflow is not None
    assert workflow["enabled"] == int(enabled)

    with connection.get_connection(test_db) as conn:
        event = conn.execute(
            """
            SELECT actor, action, target_id, outcome, details
            FROM audit_events
            WHERE action = ?
              AND target_id = ?
            """,
            (expected_action, workflow_id),
        ).fetchone()

    assert event is not None
    assert event["actor"] == "workflow_registry"
    assert event["action"] == expected_action
    assert event["target_id"] == workflow_id
    assert event["outcome"] == "success"
    assert json.loads(event["details"]) == {"enabled": enabled}


def test_set_workflow_enabled_raises_for_missing_workflow(test_db):
    with pytest.raises(LookupError, match="does not exist"):
        set_workflow_enabled("missing-workflow-id", False)


def test_audit_failure_rolls_back_enabled_state(
    test_db,
    monkeypatch,
):
    workflow_id = register_workflow(
        "Order Import",
        "Imports customer orders.",
    )

    def fail_audit(*args, **kwargs):
        raise RuntimeError("Audit write failed")

    monkeypatch.setattr(
        audit_events,
        "record_audit_event",
        fail_audit,
    )

    with pytest.raises(RuntimeError, match="Audit write failed"):
        set_workflow_enabled(workflow_id, False)

    workflow = get_workflow(workflow_id)

    assert workflow is not None
    assert workflow["enabled"] == 1


@pytest.mark.parametrize("invalid_value", [1, "false", None, 0])
def test_set_workflow_enabled_rejects_non_booleans(
    test_db,
    invalid_value,
):
    workflow_id = register_workflow(
        "Order Import",
        "Imports customer orders.",
    )

    with pytest.raises(TypeError, match="enabled must be a boolean"):
        set_workflow_enabled(workflow_id, invalid_value)

    workflow = get_workflow(workflow_id)

    assert workflow is not None
    assert workflow["enabled"] == 1
