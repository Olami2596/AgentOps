import json
import sqlite3
from datetime import datetime, timezone
from typing import Any

from agentops.database.connection import get_connection


def record_run_event(
    run_id: str,
    event_type: str,
    severity: str,
    message: str,
    details: dict[str, Any] | None = None,
    connection: sqlite3.Connection | None = None,
) -> None:
    now = datetime.now(timezone.utc).isoformat()

    details_json = json.dumps(details) if details is not None else None

    def insert_event(conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            INSERT INTO run_events (
                run_id,
                event_type,
                severity,
                message,
                details,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                event_type,
                severity,
                message,
                details_json,
                now,
            ),
        )

    if connection is not None:
        # The caller owns the supplied connection and its transaction.
        insert_event(connection)
    else:
        # Preserve the existing behavior when no connection is supplied.
        with get_connection() as conn:
            insert_event(conn)
