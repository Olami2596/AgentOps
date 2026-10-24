import json
import pytest
import logging

from agentops.database import (
    connection,
    init_db,
    workflow_registry,
    workflow_runs,
    run_events,
    order_import_items,
)
from agentops.workflows import order_service, order_import
from agentops.database.workflow_runs import get_run


@pytest.fixture
def test_db(tmp_path, monkeypatch):
    database_path = tmp_path / "test_agentops.db"

    monkeypatch.setattr(
        connection,
        "DATABASE_PATH",
        database_path,
    )

    temporary_connection = lambda: connection.get_connection(database_path)

    modules_to_patch = [
        init_db,
        workflow_registry,
        workflow_runs,
        run_events,
        order_import_items,
        order_service,
        order_import,
    ]

    for module in modules_to_patch:
        monkeypatch.setattr(
            module,
            "get_connection",
            temporary_connection,
        )

    init_db.initialize_database()

    workflow_id = workflow_registry.register_workflow(
        "Order Import",
        "Imports and validates orders.",
    )

    return database_path, workflow_id


def valid_order(order_id="ORD-001"):
    return {
        "external_order_id": order_id,
        "customer_reference": "CUST-001",
        "amount": "25.50",
        "currency": "USD",
        "order_date": "2026-10-17",
    }


def get_run_record(database_path, run_id):
    with connection.get_connection(database_path) as conn:
        row = conn.execute(
            """
            SELECT id, workflow_id, status, summary,
                   started_at, finished_at
            FROM workflow_runs
            WHERE id = ?
            """,
            (run_id,),
        ).fetchone()

    return dict(row) if row is not None else None


def test_all_valid_orders_produce_succeeded_run(test_db):
    database_path, workflow_id = test_db

    result = order_import.execute_order_import(
        [
            valid_order("ORD-001"),
            valid_order("ORD-002"),
        ],
        "shop-test",
        workflow_id,
    )

    assert result["status"] == "succeeded"
    assert result["imported_count"] == 2
    assert result["rejected_count"] == 0
    assert len(result["results"]) == 2

    run = get_run_record(database_path, result["run_id"])

    assert run["status"] == "succeeded"
    assert run["started_at"] is not None
    assert run["finished_at"] is not None


def test_mixed_orders_produce_partially_succeeded_run(test_db):
    database_path, workflow_id = test_db

    invalid_order = valid_order("ORD-002")
    invalid_order["amount"] = "-10"

    result = order_import.execute_order_import(
        [
            valid_order("ORD-001"),
            invalid_order,
        ],
        "shop-test",
        workflow_id,
    )

    assert result["status"] == "partially_succeeded"
    assert result["imported_count"] == 1
    assert result["rejected_count"] == 1
    assert len(result["results"]) == 2

    run = get_run_record(database_path, result["run_id"])

    assert run["status"] == "partially_succeeded"
    assert run["finished_at"] is not None


def test_all_invalid_orders_produce_failed_run(test_db):
    database_path, workflow_id = test_db

    first_invalid_order = valid_order("ORD-001")
    first_invalid_order["amount"] = "-10"

    second_invalid_order = valid_order("ORD-002")
    second_invalid_order["currency"] = "US"

    result = order_import.execute_order_import(
        [first_invalid_order, second_invalid_order],
        "shop-test",
        workflow_id,
    )

    assert result["status"] == "failed"
    assert result["imported_count"] == 0
    assert result["rejected_count"] == 2

    run = get_run_record(database_path, result["run_id"])

    assert run["status"] == "failed"
    assert run["finished_at"] is not None


def test_final_summary_and_counts_are_correct(test_db):
    database_path, workflow_id = test_db

    invalid_order = valid_order("ORD-002")
    invalid_order["amount"] = "-5"

    result = order_import.execute_order_import(
        [
            valid_order("ORD-001"),
            invalid_order,
        ],
        "shop-test",
        workflow_id,
    )

    run = get_run_record(database_path, result["run_id"])
    stored_summary = json.loads(run["summary"])

    expected_summary = {
        "source_name": "shop-test",
        "total_orders": 2,
        "imported_count": 1,
        "rejected_count": 1,
    }

    assert stored_summary == expected_summary
    assert result["summary"] == expected_summary
    assert result["imported_count"] == 1
    assert result["rejected_count"] == 1


