
import pytest
from datetime import datetime, timedelta, timezone

from agentops.database import connection, init_db, workflow_registry
from agentops.database import workflow_health


@pytest.fixture
def test_db(tmp_path, monkeypatch):
    database_path = tmp_path / "test_agentops.db"

    monkeypatch.setattr(
        connection,
        "DATABASE_PATH",
        database_path,
    )

    temporary_connection = lambda: connection.get_connection(
        database_path
    )

    monkeypatch.setattr(
        init_db,
        "get_connection",
        temporary_connection,
    )
    monkeypatch.setattr(
        workflow_registry,
        "get_connection",
        temporary_connection,
    )
    monkeypatch.setattr(
        workflow_health,
        "get_connection",
        temporary_connection,
    )

    init_db.initialize_database()

    workflow_id = workflow_registry.register_workflow(
        "Test Workflow",
        "A workflow used for health monitoring tests.",
    )

    return database_path, workflow_id


def insert_run(
    database_path,
    workflow_id,
    run_id,
    status,
    *,
    minutes_ago=10,
    duration_seconds=None,
):
    created_at = (
        datetime.now(timezone.utc)
        - timedelta(minutes=minutes_ago)
    )

    started_at = None
    finished_at = None

    if status != "pending":
        started_at = created_at + timedelta(seconds=2)

    if duration_seconds is not None:
        assert started_at is not None
        finished_at = started_at + timedelta(
            seconds=duration_seconds
        )

    with connection.get_connection(database_path) as conn:
        conn.execute(
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
            VALUES (?, ?, ?, ?, ?, ?, NULL, ?)
            """,
            (
                run_id,
                workflow_id,
                status,
                started_at.isoformat() if started_at else None,
                finished_at.isoformat() if finished_at else None,
                "{}",
                created_at.isoformat(),
            ),
        )


def test_workflow_without_runs_has_zero_counts_and_no_rates(test_db):
    _, workflow_id = test_db

    results = workflow_health.get_workflow_health()

    assert len(results) == 1

    result = results[0]

    assert result["workflow_id"] == workflow_id
    assert result["total_runs"] == 0
    assert result["pending_runs"] == 0
    assert result["running_runs"] == 0
    assert result["succeeded_runs"] == 0
    assert result["partially_succeeded_runs"] == 0
    assert result["failed_runs"] == 0
    assert result["cancelled_runs"] == 0
    assert result["success_rate"] is None
    assert result["average_duration_seconds"] is None
    assert result["has_repeated_failures"] is False


def test_health_metrics_count_mixed_statuses_and_calculate_success_rate(
    test_db,
):
    database_path, workflow_id = test_db

    runs = [
        ("run-success-1", "succeeded", 10),
        ("run-success-2", "succeeded", 20),
        ("run-partial", "partially_succeeded", 30),
        ("run-failed", "failed", 40),
        ("run-cancelled", "cancelled", 5),
        ("run-running", "running", None),
        ("run-pending", "pending", None),
    ]

    for run_id, status, duration in runs:
        insert_run(
            database_path,
            workflow_id,
            run_id,
            status,
            duration_seconds=duration,
        )

    results = workflow_health.get_workflow_health()
    result = results[0]

    assert result["total_runs"] == 7
    assert result["succeeded_runs"] == 2
    assert result["partially_succeeded_runs"] == 1
    assert result["failed_runs"] == 1
    assert result["cancelled_runs"] == 1
    assert result["running_runs"] == 1
    assert result["pending_runs"] == 1

    # Three successful outcomes among five terminal runs.
    assert result["success_rate"] == 60.0

    # Only runs with valid start and finish timestamps contribute.
    assert result["average_duration_seconds"] == pytest.approx(
        21.0,
        abs=0.1,
    )

    assert result["has_repeated_failures"] is False


def test_repeated_failures_are_detected(test_db):
    database_path, workflow_id = test_db

    for index in range(2):
        insert_run(
            database_path,
            workflow_id,
            f"run-failed-{index}",
            "failed",
        )

    result = workflow_health.get_workflow_health()[0]

    assert result["failed_runs"] == 2
    assert result["has_repeated_failures"] is True


def test_one_failure_does_not_trigger_repeated_failure_indicator(test_db):
    database_path, workflow_id = test_db

    insert_run(
        database_path,
        workflow_id,
        "run-failed",
        "failed",
    )

    result = workflow_health.get_workflow_health()[0]

    assert result["failed_runs"] == 1
    assert result["has_repeated_failures"] is False


def test_health_metrics_exclude_runs_outside_reporting_window(test_db):
    database_path, workflow_id = test_db

    insert_run(
        database_path,
        workflow_id,
        "recent-run",
        "succeeded",
        minutes_ago=30,
        duration_seconds=10,
    )

    insert_run(
        database_path,
        workflow_id,
        "old-run",
        "failed",
        minutes_ago=60 * 30,
        duration_seconds=20,
    )

    result = workflow_health.get_workflow_health(
        window_hours=24
    )[0]

    assert result["total_runs"] == 1
    assert result["succeeded_runs"] == 1
    assert result["failed_runs"] == 0
    assert result["success_rate"] == 100.0


@pytest.mark.parametrize(
    "window_hours",
    [0, -1, True, 1.5, "24", None],
)
def test_invalid_reporting_window_is_rejected(
    test_db,
    window_hours,
):
    with pytest.raises(
        ValueError,
        match="window_hours must be a positive integer",
    ):
        workflow_health.get_workflow_health(window_hours)


def test_stale_run_is_detected(test_db):
    database_path, workflow_id = test_db

    insert_run(
        database_path,
        workflow_id,
        "run-stale",
        "running",
        minutes_ago=60,
    )

    results = workflow_health.get_stale_runs(
        stale_after_minutes=30
    )

    assert len(results) == 1

    result = results[0]
    assert result["run_id"] == "run-stale"
    assert result["workflow_id"] == workflow_id
    assert result["workflow_name"] == "Test Workflow"
    assert result["status"] == "running"
    assert result["diagnostic_status"] == "potentially_stale"
    assert result["running_duration_minutes"] >= 30
    assert result["stale_after_minutes"] == 30


def test_recent_running_run_is_not_detected_as_stale(test_db):
    database_path, workflow_id = test_db

    insert_run(
        database_path,
        workflow_id,
        "run-recent",
        "running",
        minutes_ago=5,
    )

    assert workflow_health.get_stale_runs(
        stale_after_minutes=30
    ) == []


def test_stale_run_detection_excludes_terminal_and_pending_runs(
    test_db,
):
    database_path, workflow_id = test_db

    for run_id, status in [
        ("run-succeeded", "succeeded"),
        ("run-failed", "failed"),
        ("run-cancelled", "cancelled"),
        ("run-pending", "pending"),
    ]:
        insert_run(
            database_path,
            workflow_id,
            run_id,
            status,
            minutes_ago=120,
            duration_seconds=10 if status != "pending" else None,
        )

    assert workflow_health.get_stale_runs(
        stale_after_minutes=30
    ) == []


@pytest.mark.parametrize(
    "stale_after_minutes",
    [0, -1, True, 1.5, "30", None],
)
def test_invalid_stale_run_threshold_is_rejected(
    test_db,
    stale_after_minutes,
):
    with pytest.raises(
        ValueError,
        match="stale_after_minutes must be a positive integer",
    ):
        workflow_health.get_stale_runs(stale_after_minutes)


def test_stale_run_detection_does_not_modify_run_status(test_db):
    database_path, workflow_id = test_db

    insert_run(
        database_path,
        workflow_id,
        "run-stale",
        "running",
        minutes_ago=60,
    )

    workflow_health.get_stale_runs(stale_after_minutes=30)

    with connection.get_connection(database_path) as conn:
        row = conn.execute(
            """
            SELECT status
            FROM workflow_runs
            WHERE id = ?
            """,
            ("run-stale",),
        ).fetchone()

    assert row is not None
    assert row["status"] == "running"
