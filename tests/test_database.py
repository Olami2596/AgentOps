import sqlite3
import pytest
from agentops.database import connection, init_db

@pytest.fixture
def test_db(tmp_path, monkeypatch):
    database_path = tmp_path / "test_agentops.db"

    monkeypatch.setattr(
        connection,
        "DATABASE_PATH",
        database_path,
    )
    monkeypatch.setattr(
        init_db,
        "get_connection",
        lambda: connection.get_connection(database_path),
    )

    init_db.initialize_database()
    return database_path


def test_database_tables_exist(test_db):
    with connection.get_connection(test_db) as conn:
        rows = conn.execute("""
            SELECT name
            FROM sqlite_master
            WHERE type = 'table'
              AND name NOT LIKE 'sqlite_%'
            ORDER BY name
            """).fetchall()

    table_names = {row["name"] for row in rows}

    assert table_names == {
        "approvals",
        "audit_events",
        "order_import_items",
        "orders",
        "run_events",
        "workflow_runs",
        "workflows",
    }


def test_foreign_keys_are_enabled(test_db):
    with connection.get_connection(test_db) as conn:
        result = conn.execute("PRAGMA foreign_keys").fetchone()

    assert result[0] == 1


def test_duplicate_order_is_rejected(test_db):
    with connection.get_connection(test_db) as conn:
        conn.execute(
            """
            INSERT INTO workflows
                (id, name, description, created_at)
            VALUES (?, ?, ?, ?)
            """,
            ("workflow-test", "Order Import", "Test workflow", "2026-10-17"),
        )

        conn.execute(
            """
            INSERT INTO workflow_runs
                (id, workflow_id, status, created_at)
            VALUES (?, ?, ?, ?)
            """,
            ("run-test", "workflow-test", "running", "2026-10-17"),
        )

        order = (
            "shop-test",
            "ORD-001",
            "CUST-001",
            25.50,
            "USD",
            "2026-10-17",
            "run-test",
            "imported",
            None,
            "2026-10-17",
            "2026-10-17",
        )

        insert_order = """
            INSERT INTO orders (
                source_name, external_order_id, customer_reference,
                amount, currency, order_date, run_id, status,
                validation_errors, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """

        conn.execute(insert_order, order)

        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(insert_order, order)


def test_negative_order_amount_is_rejected(test_db):
    with connection.get_connection(test_db) as conn:
        conn.execute(
            """
            INSERT INTO workflows
                (id, name, description, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (
                "workflow-negative",
                "Order Import",
                "Test workflow",
                "2026-10-17",
            ),
        )

        conn.execute(
            """
            INSERT INTO workflow_runs
                (id, workflow_id, status, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (
                "run-negative",
                "workflow-negative",
                "running",
                "2026-10-17",
            ),
        )

        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """
                INSERT INTO orders (
                    source_name, external_order_id, customer_reference,
                    amount, currency, order_date, run_id, status,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "shop-test",
                    "ORD-NEG",
                    "CUST-002",
                    -10,
                    "USD",
                    "2026-10-17",
                    "run-negative",
                    "imported",
                    "2026-10-17",
                    "2026-10-17",
                ),
            )
