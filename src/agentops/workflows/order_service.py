
import sqlite3
from datetime import datetime, timezone
from typing import Any

from agentops.database.connection import get_connection
from agentops.database.order_import_items import (
    update_order_import_item_status,
)
from agentops.database.run_events import record_run_event
from agentops.workflows.order_validation import validate_order


def process_order(
    order: dict[str, Any],
    source_name: str,
    run_id: str,
    item_id: str | None = None,
) -> dict[str, Any]:
    with get_connection() as connection:
        validation_errors = validate_order(order)

        if validation_errors:
            record_run_event(
                run_id=run_id,
                event_type="order_rejected",
                severity="warning",
                message="Order rejected because validation failed.",
                details={
                    "order_id": order.get("external_order_id"),
                    "validation_errors": validation_errors,
                },
                connection=connection,
            )

            if item_id is not None:
                update_order_import_item_status(
                    item_id,
                    "rejected",
                    connection=connection,
                )

            return {
                "status": "rejected",
                "external_order_id": order.get("external_order_id"),
                "errors": validation_errors,
            }

        now = datetime.now(timezone.utc).isoformat()

        # Keep the order, event, and import-item status in one transaction.
        # The savepoint allows an expected duplicate to be handled safely.
        connection.execute("BEGIN")
        connection.execute("SAVEPOINT order_insert")

        try:
            cursor = connection.execute(
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
                ON CONFLICT(source_name, external_order_id) DO NOTHING
                """,
                (
                    source_name,
                    order["external_order_id"],
                    order["customer_reference"],
                    str(order["amount"]),
                    order["currency"].upper(),
                    order["order_date"],
                    run_id,
                    "imported",
                    None,
                    now,
                    now,
                ),
            )

        except sqlite3.IntegrityError:
            # Unexpected integrity failures must propagate.
            # The connection context will roll back the transaction.
            raise

        if cursor.rowcount == 0:
            # The targeted unique constraint detected a duplicate order.
            connection.execute("ROLLBACK TO SAVEPOINT order_insert")
            connection.execute("RELEASE SAVEPOINT order_insert")

            errors = [
                "Order already exists for this source."
            ]

            record_run_event(
                run_id=run_id,
                event_type="order_rejected",
                severity="warning",
                message="Order rejected because it already exists.",
                details={
                    "order_id": order.get("external_order_id"),
                    "validation_errors": errors,
                },
                connection=connection,
            )

            if item_id is not None:
                update_order_import_item_status(
                    item_id,
                    "rejected",
                    connection=connection,
                )

            return {
                "status": "rejected",
                "external_order_id": order.get("external_order_id"),
                "errors": errors,
            }

        connection.execute("RELEASE SAVEPOINT order_insert")

        record_run_event(
            run_id=run_id,
            event_type="order_imported",
            severity="info",
            message="Order imported successfully.",
            details={
                "order_id": order["external_order_id"],
            },
            connection=connection,
        )

        if item_id is not None:
            update_order_import_item_status(
                item_id,
                "imported",
                connection=connection,
            )

        return {
            "status": "imported",
            "external_order_id": order["external_order_id"],
            "errors": [],
        }
