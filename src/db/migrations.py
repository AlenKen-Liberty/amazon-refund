from __future__ import annotations

from src.db.connection import Database

TABLE_DDLS = [
    """
    CREATE TABLE IF NOT EXISTS orders (
        order_id        TEXT PRIMARY KEY,
        order_date      TEXT NOT NULL,
        total_amount    REAL,
        status          TEXT,
        created_at      TEXT DEFAULT (datetime('now')),
        updated_at      TEXT DEFAULT (datetime('now'))
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS items (
        item_id         INTEGER PRIMARY KEY AUTOINCREMENT,
        order_id        TEXT NOT NULL REFERENCES orders(order_id),
        asin            TEXT NOT NULL,
        title           TEXT,
        purchase_price  REAL NOT NULL,
        product_url     TEXT,
        seller          TEXT,
        is_eligible     INTEGER DEFAULT 1,
        created_at      TEXT DEFAULT (datetime('now')),
        UNIQUE (order_id, asin)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS price_history (
        history_id      INTEGER PRIMARY KEY AUTOINCREMENT,
        asin            TEXT NOT NULL,
        price           REAL NOT NULL,
        extraction_method TEXT,
        checked_at      TEXT DEFAULT (datetime('now'))
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS refund_requests (
        refund_id       INTEGER PRIMARY KEY AUTOINCREMENT,
        item_id         INTEGER NOT NULL REFERENCES items(item_id),
        purchase_price  REAL NOT NULL,
        current_price   REAL NOT NULL,
        price_diff      REAL NOT NULL,
        status          TEXT DEFAULT 'pending',
        refund_amount   REAL,
        refund_type     TEXT,
        conversation_log TEXT,
        failure_reason  TEXT,
        attempted_at    TEXT,
        created_at      TEXT DEFAULT (datetime('now'))
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS system_state (
        key             TEXT PRIMARY KEY,
        value           TEXT,
        updated_at      TEXT DEFAULT (datetime('now'))
    )
    """,
]

INDEX_DDLS = [
    "CREATE INDEX IF NOT EXISTS idx_items_asin ON items(asin)",
    "CREATE INDEX IF NOT EXISTS idx_items_order ON items(order_id)",
    "CREATE INDEX IF NOT EXISTS idx_price_history_asin ON price_history(asin)",
    "CREATE INDEX IF NOT EXISTS idx_price_history_time ON price_history(checked_at)",
    "CREATE INDEX IF NOT EXISTS idx_refund_status ON refund_requests(status)",
]


def create_tables(database: Database) -> None:
    with database.connection() as conn:
        cursor = conn.cursor()
        for ddl in (*TABLE_DDLS, *INDEX_DDLS):
            cursor.execute(ddl)
