import json

import pytest

from agentops.database import (
    connection,
    init_db,
    workflow_registry,
    workflow_runs,
    order_import_items,
)


@pytest.fixture
def test_db(tmp_path, monkeypatch):
    database_path = tmp_path / "test_agentops.db"

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
        order_import_items,
    ):
        monkeypatch.setattr(
            module,
            "get_connection",
            temporary_connection,
        )

    init_db.initialize_database()

    workflow_id = workflow_registry.register_workflow(
        "Order Import",
        "Stores original order inputs.",
    )

    run_id = workflow_runs.create_run(workflow_id)

    return database_path, workflow_id, run_id


def test_original_inputs_are_saved_including_invalid_orders(test_db):
    database_path, _, run_id = test_db

    orders = [
        {
            "external_order_id": "ORD-001",
            "customer_reference": "CUST-001",
            "amount": "25.50",
            "currency": "USD",
            "order_date": "2026-10-17",
        },
        {
            "external_order_id": "ORD-002",
            "amount": "-10",
            "currency": "USD",
        },
        {
            "amount": "not-a-number",
        },
    ]

    item_ids = order_import_items.save_order_import_items(
        run_id,
        "shop-test",
        orders,
    )

    assert len(item_ids) == 3

    with connection.get_connection(database_path) as conn:
        rows = conn.execute(
            """
            SELECT id, external_order_id, payload, status
            FROM order_import_items
            WHERE run_id = ?
            ORDER BY rowid
            """,
            (run_id,),
        ).fetchall()

    assert len(rows) == 3
    assert [row["status"] for row in rows] == [
        "pending",
        "pending",
        "pending",
    ]
    assert rows[0]["external_order_id"] == "ORD-001"
    assert rows[1]["external_order_id"] == "ORD-002"
    assert rows[2]["external_order_id"] is None


def test_payload_can_be_decoded_back_to_original_dictionary(test_db):
    database_path, _, run_id = test_db

    original_order = {
        "external_order_id": "ORD-JSON",
        "customer_reference": "CUST-JSON",
        "amount": "25.50",
        "currency": "USD",
        "metadata": {
            "channel": "web",
            "priority": 2,
        },
    }

    order_import_items.save_order_import_items(
        run_id,
        "shop-test",
        [original_order],
    )

    with connection.get_connection(database_path) as conn:
        row = conn.execute(
            """
            SELECT payload
            FROM order_import_items
            WHERE run_id = ?
            """,
            (run_id,),
        ).fetchone()

    assert row is not None
    assert json.loads(row["payload"]) == original_order


def test_each_input_is_associated_with_the_correct_run(test_db):
    database_path, workflow_id, first_run_id = test_db

    second_run_id = workflow_runs.create_run(workflow_id)

    order_import_items.save_order_import_items(
        first_run_id,
        "shop-one",
        [{"external_order_id": "ORD-001"}],
    )

    order_import_items.save_order_import_items(
        second_run_id,
        "shop-two",
        [{"external_order_id": "ORD-002"}],
    )

    with connection.get_connection(database_path) as conn:
        rows = conn.execute("""
            SELECT run_id, source_name, external_order_id
            FROM order_import_items
            ORDER BY rowid
            """).fetchall()

    assert len(rows) == 2
    assert rows[0]["run_id"] == first_run_id
    assert rows[0]["source_name"] == "shop-one"
    assert rows[1]["run_id"] == second_run_id
    assert rows[1]["source_name"] == "shop-two"


def test_reinitialization_preserves_existing_records(test_db):
    database_path, _, run_id = test_db

    original_order = {
        "external_order_id": "ORD-PRESERVE",
        "amount": "50.00",
    }

    item_ids = order_import_items.save_order_import_items(
        run_id,
        "shop-test",
        [original_order],
    )

    # Run the schema and migration process again.
    init_db.initialize_database()

    with connection.get_connection(database_path) as conn:
        row = conn.execute(
            """
            SELECT id, run_id, payload, status
            FROM order_import_items
            WHERE id = ?
            """,
            (item_ids[0],),
        ).fetchone()

    assert row is not None
    assert row["run_id"] == run_id
    assert json.loads(row["payload"]) == original_order
    assert row["status"] == "pending"


def test_item_status_can_be_updated(test_db):
    database_path, _, run_id = test_db

    item_ids = order_import_items.save_order_import_items(
        run_id,
        "shop-test",
        [{"external_order_id": "ORD-STATUS"}],
    )

    order_import_items.update_order_import_item_status(
        item_ids[0],
        "imported",
    )

    with connection.get_connection(database_path) as conn:
        row = conn.execute(
            """
            SELECT status
            FROM order_import_items
            WHERE id = ?
            """,
            (item_ids[0],),
        ).fetchone()

    assert row["status"] == "imported"


def test_invalid_item_status_is_rejected(test_db):
    _, _, run_id = test_db

    item_ids = order_import_items.save_order_import_items(
        run_id,
        "shop-test",
        [{"external_order_id": "ORD-STATUS"}],
    )

    with pytest.raises(ValueError, match="Invalid order import item status"):
        order_import_items.update_order_import_item_status(
            item_ids[0],
            "failed",
        )


def test_nonexistent_item_update_raises_lookup_error(test_db):
    with pytest.raises(LookupError, match="does not exist"):
        order_import_items.update_order_import_item_status(
            "missing-item",
            "rejected",
        )
