import json
import sqlite3
from datetime import datetime, timezone
from typing import Any

from agentops.database.connection import get_connection


def record_audit_event(
    actor: str,
    action: str,
    target_id: str | None,
    outcome: str,
    details: dict[str, Any] | None = None,
    connection: sqlite3.Connection | None = None,
) -> None:
    """Record a consequential action in the audit log."""
    now = datetime.now(timezone.utc).isoformat()

    details_json = json.dumps(details) if details is not None else None

    def insert_event(conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            INSERT INTO audit_events (
                actor,
                action,
                target_id,
                outcome,
                details,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                actor,
                action,
                target_id,
                outcome,
                details_json,
                now,
            ),
        )

    if connection is not None:
        # The caller owns this connection and its transaction.
        insert_event(connection)
    else:
        # Use the connection context manager when no connection is supplied.
        with get_connection() as conn:
            insert_event(conn)