def test_original_order_inputs_are_preserved_with_correct_statuses(
    test_db,
):
    database_path, workflow_id = test_db

    imported_order = valid_order("ORD-001")

    rejected_order = valid_order("ORD-002")
    rejected_order["amount"] = "-10"

    result = order_import.execute_order_import(
        [imported_order, rejected_order],
        "shop-test",
        workflow_id,
    )

    with connection.get_connection(database_path) as conn:
        rows = conn.execute(
            """
            SELECT
                run_id,
                source_name,
                external_order_id,
                payload,
                status
            FROM order_import_items
            WHERE run_id = ?
            ORDER BY rowid
            """,
            (result["run_id"],),
        ).fetchall()

    assert len(rows) == 2

    items_by_order_id = {row["external_order_id"]: dict(row) for row in rows}

    imported_item = items_by_order_id["ORD-001"]
    rejected_item = items_by_order_id["ORD-002"]

    # Both original inputs belong to the same workflow run.
    assert imported_item["run_id"] == result["run_id"]
    assert rejected_item["run_id"] == result["run_id"]

    # The source name is preserved for both inputs.
    assert imported_item["source_name"] == "shop-test"
    assert rejected_item["source_name"] == "shop-test"

    # JSON round-tripping preserves each original input exactly.
    assert json.loads(imported_item["payload"]) == imported_order
    assert json.loads(rejected_item["payload"]) == rejected_order

    # The rejected payload retains the original invalid amount.
    assert json.loads(rejected_item["payload"])["amount"] == "-10"

    # Item statuses reflect their processing outcomes.
    assert imported_item["status"] == "imported"
    assert rejected_item["status"] == "rejected"


def test_empty_order_list_is_rejected(test_db):
    database_path, workflow_id = test_db

    with pytest.raises(ValueError, match="empty order list"):
        order_import.execute_order_import(
            [],
            "shop-test",
            workflow_id,
        )

    with connection.get_connection(database_path) as conn:
        run_count = conn.execute("SELECT COUNT(*) FROM workflow_runs").fetchone()[0]

    assert run_count == 0


def test_nonexistent_workflow_is_rejected(test_db):
    database_path, _ = test_db

    with pytest.raises(LookupError, match="does not exist"):
        order_import.execute_order_import(
            [valid_order()],
            "shop-test",
            "missing-workflow",
        )

    with connection.get_connection(database_path) as conn:
        run_count = conn.execute("SELECT COUNT(*) FROM workflow_runs").fetchone()[0]

    assert run_count == 0




def test_finalization_error_attempts_failure_recovery(
    test_db,
    monkeypatch,
    caplog,
):
    _, workflow_id = test_db

    original_update_run_status = order_import.update_run_status
    original_create_run = order_import.create_run

    attempted_statuses = []
    created_run_ids = []

    def capture_run_id(workflow_id):
        run_id = original_create_run(workflow_id)
        created_run_ids.append(run_id)
        return run_id

    def failing_finalization(run_id, status, summary=None):
        attempted_statuses.append(status)

        if status == "succeeded":
            raise RuntimeError("Finalization failed")

        return original_update_run_status(
            run_id,
            status,
            summary,
        )

    monkeypatch.setattr(
        order_import,
        "create_run",
        capture_run_id,
    )

    monkeypatch.setattr(
        order_import,
        "update_run_status",
        failing_finalization,
    )

    with caplog.at_level(
        logging.ERROR,
        logger="agentops.workflows.order_import",
    ):
        with pytest.raises(
            RuntimeError,
            match="Finalization failed",
        ):
            order_import.execute_order_import(
                [valid_order()],
                "shop-test",
                workflow_id,
            )

    assert attempted_statuses == [
        "running",
        "succeeded",
        "failed",
    ]

    assert len(created_run_ids) == 1

    run = get_run(created_run_ids[0])

    assert run is not None
    assert run["status"] == "failed"
    assert run["finished_at"] is not None

    summary = json.loads(run["summary"])
    assert summary["execution_error"] == "Finalization failed"

    finalization_logs = [
        record
        for record in caplog.records
        if record.name == "agentops.workflows.order_import"
        and record.getMessage().startswith(
            "Order import finalization failed"
        )
    ]

    assert len(finalization_logs) == 1

    record = finalization_logs[0]
    assert record.levelno == logging.ERROR
    assert created_run_ids[0] in record.getMessage()
    assert "RuntimeError" in record.getMessage()
    assert record.exc_info is not None
    assert record.exc_info[0] is RuntimeError


