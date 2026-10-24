import json
from datetime import datetime, timezone
from uuid import uuid4
import logging

from agentops.database import audit_events
from agentops.database.connection import get_connection
from agentops.database.workflow_runs import get_run, update_run_status
from agentops.workflows.order_import import process_orders_in_run

logger = logging.getLogger(__name__)

RETRYABLE_STATUSES = {"failed", "partially_succeeded"}


def check_retry_eligibility(run_id: str) -> dict:
    """Check whether an existing workflow run can be retried."""
    with get_connection() as connection:
        run = connection.execute(
            """
            SELECT id, status
            FROM workflow_runs
            WHERE id = ?
            """,
            (run_id,),
        ).fetchone()

    if run is None:
        raise LookupError(f"Workflow run {run_id!r} does not exist.")

    if run["status"] in RETRYABLE_STATUSES:
        return {
            "eligible": True,
            "reason": "Run status allows a retry.",
        }

    return {
        "eligible": False,
        "reason": (f"Workflow run with status {run['status']!r} " "cannot be retried."),
    }


def request_retry(run_id: str) -> str:
    """Create a pending retry approval and audit the request atomically."""
    approval_id = str(uuid4())
    created_at = datetime.now(timezone.utc).isoformat()

    with get_connection() as connection:
        connection.execute("BEGIN IMMEDIATE")

        run = connection.execute(
            """
            SELECT id, status
            FROM workflow_runs
            WHERE id = ?
            """,
            (run_id,),
        ).fetchone()

        if run is None:
            raise LookupError(f"Workflow run {run_id!r} does not exist.")

        if run["status"] not in RETRYABLE_STATUSES:
            raise ValueError(f"Workflow run {run_id!r} is not eligible for retry.")

        connection.execute(
            """
            INSERT INTO approvals (
                id, run_id, action, status,
                created_at, decided_at, retry_run_id
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                approval_id,
                run_id,
                "retry_workflow",
                "pending",
                created_at,
                None,
                None,
            ),
        )

        audit_events.record_audit_event(
            actor="retry_service",
            action="retry_approval_requested",
            target_id=approval_id,
            outcome="success",
            details={"run_id": run_id},
            connection=connection,
        )

    return approval_id


def decide_retry_approval(
    approval_id: str,
    decision: str,
) -> None:
    """Approve or reject a pending retry request and audit the decision."""
    if decision not in {"approved", "rejected"}:
        raise ValueError("Decision must be 'approved' or 'rejected'.")

    decided_at = datetime.now(timezone.utc).isoformat()

    with get_connection() as connection:
        connection.execute("BEGIN IMMEDIATE")

        approval = connection.execute(
            """
            SELECT id, action, status
            FROM approvals
            WHERE id = ?
            """,
            (approval_id,),
        ).fetchone()

        if approval is None:
            raise LookupError(f"Retry approval {approval_id!r} does not exist.")

        if approval["action"] != "retry_workflow":
            raise ValueError(f"Approval {approval_id!r} is not a retry approval.")

        if approval["status"] != "pending":
            raise ValueError(
                "Only pending approvals can be decided. "
                f"Approval {approval_id!r} is not pending."
            )

        result = connection.execute(
            """
            UPDATE approvals
            SET status = ?, decided_at = ?
            WHERE id = ? AND status = 'pending'
            """,
            (decision, decided_at, approval_id),
        )

        if result.rowcount != 1:
            raise ValueError("Only pending approvals can be decided.")

        audit_events.record_audit_event(
            actor="retry_service",
            action="retry_approval_decided",
            target_id=approval_id,
            outcome="success",
            details={"decision": decision},
            connection=connection,
        )


def execute_approved_retry(approval_id: str) -> str:
    """Create and execute one retry for an approved request."""
    retry_run_id = str(uuid4())
    now = datetime.now(timezone.utc).isoformat()

    with get_connection() as connection:
        connection.execute("BEGIN IMMEDIATE")

        approval = connection.execute(
            """
            SELECT id, run_id, action, status, retry_run_id
            FROM approvals
            WHERE id = ?
            """,
            (approval_id,),
        ).fetchone()

        if approval is None:
            raise LookupError(f"Retry approval {approval_id!r} does not exist.")

        if approval["action"] != "retry_workflow":
            raise ValueError(f"Approval {approval_id!r} is not a retry approval.")

        if approval["retry_run_id"] is not None:
            raise ValueError(f"Retry approval {approval_id!r} has already been used.")

        if approval["status"] != "approved":
            raise ValueError(
                "Retry execution requires an approved approval record. "
                f"Current status: {approval['status']!r}."
            )

        original_run_id = approval["run_id"]

        original_run = connection.execute(
            """
            SELECT id, workflow_id, status
            FROM workflow_runs
            WHERE id = ?
            """,
            (original_run_id,),
        ).fetchone()

        if original_run is None:
            raise LookupError(
                f"Original workflow run {original_run_id!r} " "does not exist."
            )

        if original_run["status"] not in RETRYABLE_STATUSES:
            raise ValueError(
                f"Original workflow run {original_run_id!r} "
                "is no longer eligible for retry."
            )

        workflow = connection.execute(
            """
            SELECT id, enabled
            FROM workflows
            WHERE id = ?
            """,
            (original_run["workflow_id"],),
        ).fetchone()

        if workflow is None:
            raise LookupError(
                f"Workflow {original_run['workflow_id']!r} " "does not exist."
            )

        if not workflow["enabled"]:
            raise ValueError(
                f"Workflow {workflow['id']!r} is disabled " "and cannot be retried."
            )

        saved_items = connection.execute(
            """
            SELECT source_name, payload, status
            FROM order_import_items
            WHERE run_id = ?
            ORDER BY rowid
            """,
            (original_run_id,),
        ).fetchall()

        # Retry only saved inputs that remain pending or rejected.
        retryable_items = [
            item for item in saved_items if item["status"] in {"pending", "rejected"}
        ]

        if not retryable_items:
            raise ValueError(
                "The original run has no saved order inputs " "that remain retryable."
            )

        source_names = {item["source_name"] for item in retryable_items}

        if len(source_names) != 1:
            raise ValueError("Retryable order inputs must have the same source name.")

        source_name = next(iter(source_names))
        orders = [json.loads(item["payload"]) for item in retryable_items]

        # Create the retry run inside the current transaction.
        connection.execute(
            """
            INSERT INTO workflow_runs (
                id, workflow_id, status, created_at,
                started_at, finished_at, summary, retry_of_run_id
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                retry_run_id,
                original_run["workflow_id"],
                "running",
                now,
                now,
                None,
                None,
                original_run_id,
            ),
        )

        # Claim the approval in the same transaction.
        claim = connection.execute(
            """
            UPDATE approvals
            SET retry_run_id = ?
            WHERE id = ?
              AND status = 'approved'
              AND retry_run_id IS NULL
            """,
            (retry_run_id, approval_id),
        )

        if claim.rowcount != 1:
            raise ValueError(f"Retry approval {approval_id!r} has already been used.")

        # A failed audit write rolls back the run and approval claim.
        audit_events.record_audit_event(
            actor="retry_service",
            action="retry_started",
            target_id=retry_run_id,
            outcome="success",
            details={
                "approval_id": approval_id,
                "original_run_id": original_run_id,
            },
            connection=connection,
        )

    # Processing begins only after the transaction commits.
    try:
        process_orders_in_run(
            orders,
            source_name,
            retry_run_id,
        )

    except Exception as exc:
        # Attempt recovery, but never replace the original processing error.
        try:
            retry_run = get_run(retry_run_id)

            if retry_run is not None and retry_run["status"] == "running":
                failure_summary = json.dumps(
                    {
                        "source_name": source_name,
                        "total_orders": len(orders),
                        "execution_error": str(exc),
                        "error_type": type(exc).__name__,
                    }
                )

                update_run_status(
                    retry_run_id,
                    "failed",
                    summary=failure_summary,
                )

        except Exception as recovery_error:
            logger.exception(
                "Retry-run failure recovery failed for retry_run_id=%s "
                "original_error_type=%s recovery_error_type=%s",
                retry_run_id,
                type(exc).__name__,
                type(recovery_error).__name__,
            )
            exc.add_note(
                "Additionally, retry-run failure recovery failed: "
                f"{recovery_error!r}"
            )
        # Audit the processing failure even if recovery failed.
        try:
            audit_events.record_audit_event(
                actor="retry_service",
                action="retry_failed",
                target_id=retry_run_id,
                outcome="failure",
                details={
                    "approval_id": approval_id,
                    "original_run_id": original_run_id,
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                },
            )

        except Exception as audit_error:
            logger.exception(
                "Retry-failure audit logging failed for retry_run_id=%s "
                "original_error_type=%s audit_error_type=%s",
                retry_run_id,
                type(exc).__name__,
                type(audit_error).__name__,
            )
            exc.add_note(
                "Additionally, retry-failure audit logging failed: "
                f"{audit_error!r}"
            )

        # Preserve the original processing exception.
        raise

    return retry_run_id
