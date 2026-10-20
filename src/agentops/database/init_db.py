from pathlib import Path

from agentops.database.connection import get_connection

SCHEMA_PATH = Path(__file__).with_name("schema.sql")


def initialize_database() -> None:
    schema = SCHEMA_PATH.read_text(encoding="utf-8")

    with get_connection() as connection:
        connection.executescript(schema)

        approval_columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(approvals)").fetchall()
        }

        if "retry_run_id" not in approval_columns:
            connection.execute("ALTER TABLE approvals ADD COLUMN retry_run_id TEXT")

        connection.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS
            idx_approvals_retry_run_id_unique
            ON approvals(retry_run_id)
            """)

        # The schema script creates this table if it is missing.
        # Verify it exists so initialization fails clearly if the
        # schema was edited incorrectly.
        table = connection.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table' AND name = ?
            """,
            ("order_import_items",),
        ).fetchone()

        if table is None:
            raise RuntimeError(
                "Database initialization failed to create "
                "the order_import_items table."
            )


if __name__ == "__main__":
    initialize_database()
    print("Database initialized successfully.")