def test_disabled_workflow_cannot_be_executed(test_db):
    database_path, workflow_id = test_db

    # Disable the workflow.
    with connection.get_connection(database_path) as conn:
        conn.execute(
            "UPDATE workflows SET enabled = 0 WHERE id = ?",
            (workflow_id,),
        )

    # Execution should be rejected before a run is created.
    with pytest.raises(ValueError, match="disabled"):
        order_import.execute_order_import(
            [valid_order()],
            "shop-test",
            workflow_id,
        )

    # No run should have been created for the disabled workflow.
    with connection.get_connection(database_path) as conn:
        run_count = conn.execute(
            "SELECT COUNT(*) FROM workflow_runs WHERE workflow_id = ?",
            (workflow_id,),
        ).fetchone()[0]

        order_count = conn.execute(
            "SELECT COUNT(*) FROM orders",
        ).fetchone()[0]

    assert run_count == 0
    assert order_count == 0


def test_finalization_failure_preserves_original_exception(
    test_db,
    monkeypatch,
):
    _, workflow_id = test_db

    original_update_run_status = order_import.update_run_status
    attempted_statuses = []

    def failing_update_run_status(
        run_id,
        status,
        summary=None,
    ):
        attempted_statuses.append(status)

        if status == "running":
            return original_update_run_status(
                run_id,
                status,
                summary=summary,
            )

        if status == "succeeded":
            raise RuntimeError("Original finalization failure")

        if status == "failed":
            raise ValueError("Recovery finalization failure")

        return original_update_run_status(
            run_id,
            status,
            summary=summary,
        )

    monkeypatch.setattr(
        order_import,
        "update_run_status",
        failing_update_run_status,
    )

    with pytest.raises(
        RuntimeError,
        match="Original finalization failure",
    ) as exc_info:
        order_import.execute_order_import(
            [valid_order()],
            "shop-test",
            workflow_id,
        )

    assert attempted_statuses == [
        "running",
        "succeeded",
        "failed",
    ]

    notes = getattr(exc_info.value, "__notes__", [])
    assert any(
        "Recovery finalization failure" in note
        for note in notes
    )


def test_invalid_direct_processing_saves_no_items_or_orders(test_db):
    database_path, workflow_id = test_db

    run_id = order_import.create_run(workflow_id)
    order_import.update_run_status(run_id, "running")

    with pytest.raises(
        ValueError,
        match="Order at index 0 must be a dictionary",
    ):
        order_import.process_orders_in_run(
            [None],
            "test-source",
            run_id,
        )

    run = workflow_runs.get_run(run_id)
    assert run is not None
    assert run["status"] == "failed"

    with connection.get_connection(database_path) as conn:
        items = conn.execute(
            """
            SELECT id
            FROM order_import_items
            WHERE run_id = ?
            """,
            (run_id,),
        ).fetchall()

        orders = conn.execute(
            """
            SELECT id
            FROM orders
            WHERE run_id = ?
            """,
            (run_id,),
        ).fetchall()

    assert items == []
    assert orders == []


def test_processing_failure_is_logged_with_run_context(
    test_db,
    caplog,
    monkeypatch,
):
    _, workflow_id = test_db

    run_id = order_import.create_run(workflow_id)
    order_import.update_run_status(run_id, "running")

    def fail_processing(*args, **kwargs):
        raise RuntimeError("Simulated processing failure")

    monkeypatch.setattr(
        order_import,
        "process_order",
        fail_processing,
    )

    with caplog.at_level(
        logging.ERROR,
        logger="agentops.workflows.order_import",
    ):
        with pytest.raises(
            RuntimeError,
            match="Simulated processing failure",
        ):
            order_import.process_orders_in_run(
                [valid_order()],
                "test-source",
                run_id,
            )

    matching_records = [
        record
        for record in caplog.records
        if record.name == "agentops.workflows.order_import"
        and record.getMessage().startswith(
            "Order import processing failed"
        )
    ]

    assert len(matching_records) == 1

    record = matching_records[0]
    assert record.levelno == logging.ERROR
    assert run_id in record.getMessage()
    assert "RuntimeError" in record.getMessage()
    assert record.exc_info is not None
    assert record.exc_info[0] is RuntimeError

    run = get_run(run_id)

    assert run is not None
    assert run["status"] == "failed"
