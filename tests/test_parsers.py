from __future__ import annotations

from datetime import date

from src.collector.parsers import (
    extract_asin,
    parse_order_date,
    parse_price_text,
    truncate_title,
)


def test_extract_asin_from_dp_url() -> None:
    assert extract_asin("https://www.amazon.com/dp/B012345678") == "B012345678"


def test_extract_asin_from_gp_url() -> None:
    assert extract_asin("/gp/product/B0ABCDEF12/ref=something") == "B0ABCDEF12"


def test_parse_price_text() -> None:
    assert parse_price_text("$1,234.56") == 1234.56


def test_parse_order_date_full_month() -> None:
    assert parse_order_date("January 15, 2026") == date(2026, 1, 15)


def test_truncate_title_normalizes_whitespace() -> None:
    assert truncate_title("  Example   item \n title  ", length=12) == "Example item"
