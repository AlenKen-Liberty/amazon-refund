from __future__ import annotations

from datetime import date

import pytest

from src.db.connection import db
from src.db.migrations import create_tables
from src.db.repository import OrderRepository, PriceRepository
from src.db.models import Order, PriceRecord


@pytest.fixture(scope="module")
def connection():
    db.init_pool(force=True)
    create_tables(db)
    with db.connection() as conn:
        yield conn


def test_order_upsert(connection) -> None:
    repo = OrderRepository()
    repo.upsert_order(
        connection,
        Order(order_id="TEST-001", order_date=date(2026, 1, 15), total_amount=49.99),
    )

    row = connection.execute(
        "SELECT order_id FROM orders WHERE order_id = 'TEST-001'"
    ).fetchone()
    assert row is not None
    assert row[0] == "TEST-001"


def test_price_history_insert(connection) -> None:
    repo = PriceRepository()
    repo.record_price(
        connection,
        PriceRecord(asin="TESTASIN01", price=19.99, extraction_method="css"),
    )

    row = connection.execute(
        """
        SELECT price FROM price_history
        WHERE asin = 'TESTASIN01'
        ORDER BY checked_at DESC
        LIMIT 1
        """
    ).fetchone()
    assert row is not None
    assert float(row[0]) == 19.99
