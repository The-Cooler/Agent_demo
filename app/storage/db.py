import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

SCHEMA_PATH = Path(__file__).with_name("schema.sql")


class Database:
    def __init__(self, path: str) -> None:
        self.path = path

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def init_schema(self) -> None:
        with self.connect() as conn:
            conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
