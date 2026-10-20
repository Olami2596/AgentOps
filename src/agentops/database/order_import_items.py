import json
import sqlite3
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from agentops.database.connection import get_connection

VALID_ITEM_STATUSES = {"pending", "imported", "rejected"}


def save_order_import_items(
    run_id: str,
    source_name: str,
    orders: list[dict[str, Any]],
) -> list[str]:
    now = datetime.now(timezone.utc).isoformat()
    items = []

    for order in orders:
        item_id = str(uuid4())
        external_order_id = order.get("external_order_id")
        payload = json.dumps(order)

        items.append(
            (
                item_id,
                run_id,
                source_name,
                external_order_id,
                payload,
                "pending",
                now,
            )
        )

    with get_connection() as connection:
        connection.executemany(
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
            """,
            items,
        )

    return [item[0] for item in items]


def update_order_import_item_status(
    item_id: str,
    status: str,
    connection: sqlite3.Connection | None = None,
) -> None:
    if status not in VALID_ITEM_STATUSES:
        raise ValueError(f"Invalid order import item status: {status!r}.")

    def update_status(conn: sqlite3.Connection) -> None:
        cursor = conn.execute(
            """
            UPDATE order_import_items
            SET status = ?
            WHERE id = ?
            """,
            (status, item_id),
        )

        if cursor.rowcount == 0:
            raise LookupError(f"Order import item {item_id!r} does not exist.")

    if connection is not None:
        # The caller owns this connection and its transaction.
        update_status(connection)
    else:
        # Preserve existing behavior for callers without a connection.
        with get_connection() as conn:
            update_status(conn)
