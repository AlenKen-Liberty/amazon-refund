from __future__ import annotations

from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def order_page_html() -> str:
    return (FIXTURES_DIR / "order_page.html").read_text(encoding="utf-8")


@pytest.fixture
def product_page_html() -> str:
    return (FIXTURES_DIR / "product_page.html").read_text(encoding="utf-8")
