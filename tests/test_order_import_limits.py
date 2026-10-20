
import json

import pytest

from agentops.database import (
    connection,
    init_db,
    workflow_registry,
    workflow_runs,
)
from agentops.workflows import order_import


@pytest.fixture
def test_db(tmp_path, monkeypatch):
    database_path = tmp_path / "test_agentops_limits.db"

    monkeypatch.setattr(
        connection,
        "DATABASE_PATH",
        database_path,
    )

    temporary_connection = lambda: connection.get_connection(database_path)

    for module in (
        init_db,
        workflow_registry,
        workflow_runs,
        order_import,
    ):
        monkeypatch.setattr(
            module,
            "get_connection",
            temporary_connection,
        )

    init_db.initialize_database()

    workflow_id = workflow_registry.register_workflow(
        "Order Import Limits",
        "Tests order-import validation boundaries.",
    )

    return database_path, workflow_id


def valid_order(order_id="ORD-LIMIT-001"):
    return {
        "external_order_id": order_id,
        "customer_reference": "CUST-LIMIT-001",
        "amount": "25.50",
        "currency": "USD",
        "order_date": "2026-10-17",
    }


def count_runs(database_path):
    with connection.get_connection(database_path) as conn:
        return conn.execute(
            "SELECT COUNT(*) FROM workflow_runs"
        ).fetchone()[0]


def test_none_orders_preserves_validation_error_and_fails_run(test_db):
    database_path, workflow_id = test_db

    run_id = workflow_runs.create_run(workflow_id)
    workflow_runs.update_run_status(run_id, "running")

    with pytest.raises(
        ValueError,
        match="Orders must be provided as a list",
    ):
        order_import.process_orders_in_run(
            None,
            "test-source",
            run_id,
        )

    run = workflow_runs.get_run(run_id)

    assert run is not None
    assert run["status"] == "failed"

    summary = json.loads(run["summary"])
    assert summary["execution_error"] == (
        "Orders must be provided as a list."
    )
    assert summary["error_type"] == "ValueError"
    assert summary["total_orders"] == 0

    with connection.get_connection(database_path) as conn:
        item_count = conn.execute(
            "SELECT COUNT(*) FROM order_import_items WHERE run_id = ?",
            (run_id,),
        ).fetchone()[0]

        order_count = conn.execute(
            "SELECT COUNT(*) FROM orders WHERE run_id = ?",
            (run_id,),
        ).fetchone()[0]

    assert item_count == 0
    assert order_count == 0


def test_source_name_at_maximum_length_is_accepted(test_db):
    _, workflow_id = test_db
    source_name = "s" * order_import.MAX_SOURCE_NAME_LENGTH

    result = order_import.execute_order_import(
        [valid_order()],
        source_name,
        workflow_id,
    )

    assert result["status"] == "succeeded"


def test_source_name_over_limit_is_rejected_before_run_creation(test_db):
    database_path, workflow_id = test_db
    source_name = "s" * (order_import.MAX_SOURCE_NAME_LENGTH + 1)

    with pytest.raises(ValueError, match="Source name cannot exceed"):
        order_import.execute_order_import(
            [valid_order()],
            source_name,
            workflow_id,
        )

    assert count_runs(database_path) == 0


def test_maximum_order_count_is_accepted(test_db):
    _, workflow_id = test_db
    orders = [
        valid_order(f"ORD-LIMIT-{index:04d}")
        for index in range(order_import.MAX_ORDERS_PER_IMPORT)
    ]

    result = order_import.execute_order_import(
        orders,
        "test-source",
        workflow_id,
    )

    assert result["status"] == "succeeded"
    assert result["imported_count"] == order_import.MAX_ORDERS_PER_IMPORT


def test_order_count_over_limit_is_rejected_before_run_creation(test_db):
    database_path, workflow_id = test_db
    orders = [
        valid_order(f"ORD-OVER-LIMIT-{index:04d}")
        for index in range(order_import.MAX_ORDERS_PER_IMPORT + 1)
    ]

    with pytest.raises(ValueError, match="cannot contain more than"):
        order_import.execute_order_import(
            orders,
            "test-source",
            workflow_id,
        )

    assert count_runs(database_path) == 0


def test_payload_at_maximum_size_is_accepted(test_db):
    _, workflow_id = test_db

    order = valid_order()
    # Add a string field until the serialized UTF-8 JSON payload is exactly
    # the allowed number of bytes. ASCII padding makes byte length predictable.
    order["padding"] = ""
    base_size = len(json.dumps(order, ensure_ascii=False).encode("utf-8"))
    order["padding"] = "x" * (
        order_import.MAX_ORDER_PAYLOAD_BYTES - base_size
    )

    assert len(json.dumps(order, ensure_ascii=False).encode("utf-8")) == (
        order_import.MAX_ORDER_PAYLOAD_BYTES
    )

    result = order_import.execute_order_import(
        [order],
        "test-source",
        workflow_id,
    )

    assert result["status"] == "succeeded"


def test_payload_over_maximum_size_is_rejected_before_run_creation(test_db):
    database_path, workflow_id = test_db

    order = valid_order()
    order["padding"] = "x" * order_import.MAX_ORDER_PAYLOAD_BYTES

    with pytest.raises(ValueError, match="exceeds the maximum payload size"):
        order_import.execute_order_import(
            [order],
            "test-source",
            workflow_id,
        )

    assert count_runs(database_path) == 0
