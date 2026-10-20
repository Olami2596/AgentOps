import sqlite3
from contextlib import contextmanager
from collections.abc import Generator
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DATABASE_PATH = PROJECT_ROOT / "agentops.db"


@contextmanager
def get_connection(
    database_path: Path | None = None,
) -> Generator[sqlite3.Connection, None, None]:
    if database_path is None:
        database_path = DATABASE_PATH

    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")

    try:
        with connection:
            yield connection
    finally:
        connection.close()
