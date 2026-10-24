from datetime import datetime, timedelta, timezone
from typing import Any

from agentops.database.connection import get_connection


def get_workflow_health(
    window_hours: int = 24,
) -> list[dict[str, Any]]:
    """Return workflow health metrics for a rolling time window."""
    if type(window_hours) is not int or window_hours < 1:
        raise ValueError("window_hours must be a positive integer.")

    now = datetime.now(timezone.utc)
    window_start = (now - timedelta(hours=window_hours)).isoformat()

    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT
                w.id AS workflow_id,
                w.name AS workflow_name,
                w.enabled AS workflow_enabled,

                COUNT(r.id) AS total_runs,

                SUM(CASE WHEN r.status = 'pending'
                    THEN 1 ELSE 0 END) AS pending_runs,

                SUM(CASE WHEN r.status = 'running'
                    THEN 1 ELSE 0 END) AS running_runs,

                SUM(CASE WHEN r.status = 'succeeded'
                    THEN 1 ELSE 0 END) AS succeeded_runs,

                SUM(CASE WHEN r.status = 'partially_succeeded'
                    THEN 1 ELSE 0 END) AS partially_succeeded_runs,

                SUM(CASE WHEN r.status = 'failed'
                    THEN 1 ELSE 0 END) AS failed_runs,

                SUM(CASE WHEN r.status = 'cancelled'
                    THEN 1 ELSE 0 END) AS cancelled_runs,

                AVG(
                    CASE
                        WHEN r.started_at IS NOT NULL
                         AND r.finished_at IS NOT NULL
                         AND julianday(r.finished_at)
                             >= julianday(r.started_at)
                        THEN
                            (julianday(r.finished_at)
                             - julianday(r.started_at)) * 86400.0
                        ELSE NULL
                    END
                ) AS average_duration_seconds

            FROM workflows AS w
            LEFT JOIN workflow_runs AS r
                ON r.workflow_id = w.id
                AND r.created_at >= ?

            GROUP BY w.id, w.name, w.enabled
            ORDER BY w.name
            """,
            (window_start,),
        ).fetchall()

    health_results = []

    for row in rows:
        result = dict(row)

        # SQLite SUM returns NULL when a workflow has no runs.
        count_fields = [
            "total_runs",
            "pending_runs",
            "running_runs",
            "succeeded_runs",
            "partially_succeeded_runs",
            "failed_runs",
            "cancelled_runs",
        ]

        for field in count_fields:
            result[field] = result[field] or 0

        completed_runs = (
            result["succeeded_runs"]
            + result["partially_succeeded_runs"]
            + result["failed_runs"]
            + result["cancelled_runs"]
        )

        successful_runs = result["succeeded_runs"] + result["partially_succeeded_runs"]

        result["success_rate"] = (
            round(successful_runs / completed_runs * 100, 2) if completed_runs else None
        )

        result["has_repeated_failures"] = result["failed_runs"] >= 2

        average_duration = result["average_duration_seconds"]
        result["average_duration_seconds"] = (
            round(average_duration, 2) if average_duration is not None else None
        )

        health_results.append(result)

    return health_results


def get_stale_runs(stale_after_minutes: int = 30) -> list[dict[str, Any]]:
    """Return running workflow runs that exceed the stale-age threshold.

    This is a read-only diagnostic. It does not change run statuses
    and cannot determine whether a worker is genuinely still active.
    """
    if type(stale_after_minutes) is not int or stale_after_minutes < 1:
        raise ValueError("stale_after_minutes must be a positive integer.")

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(minutes=stale_after_minutes)

    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT
                r.id AS run_id,
                r.workflow_id,
                w.name AS workflow_name,
                r.status,
                r.started_at,
                r.created_at,
                r.retry_of_run_id
            FROM workflow_runs AS r
            JOIN workflows AS w
                ON w.id = r.workflow_id
            WHERE r.status = 'running'
              AND r.started_at IS NOT NULL
              AND julianday(r.started_at) <= julianday(?)
            ORDER BY julianday(r.started_at) ASC, r.id ASC
            """,
            (cutoff.isoformat(),),
        ).fetchall()

    stale_runs = []

    for row in rows:
        result = dict(row)
        started_at = datetime.fromisoformat(result["started_at"])

        if started_at.tzinfo is None:
            started_at = started_at.replace(tzinfo=timezone.utc)

        duration_minutes = (
            now - started_at.astimezone(timezone.utc)
        ).total_seconds() / 60

        result["running_duration_minutes"] = round(
            max(0.0, duration_minutes), 2
        )
        result["stale_after_minutes"] = stale_after_minutes
        result["diagnostic_status"] = "potentially_stale"

        stale_runs.append(result)

    return stale_runs
