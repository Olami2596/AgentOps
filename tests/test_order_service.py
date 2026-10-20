
import json
import sqlite3

import pytest

from agentops.database import (
    connection,
    init_db,
    workflow_registry,
    workflow_runs,
    run_events,
    order_import_items,
)
from agentops.workflows import order_service


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

    run_id = workflow_runs.create_run(workflow_id)

    return database_path, run_id


def valid_order(order_id="ORD-001"):
    return {
        "external_order_id": order_id,
        "customer_reference": "CUST-001",
        "amount": "25.50",
        "currency": "USD",
        "order_date": "2026-10-17",
    }


def get_order_count(database_path, external_order_id=None):
    with connection.get_connection(database_path) as conn:
        if external_order_id is None:
            row = conn.execute(
                "SELECT COUNT(*) AS count FROM orders"
            ).fetchone()
        else:
            row = conn.execute(
                """
                SELECT COUNT(*) AS count
                FROM orders
                WHERE external_order_id = ?
                """,
                (external_order_id,),
            ).fetchone()

    return row["count"]


def get_run_events(database_path, run_id):
    with connection.get_connection(database_path) as conn:
        rows = conn.execute(
            """
            SELECT event_type, severity, message, details
            FROM run_events
            WHERE run_id = ?
            ORDER BY id
            """,
            (run_id,),
        ).fetchall()

    return [dict(row) for row in rows]


def get_import_item(database_path, run_id):
    with connection.get_connection(database_path) as conn:
        row = conn.execute(
            """
            SELECT id, run_id, source_name, payload, status
            FROM order_import_items
            WHERE run_id = ?
            ORDER BY rowid DESC
            LIMIT 1
            """,
            (run_id,),
        ).fetchone()

    return dict(row) if row is not None else None


def test_valid_order_is_imported(test_db):
    database_path, run_id = test_db

    result = order_service.process_order(
        valid_order(),
        "shop-test",
        run_id,
    )

    assert result["status"] == "imported"
    assert result["external_order_id"] == "ORD-001"
    assert result["errors"] == []
    assert get_order_count(database_path, "ORD-001") == 1

    events = get_run_events(database_path, run_id)
    imported_events = [
        event
        for event in events
        if event["event_type"] == "order_imported"
    ]

    assert len(imported_events) == 1


def test_invalid_order_is_rejected(test_db):
    database_path, run_id = test_db

    order = valid_order()
    order["amount"] = "-10"

    result = order_service.process_order(
        order,
        "shop-test",
        run_id,
    )

    assert result["status"] == "rejected"
    assert result["errors"]
    assert get_order_count(database_path) == 0

    events = get_run_events(database_path, run_id)
    rejected_events = [
        event
        for event in events
        if event["event_type"] == "order_rejected"
    ]

    assert len(rejected_events) == 1
    assert rejected_events[0]["severity"] == "warning"

    details = json.loads(rejected_events[0]["details"])
    assert "validation_errors" in details


def test_duplicate_order_is_rejected(test_db):
    database_path, run_id = test_db

    first_result = order_service.process_order(
        valid_order(),
        "shop-test",
        run_id,
    )
    second_result = order_service.process_order(
        valid_order(),
        "shop-test",
        run_id,
    )

    assert first_result["status"] == "imported"
    assert second_result["status"] == "rejected"
    assert second_result["errors"]
    assert get_order_count(database_path, "ORD-001") == 1

    events = get_run_events(database_path, run_id)
    imported_events = [
        event
        for event in events
        if event["event_type"] == "order_imported"
    ]
    rejected_events = [
        event
        for event in events
        if event["event_type"] == "order_rejected"
    ]

    assert len(imported_events) == 1
    assert len(rejected_events) == 1


def test_order_processing_failure_rolls_back_transaction(
    test_db,
    monkeypatch,
):
    database_path, run_id = test_db

    original_record_run_event = order_service.record_run_event

    def failing_record_run_event(
        run_id,
        event_type,
        severity,
        message,
        details=None,
        connection=None,
    ):
        if event_type == "order_imported":
            raise RuntimeError("Simulated success-event failure")

        return original_record_run_event(
            run_id=run_id,
            event_type=event_type,
            severity=severity,
            message=message,
            details=details,
            connection=connection,
        )

    monkeypatch.setattr(
        order_service,
        "record_run_event",
        failing_record_run_event,
    )

    with pytest.raises(
        RuntimeError,
        match="Simulated success-event failure",
    ):
        order_service.process_order(
            valid_order(),
            "shop-test",
            run_id,
        )

    assert get_order_count(database_path) == 0

    events = get_run_events(database_path, run_id)
    assert not any(
        event["event_type"] == "order_imported"
        for event in events
    )


def test_duplicate_order_is_rejected_without_creating_duplicate(test_db):
    database_path, run_id = test_db

    first_result = order_service.process_order(
        valid_order(),
        "shop-test",
        run_id,
    )

    second_result = order_service.process_order(
        valid_order(),
        "shop-test",
        run_id,
    )

    assert first_result["status"] == "imported"
    assert second_result["status"] == "rejected"
    assert get_order_count(database_path, "ORD-001") == 1

    events = get_run_events(database_path, run_id)
    assert sum(
        event["event_type"] == "order_imported"
        for event in events
    ) == 1
    assert sum(
        event["event_type"] == "order_rejected"
        for event in events
    ) == 1


def test_unexpected_integrity_error_propagates(test_db):
    database_path, run_id = test_db

    with connection.get_connection(database_path) as conn:
        conn.execute(
            """
            CREATE TRIGGER reject_order_insert
            BEFORE INSERT ON orders
            BEGIN
                SELECT RAISE(
                    ABORT,
                    'Simulated unexpected integrity failure'
                );
            END;
            """
        )

    with pytest.raises(
        sqlite3.IntegrityError,
        match="Simulated unexpected integrity failure",
    ):
        order_service.process_order(
            valid_order(),
            "shop-test",
            run_id,
        )

    assert get_order_count(database_path) == 0

    events = get_run_events(database_path, run_id)
    assert not any(
        event["event_type"] == "order_imported"
        for event in events
    )


def test_unexpected_integrity_error_does_not_mark_input_imported(
    test_db,
):
    database_path, run_id = test_db
    order = valid_order()

    order_import_items.save_order_import_items(
        run_id,
        "shop-test",
        [order],
    )

    item_before = get_import_item(database_path, run_id)
    assert item_before is not None
    assert item_before["status"] == "pending"

    with connection.get_connection(database_path) as conn:
        conn.execute(
            """
            CREATE TRIGGER reject_order_insert
            BEFORE INSERT ON orders
            BEGIN
                SELECT RAISE(
                    ABORT,
                    'Simulated unexpected integrity failure'
                );
            END;
            """
        )

    with pytest.raises(
        sqlite3.IntegrityError,
        match="Simulated unexpected integrity failure",
    ):
        order_service.process_order(
            order,
            "shop-test",
            run_id,
            item_id=item_before["id"],
        )

    item_after = get_import_item(database_path, run_id)

    assert item_after is not None
    assert item_after["status"] == "pending"
    assert get_order_count(database_path) == 0

    events = get_run_events(database_path, run_id)
    assert not any(
        event["event_type"] == "order_imported"
        for event in events
    )
