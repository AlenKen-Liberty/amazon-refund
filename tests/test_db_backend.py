from __future__ import annotations

from pathlib import Path

from src.db.connection import Database


def test_init_creates_data_dir(tmp_path: Path) -> None:
    """init_pool creates the data directory if missing."""
    db = Database()
    db.init_pool()
    # Should not raise
    with db.connection() as conn:
        conn.execute("SELECT 1")
