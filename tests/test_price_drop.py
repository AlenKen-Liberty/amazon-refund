from __future__ import annotations

from src.analyzer.price_drop import PriceDropAnalyzer
from src.db.models import Item


def test_detects_significant_drop() -> None:
    analyzer = PriceDropAnalyzer()
    item = Item(
        item_id=1,
        order_id="111",
        asin="B000TEST01",
        title="Test Item",
        purchase_price=100.0,
        product_url="https://www.amazon.com/dp/B000TEST01",
        seller="Amazon.com",
    )
    result = analyzer.analyze(item, current_price=80.0)
    assert result is not None
    assert result.price_diff == 20.0
    assert result.pct_drop == 20.0


def test_ignores_small_drop() -> None:
    analyzer = PriceDropAnalyzer()
    item = Item(
        item_id=1,
        order_id="111",
        asin="B000TEST01",
        title="Test Item",
        purchase_price=100.0,
        product_url="https://www.amazon.com/dp/B000TEST01",
        seller="Amazon.com",
    )
    assert analyzer.analyze(item, current_price=99.5) is None


def test_ignores_third_party_seller() -> None:
    analyzer = PriceDropAnalyzer()
    item = Item(
        item_id=1,
        order_id="111",
        asin="B000TEST01",
        title="Test Item",
        purchase_price=100.0,
        product_url="https://www.amazon.com/dp/B000TEST01",
        seller="Example Seller LLC",
    )
    assert analyzer.analyze(item, current_price=70.0) is None
