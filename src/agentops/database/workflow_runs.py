import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any

from agentops.database.connection import get_connection

VALID_STATUSES = {
    "pending",
    "running",
    "succeeded",
    "partially_succeeded",
    "failed",
    "cancelled",
}

TERMINAL_STATUSES = {
    "succeeded",
    "partially_succeeded",
    "failed",
    "cancelled",
}

ALLOWED_TRANSITIONS = {
    "pending": {"running", "cancelled"},
    "running": TERMINAL_STATUSES,
}


def create_run(
    workflow_id: str,
    retry_of_run_id: str | None = None,
) -> str:
    run_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    with get_connection() as connection:
        # Acquire a write reservation before checking the workflow.
        connection.execute("BEGIN IMMEDIATE")

        workflow = connection.execute(
            "SELECT id, enabled FROM workflows WHERE id = ?",
            (workflow_id,),
        ).fetchone()

        if workflow is None:
            raise LookupError(f"Workflow {workflow_id!r} does not exist.")

        if not workflow["enabled"]:
            raise ValueError(
                f"Workflow {workflow_id!r} is disabled and cannot be executed."
            )

        connection.execute(
            """
            INSERT INTO workflow_runs (
                id,
                workflow_id,
                status,
                retry_of_run_id,
                created_at
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                run_id,
                workflow_id,
                "pending",
                retry_of_run_id,
                now,
            ),
        )

    return run_id


def update_run_status(
    run_id: str,
    status: str,
    summary: str | None = None,
) -> None:
    if status not in VALID_STATUSES:
        raise ValueError(
            f"Invalid run status: {status!r}. "
            f"Expected one of: {', '.join(sorted(VALID_STATUSES))}."
        )

    now = datetime.now(timezone.utc).isoformat()

    with get_connection() as connection:
        row = connection.execute(
            """
            SELECT status
            FROM workflow_runs
            WHERE id = ?
            """,
            (run_id,),
        ).fetchone()

        if row is None:
            raise LookupError(f"Workflow run {run_id!r} does not exist.")

        current_status = row["status"]

        if status not in ALLOWED_TRANSITIONS.get(current_status, set()):
            raise ValueError(
                f"Invalid run status transition: " f"{current_status!r} -> {status!r}."
            )

        if status == "running":
            connection.execute(
                """
                UPDATE workflow_runs
                SET status = ?, started_at = ?, summary = ?
                WHERE id = ?
                """,
                (status, now, summary, run_id),
            )
        elif status in TERMINAL_STATUSES:
            connection.execute(
                """
                UPDATE workflow_runs
                SET status = ?, finished_at = ?, summary = ?
                WHERE id = ?
                """,
                (status, now, summary, run_id),
            )


def get_run(run_id: str) -> dict[str, Any] | None:
    with get_connection() as connection:
        row = connection.execute(
            """
            SELECT
                id,
                workflow_id,
                status,
                started_at,
                finished_at,
                summary,
                retry_of_run_id,
                created_at
            FROM workflow_runs
            WHERE id = ?
            """,
            (run_id,),
        ).fetchone()

    return dict(row) if row is not None else None


def list_runs(limit: int = 50) -> list[dict[str, Any]]:
    if not 1 <= limit <= 200:
        raise ValueError("Limit must be between 1 and 200.")

    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT
                id,
                workflow_id,
                status,
                started_at,
                finished_at,
                summary,
                retry_of_run_id,
                created_at
            FROM workflow_runs
            ORDER BY created_at DESC, id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

    return [dict(row) for row in rows]


def get_retry_history(run_id: str) -> list[dict[str, Any]] | None:
    """Return the complete retry family containing the specified run.

    Includes the selected run, its ancestors, and all descendant retries.
    Returns None if the selected run does not exist.
    """
    with get_connection() as connection:
        rows = connection.execute(
            """
            WITH RECURSIVE retry_family(id) AS (
                SELECT id
                FROM workflow_runs
                WHERE id = ?

                UNION

                SELECT
                    CASE
                        WHEN workflow_runs.id = retry_family.id
                        THEN workflow_runs.retry_of_run_id
                        ELSE workflow_runs.id
                    END
                FROM workflow_runs
                JOIN retry_family
                    ON workflow_runs.id = retry_family.id
                    OR workflow_runs.retry_of_run_id = retry_family.id
                WHERE
                    CASE
                        WHEN workflow_runs.id = retry_family.id
                        THEN workflow_runs.retry_of_run_id
                        ELSE workflow_runs.id
                    END IS NOT NULL
            )
            SELECT
                id,
                workflow_id,
                status,
                started_at,
                finished_at,
                summary,
                retry_of_run_id,
                created_at
            FROM workflow_runs
            WHERE id IN (SELECT id FROM retry_family)
            ORDER BY created_at ASC, id ASC
            """,
            (run_id,),
        ).fetchall()

    if not rows:
        return None

    return [dict(row) for row in rows]
