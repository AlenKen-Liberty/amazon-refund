from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from src.config import settings

_DB_DIR = Path(__file__).resolve().parent.parent.parent / "data"


class Database:
    def __init__(self) -> None:
        self._db_path: Path | None = None

    def init_pool(self, force: bool = False) -> None:
        _DB_DIR.mkdir(parents=True, exist_ok=True)
        self._db_path = _DB_DIR / "amazon_refund.db"

    def get_connection(self) -> sqlite3.Connection:
        if self._db_path is None:
            self.init_pool()
        conn = sqlite3.connect(str(self._db_path))
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    @contextmanager
    def connection(self) -> Any:
        conn = self.get_connection()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def close(self) -> None:
        pass  # SQLite connections are per-call, no pool to close


db = Database()
