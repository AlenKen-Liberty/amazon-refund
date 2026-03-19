from __future__ import annotations

import os
from datetime import date

import pytest

pytest.importorskip("oracledb")

from src.db.connection import db
from src.db.migrations import create_tables
from src.db.repository import OrderRepository, PriceRepository
from src.db.models import Order, PriceRecord

REQUIRED_ENV_VARS = ("AR_DB_USER", "AR_DB_PASSWORD", "AR_DB_DSN")
pytestmark = pytest.mark.skipif(
    any(not os.getenv(name) for name in REQUIRED_ENV_VARS),
    reason="Oracle integration env vars are not configured.",
)


@pytest.fixture(scope="module")
def connection():
    db.init_pool(force=True)
    create_tables(db)
    with db.connection() as conn:
        yield conn
        with conn.cursor() as cursor:
            cursor.execute("DELETE FROM price_history WHERE asin LIKE 'TEST%'")
            cursor.execute("DELETE FROM items WHERE asin LIKE 'TEST%'")
            cursor.execute("DELETE FROM orders WHERE order_id LIKE 'TEST-%'")
        conn.commit()
    db.close()


def test_order_upsert(connection) -> None:
    repo = OrderRepository()
    repo.upsert_order(
        connection,
        Order(order_id="TEST-001", order_date=date(2026, 1, 15), total_amount=49.99),
    )
    connection.commit()

    with connection.cursor() as cursor:
        cursor.execute("SELECT order_id FROM orders WHERE order_id = 'TEST-001'")
        row = cursor.fetchone()
    assert row is not None
    assert row[0] == "TEST-001"


def test_price_history_insert(connection) -> None:
    repo = PriceRepository()
    repo.record_price(
        connection,
        PriceRecord(asin="TESTASIN01", price=19.99, extraction_method="css"),
    )
    connection.commit()

    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT price
            FROM price_history
            WHERE asin = 'TESTASIN01'
            ORDER BY checked_at DESC
            FETCH FIRST 1 ROWS ONLY
            """
        )
        row = cursor.fetchone()
    assert row is not None
    assert float(row[0]) == 19.99
