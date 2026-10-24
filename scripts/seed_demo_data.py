import json
from datetime import datetime, timedelta, timezone
from typing import Any

from agentops.database.connection import get_connection

DEMO_WORKFLOWS = [
    {
        "id": "demo-workflow-order-import",
        "name": "[DEMO] Order Import",
        "description": "Imports and validates customer orders.",
        "enabled": 1,
    },
    {
        "id": "demo-workflow-feedback",
        "name": "[DEMO] Customer Feedback Analysis",
        "description": "Analyzes customer feedback and sentiment.",
        "enabled": 1,
    },
    {
        "id": "demo-workflow-lead-intake",
        "name": "[DEMO] Lead Intake",
        "description": "Validates and routes incoming leads.",
        "enabled": 0,
    },
]

REQUIRED_TABLES = {
    "workflows",
    "workflow_runs",
    "orders",
    "order_import_items",
    "run_events",
    "approvals",
    "audit_events",
}


def timestamp_ago(minutes: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat()


def build_demo_runs() -> list[dict[str, Any]]:
    """Build stable demo runs with timestamps relative to the current time."""
    now = datetime.now(timezone.utc)

    def run(
        run_id: str,
        workflow_id: str,
        status: str,
        minutes_ago: int,
        duration_seconds: int | None = None,
        retry_of_run_id: str | None = None,
        summary: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        created_at = now - timedelta(minutes=minutes_ago)

        started_at = None
        finished_at = None

        if status != "pending":
            started_at = created_at + timedelta(seconds=2)

        if duration_seconds is not None and started_at is not None:
            finished_at = started_at + timedelta(seconds=duration_seconds)

        return {
            "id": run_id,
            "workflow_id": workflow_id,
            "status": status,
            "started_at": (started_at.isoformat() if started_at else None),
            "finished_at": (finished_at.isoformat() if finished_at else None),
            "summary": json.dumps(summary or {"demo_data": True}),
            "retry_of_run_id": retry_of_run_id,
            "created_at": created_at.isoformat(),
        }

    order = "demo-workflow-order-import"
    feedback = "demo-workflow-feedback"
    lead = "demo-workflow-lead-intake"

    return [
        run(
            "demo-run-order-success-1",
            order,
            "succeeded",
            30,
            12,
            summary={
                "demo_data": True,
                "source_name": "orders-morning.csv",
                "total_orders": 25,
                "imported_count": 25,
                "rejected_count": 0,
            },
        ),
        run(
            "demo-run-order-success-2",
            order,
            "succeeded",
            150,
            18,
            summary={
                "demo_data": True,
                "source_name": "orders-afternoon.csv",
                "total_orders": 40,
                "imported_count": 40,
                "rejected_count": 0,
            },
        ),
        run(
            "demo-run-order-partial-1",
            order,
            "partially_succeeded",
            75,
            20,
            summary={
                "demo_data": True,
                "source_name": "orders-evening.csv",
                "total_orders": 20,
                "imported_count": 17,
                "rejected_count": 3,
            },
        ),
        run(
            "demo-run-order-failed-1",
            order,
            "failed",
            110,
            8,
            summary={
                "demo_data": True,
                "source_name": "orders-batch-1.csv",
                "total_orders": 30,
                "execution_error": "Simulated database timeout",
                "error_type": "TimeoutError",
            },
        ),
        run(
            "demo-run-order-retry-1",
            order,
            "failed",
            95,
            6,
            retry_of_run_id="demo-run-order-failed-1",
            summary={
                "demo_data": True,
                "execution_error": "Simulated retry failure",
                "error_type": "RuntimeError",
            },
        ),
        run(
            "demo-run-order-retry-2",
            order,
            "succeeded",
            80,
            10,
            retry_of_run_id="demo-run-order-retry-1",
            summary={
                "demo_data": True,
                "imported_count": 30,
                "rejected_count": 0,
            },
        ),
        run(
            "demo-run-order-running-1",
            order,
            "running",
            5,
            summary={"demo_data": True},
        ),
        run(
            "demo-run-order-pending-1",
            order,
            "pending",
            2,
            summary={"demo_data": True},
        ),
        run(
            "demo-run-feedback-success-1",
            feedback,
            "succeeded",
            45,
            35,
            summary={
                "demo_data": True,
                "reviews_analyzed": 120,
                "sentiment": "mostly_positive",
            },
        ),
        run(
            "demo-run-feedback-failed-1",
            feedback,
            "failed",
            60,
            14,
            summary={
                "demo_data": True,
                "execution_error": "Simulated model timeout",
                "error_type": "TimeoutError",
            },
        ),
        run(
            "demo-run-feedback-cancelled-1",
            feedback,
            "cancelled",
            180,
            3,
            summary={"demo_data": True},
        ),
        run(
            "demo-run-lead-success-1",
            lead,
            "succeeded",
            90,
            5,
            summary={
                "demo_data": True,
                "leads_processed": 18,
            },
        ),
    ]


def seed_related_demo_data(
    connection,
    demo_runs: list[dict[str, Any]],
) -> None:
    """Seed related demo records without duplicating them on reruns."""
    run_by_id = {run["id"]: run for run in demo_runs}

    def run_time(run_id: str, offset_seconds: int = 2) -> str:
        created_at = datetime.fromisoformat(run_by_id[run_id]["created_at"])
        return (created_at + timedelta(seconds=offset_seconds)).isoformat()

    today = datetime.now(timezone.utc).date().isoformat()

    # Orders: imported and failed examples.
    # Rejected orders are represented by import items and run events;
    # the order service does not insert invalid orders into orders.
    orders = [
        {
            "source_name": "demo-orders-morning.csv",
            "external_order_id": "DEMO-ORD-001",
            "customer_reference": "DEMO-CUSTOMER-001",
            "amount": "149.99",
            "currency": "USD",
            "order_date": today,
            "run_id": "demo-run-order-success-1",
            "status": "imported",
            "validation_errors": None,
        },
        {
            "source_name": "demo-orders-morning.csv",
            "external_order_id": "DEMO-ORD-002",
            "customer_reference": "DEMO-CUSTOMER-002",
            "amount": "89.50",
            "currency": "USD",
            "order_date": today,
            "run_id": "demo-run-order-success-1",
            "status": "imported",
            "validation_errors": None,
        },
        {
            "source_name": "demo-orders-evening.csv",
            "external_order_id": "DEMO-ORD-003",
            "customer_reference": "DEMO-CUSTOMER-003",
            "amount": "220.00",
            "currency": "USD",
            "order_date": today,
            "run_id": "demo-run-order-partial-1",
            "status": "imported",
            "validation_errors": None,
        },
        {
            "source_name": "demo-orders-failed.csv",
            "external_order_id": "DEMO-ORD-005",
            "customer_reference": "DEMO-CUSTOMER-005",
            "amount": "75.00",
            "currency": "USD",
            "order_date": today,
            "run_id": "demo-run-order-failed-1",
            "status": "failed",
            "validation_errors": json.dumps(
                {
                    "demo_data": True,
                    "error": "Simulated database timeout",
                }
            ),
        },
    ]

    for order in orders:
        now = run_time(order["run_id"])

        connection.execute(
            """
            INSERT INTO orders (
                source_name,
                external_order_id,
                customer_reference,
                amount,
                currency,
                order_date,
                run_id,
                status,
                validation_errors,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(source_name, external_order_id)
            DO UPDATE SET
                customer_reference = excluded.customer_reference,
                amount = excluded.amount,
                currency = excluded.currency,
                order_date = excluded.order_date,
                run_id = excluded.run_id,
                status = excluded.status,
                validation_errors = excluded.validation_errors,
                updated_at = excluded.updated_at
            """,
            (
                order["source_name"],
                order["external_order_id"],
                order["customer_reference"],
                order["amount"],
                order["currency"],
                order["order_date"],
                order["run_id"],
                order["status"],
                order["validation_errors"],
                now,
                now,
            ),
        )

    # Saved order inputs include imported, rejected, and pending examples.
    import_items = [
        (
            "demo-item-order-001",
            "demo-run-order-success-1",
            "demo-orders-morning.csv",
            "DEMO-ORD-001",
            {
                "external_order_id": "DEMO-ORD-001",
                "customer_reference": "DEMO-CUSTOMER-001",
                "amount": "149.99",
                "currency": "USD",
                "order_date": today,
            },
            "imported",
        ),
        (
            "demo-item-order-002",
            "demo-run-order-success-1",
            "demo-orders-morning.csv",
            "DEMO-ORD-002",
            {
                "external_order_id": "DEMO-ORD-002",
                "customer_reference": "DEMO-CUSTOMER-002",
                "amount": "89.50",
                "currency": "USD",
                "order_date": today,
            },
            "imported",
        ),
        (
            "demo-item-order-003",
            "demo-run-order-partial-1",
            "demo-orders-evening.csv",
            "DEMO-ORD-003",
            {
                "external_order_id": "DEMO-ORD-003",
                "customer_reference": "DEMO-CUSTOMER-003",
                "amount": "220.00",
                "currency": "USD",
                "order_date": today,
            },
            "imported",
        ),
        (
            "demo-item-order-004",
            "demo-run-order-partial-1",
            "demo-orders-evening.csv",
            "DEMO-ORD-004",
            {
                "external_order_id": "DEMO-ORD-004",
                "customer_reference": "",
                "amount": "-10",
                "currency": "USD",
                "order_date": today,
            },
            "rejected",
        ),
        (
            "demo-item-order-005",
            "demo-run-order-failed-1",
            "orders-batch-1.csv",
            "DEMO-ORD-005",
            {
                "external_order_id": "DEMO-ORD-005",
                "customer_reference": "DEMO-CUSTOMER-005",
                "amount": "75.00",
                "currency": "USD",
                "order_date": today,
            },
            "pending",
        ),
        (
            "demo-item-order-006",
            "demo-run-order-retry-1",
            "orders-batch-1.csv",
            "DEMO-ORD-006",
            {
                "external_order_id": "DEMO-ORD-006",
                "customer_reference": "DEMO-CUSTOMER-006",
                "amount": "45.00",
                "currency": "USD",
                "order_date": today,
            },
            "rejected",
        ),
    ]

    for (
        item_id,
        run_id,
        source_name,
        external_order_id,
        payload,
        status,
    ) in import_items:
        connection.execute(
            """
            INSERT INTO order_import_items (
                id,
                run_id,
                source_name,
                external_order_id,
                payload,
                status,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                run_id = excluded.run_id,
                source_name = excluded.source_name,
                external_order_id = excluded.external_order_id,
                payload = excluded.payload,
                status = excluded.status,
                created_at = excluded.created_at
            """,
            (
                item_id,
                run_id,
                source_name,
                external_order_id,
                json.dumps(payload),
                status,
                run_time(run_id),
            ),
        )

    # Historical retry approvals. The approved example is already linked
    # to a retry run; it must not be interpreted as a new retry request.
    approvals = [
        (
            "demo-approval-pending",
            "demo-run-order-failed-1",
            "retry_workflow",
            "pending",
            run_time("demo-run-order-failed-1", 3),
            None,
            None,
        ),
        (
            "demo-approval-approved",
            "demo-run-order-failed-1",
            "retry_workflow",
            "approved",
            run_time("demo-run-order-failed-1", 3),
            run_time("demo-run-order-failed-1", 4),
            "demo-run-order-retry-1",
        ),
        (
            "demo-approval-rejected",
            "demo-run-order-retry-1",
            "retry_workflow",
            "rejected",
            run_time("demo-run-order-retry-1", 3),
            run_time("demo-run-order-retry-1", 4),
            None,
        ),
        (
            "demo-approval-expired",
            "demo-run-order-retry-1",
            "retry_workflow",
            "expired",
            run_time("demo-run-order-retry-1", 3),
            run_time("demo-run-order-retry-1", 4),
            None,
        ),
    ]

    connection.executemany(
        """
        INSERT INTO approvals (
            id, run_id, action, status,
            created_at, decided_at, retry_run_id
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            run_id = excluded.run_id,
            action = excluded.action,
            status = excluded.status,
            created_at = excluded.created_at,
            decided_at = excluded.decided_at,
            retry_run_id = excluded.retry_run_id
        """,
        approvals,
    )

    # Refresh only events explicitly marked as demo records.
    # Existing non-demo operational and audit history is preserved.
    connection.execute("""
        DELETE FROM run_events
        WHERE json_extract(details, '$.demo_data') = 1
        """)
    connection.execute("""
        DELETE FROM audit_events
        WHERE json_extract(details, '$.demo_data') = 1
        """)

    run_events = [
        (
            "demo-run-order-success-1",
            "order_import_started",
            "info",
            "Demo order import started.",
            {"demo_data": True, "source_name": "demo-orders-morning.csv"},
        ),
        (
            "demo-run-order-success-1",
            "order_import_completed",
            "info",
            "Demo order import completed successfully.",
            {"demo_data": True, "imported_count": 2},
        ),
        (
            "demo-run-order-partial-1",
            "order_rejected",
            "warning",
            "A demo order failed validation.",
            {"demo_data": True, "external_order_id": "DEMO-ORD-004"},
        ),
        (
            "demo-run-order-failed-1",
            "execution_failed",
            "error",
            "Demo import failed because of a simulated timeout.",
            {"demo_data": True, "error_type": "TimeoutError"},
        ),
        (
            "demo-run-order-retry-1",
            "execution_failed",
            "error",
            "Demo retry failed.",
            {"demo_data": True, "error_type": "RuntimeError"},
        ),
        (
            "demo-run-feedback-success-1",
            "analysis_completed",
            "info",
            "Demo feedback analysis completed.",
            {"demo_data": True, "reviews_analyzed": 120},
        ),
        (
            "demo-run-feedback-failed-1",
            "execution_failed",
            "error",
            "Demo feedback analysis timed out.",
            {"demo_data": True, "error_type": "TimeoutError"},
        ),
    ]

    for run_id, event_type, severity, message, details in run_events:
        connection.execute(
            """
            INSERT INTO run_events (
                run_id, event_type, severity, message, details, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                event_type,
                severity,
                message,
                json.dumps(details),
                run_time(run_id, 5),
            ),
        )

    audit_events = [
        (
            "demo_operator",
            "retry_approval_requested",
            "demo-approval-pending",
            "success",
            {
                "demo_data": True,
                "run_id": "demo-run-order-failed-1",
            },
            "demo-run-order-failed-1",
        ),
        (
            "demo_operator",
            "retry_approval_requested",
            "demo-approval-approved",
            "success",
            {
                "demo_data": True,
                "run_id": "demo-run-order-failed-1",
            },
            "demo-run-order-failed-1",
        ),
        (
            "demo_operator",
            "retry_approval_decided",
            "demo-approval-approved",
            "success",
            {"demo_data": True, "decision": "approved"},
            "demo-run-order-failed-1",
        ),
        (
            "demo_operator",
            "retry_started",
            "demo-run-order-retry-1",
            "success",
            {
                "demo_data": True,
                "approval_id": "demo-approval-approved",
            },
            "demo-run-order-retry-1",
        ),
        (
            "demo_operator",
            "retry_approval_requested",
            "demo-approval-rejected",
            "success",
            {
                "demo_data": True,
                "run_id": "demo-run-order-retry-1",
            },
            "demo-run-order-retry-1",
        ),
        (
            "demo_operator",
            "retry_approval_decided",
            "demo-approval-rejected",
            "success",
            {"demo_data": True, "decision": "rejected"},
            "demo-run-order-retry-1",
        ),
        (
            "demo_system",
            "retry_approval_expired",
            "demo-approval-expired",
            "success",
            {
                "demo_data": True,
                "run_id": "demo-run-order-retry-1",
            },
            "demo-run-order-retry-1",
        ),
    ]

    for actor, action, target_id, outcome, details, run_id in audit_events:
        connection.execute(
            """
            INSERT INTO audit_events (
                actor, action, target_id, outcome, details, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                actor,
                action,
                target_id,
                outcome,
                json.dumps(details),
                run_time(run_id, 6),
            ),
        )


def seed_demo_data() -> None:
    demo_runs = build_demo_runs()

    with get_connection() as connection:
        existing_tables = {row[0] for row in connection.execute("""
                SELECT name
                FROM sqlite_master
                WHERE type = 'table'
                """).fetchall()}

        missing_tables = REQUIRED_TABLES - existing_tables

        if missing_tables:
            raise RuntimeError(
                "Database is not initialized or is missing required tables: "
                + ", ".join(sorted(missing_tables))
            )

        for workflow in DEMO_WORKFLOWS:
            connection.execute(
                """
                INSERT INTO workflows (
                    id, name, description, enabled, created_at
                )
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    name = excluded.name,
                    description = excluded.description,
                    enabled = excluded.enabled
                """,
                (
                    workflow["id"],
                    workflow["name"],
                    workflow["description"],
                    workflow["enabled"],
                    timestamp_ago(24 * 60),
                ),
            )

        for item in demo_runs:
            connection.execute(
                """
                INSERT INTO workflow_runs (
                    id,
                    workflow_id,
                    status,
                    started_at,
                    finished_at,
                    summary,
                    retry_of_run_id,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    workflow_id = excluded.workflow_id,
                    status = excluded.status,
                    started_at = excluded.started_at,
                    finished_at = excluded.finished_at,
                    summary = excluded.summary,
                    retry_of_run_id = excluded.retry_of_run_id,
                    created_at = excluded.created_at
                """,
                (
                    item["id"],
                    item["workflow_id"],
                    item["status"],
                    item["started_at"],
                    item["finished_at"],
                    item["summary"],
                    item["retry_of_run_id"],
                    item["created_at"],
                ),
            )

        seed_related_demo_data(connection, demo_runs)

    print("Demo data seeded successfully.")
    print(f"Workflows: {len(DEMO_WORKFLOWS)}")
    print(f"Workflow runs: {len(demo_runs)}")


if __name__ == "__main__":
    seed_demo_data()
