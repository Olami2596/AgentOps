
from datetime import datetime, timezone
from uuid import uuid4

from agentops.database import audit_events
from agentops.database.connection import get_connection


def register_workflow(name: str, description: str) -> str:
    """Register a workflow and audit its registration atomically."""
    workflow_id = str(uuid4())
    created_at = datetime.now(timezone.utc).isoformat()

    with get_connection() as connection:
        connection.execute("BEGIN IMMEDIATE")

        connection.execute(
            """
            INSERT INTO workflows (id, name, description, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (workflow_id, name, description, created_at),
        )

        audit_events.record_audit_event(
            actor="workflow_registry",
            action="workflow_registered",
            target_id=workflow_id,
            outcome="success",
            details={"name": name},
            connection=connection,
        )

    return workflow_id


def set_workflow_enabled(workflow_id: str, enabled: bool) -> None:
    """Enable or disable a workflow and audit the change atomically."""
    if type(enabled) is not bool:
        raise TypeError("enabled must be a boolean.")

    action = "workflow_enabled" if enabled else "workflow_disabled"

    with get_connection() as connection:
        connection.execute("BEGIN IMMEDIATE")

        workflow = connection.execute(
            """
            SELECT id
            FROM workflows
            WHERE id = ?
            """,
            (workflow_id,),
        ).fetchone()

        if workflow is None:
            raise LookupError(
                f"Workflow {workflow_id!r} does not exist."
            )

        connection.execute(
            """
            UPDATE workflows
            SET enabled = ?
            WHERE id = ?
            """,
            (int(enabled), workflow_id),
        )

        audit_events.record_audit_event(
            actor="workflow_registry",
            action=action,
            target_id=workflow_id,
            outcome="success",
            details={"enabled": enabled},
            connection=connection,
        )

def list_workflows(enabled_only: bool = True) -> list[dict]:
    query = """
        SELECT id, name, description, enabled, created_at
        FROM workflows
    """

    if enabled_only:
        query += " WHERE enabled = 1"

    query += " ORDER BY name"

    with get_connection() as connection:
        rows = connection.execute(query).fetchall()

    return [dict(row) for row in rows]


def get_workflow(workflow_id: str) -> dict | None:
    with get_connection() as connection:
        row = connection.execute(
            """
            SELECT id, name, description, enabled, created_at
            FROM workflows
            WHERE id = ?
            """,
            (workflow_id,),
        ).fetchone()

    return dict(row) if row else None
