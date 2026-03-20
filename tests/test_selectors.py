"""Tests for the resilient selector engine.

These are pure unit tests — no browser required.  They use a mock page
object to verify the fallback chain logic.
"""

from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch

import pytest

from src.browser.selectors import (
    SELECTORS,
    SelectorChain,
    Strategy,
    chain,
    css,
)


# ── Mock helpers ──────────────────────────────────────────────────────

class FakePage:
    """Minimal mock that responds to query_selector / query_selector_all."""

    def __init__(self, hits: dict[str, list[object]] | None = None):
        # hits maps CSS selector → list of fake elements
        self._hits = hits or {}

    def query_selector(self, selector: str) -> object | None:
        # Strip "xpath=" prefix for xpath strategies
        if selector.startswith("xpath="):
            selector = selector[6:]
        els = self._hits.get(selector, [])
        return els[0] if els else None

    def query_selector_all(self, selector: str) -> list[object]:
        if selector.startswith("xpath="):
            selector = selector[6:]
        return list(self._hits.get(selector, []))

    def wait_for_selector(self, selector: str, timeout: int = 5000) -> object | None:
        return self.query_selector(selector)


# ── SelectorChain logic ──────────────────────────────────────────────

class TestSelectorChainFind:
    def test_primary_hit(self):
        page = FakePage({".primary": ["el1"]})
        sc = css(".primary", ".fallback", name="test")
        assert sc.find(page) == "el1"

    def test_fallback_hit(self):
        page = FakePage({".fallback": ["el2"]})
        sc = css(".primary", ".fallback", name="test")
        assert sc.find(page) == "el2"

    def test_all_miss(self):
        page = FakePage()
        sc = css(".a", ".b", name="test")
        assert sc.find(page) is None

    def test_find_all_primary(self):
        page = FakePage({".p": ["a", "b", "c"]})
        sc = css(".p", ".q", name="test")
        assert sc.find_all(page) == ["a", "b", "c"]

    def test_find_all_fallback(self):
        page = FakePage({".q": ["x"]})
        sc = css(".p", ".q", name="test")
        assert sc.find_all(page) == ["x"]

    def test_find_all_empty(self):
        page = FakePage()
        sc = css(".p", name="test")
        assert sc.find_all(page) == []


class TestSelectorChainWait:
    def test_wait_primary(self):
        page = FakePage({".ok": ["el"]})
        sc = css(".ok", name="test")
        assert sc.wait(page, timeout_ms=1000) == "el"

    def test_wait_fallback(self):
        page = FakePage({".fb": ["el"]})
        sc = css(".miss", ".fb", name="test")
        assert sc.wait(page, timeout_ms=1000) == "el"

    def test_wait_timeout(self):
        page = FakePage()
        sc = css(".nope", name="test")
        assert sc.wait(page, timeout_ms=100) is None


class TestDegradationWarning:
    def test_warns_on_fallback(self, caplog):
        page = FakePage({".fallback": ["el"]})
        sc = css(".primary", ".fallback", name="test-degrade")
        with caplog.at_level(logging.WARNING, logger="ar.selectors"):
            result = sc.find(page)
        assert result == "el"
        assert any("selector-degraded" in r.message for r in caplog.records)

    def test_no_warn_on_primary(self, caplog):
        page = FakePage({".primary": ["el"]})
        sc = css(".primary", ".fallback", name="test-ok")
        with caplog.at_level(logging.WARNING, logger="ar.selectors"):
            sc.find(page)
        assert not any("selector-degraded" in r.message for r in caplog.records)


class TestCssProperty:
    def test_returns_first_css(self):
        sc = chain(
            Strategy("xpath", "//div"),
            Strategy("css", ".actual"),
            name="test",
        )
        assert sc.css == ".actual"

    def test_returns_primary_if_no_css(self):
        sc = chain(Strategy("xpath", "//div"), name="test")
        assert sc.css == "//div"


class TestMixedStrategies:
    def test_xpath_fallback(self):
        xpath = '//span[contains(@class, "price")]'
        page = FakePage({xpath: ["price-el"]})
        sc = chain(
            Strategy("css", ".missing"),
            Strategy("xpath", xpath),
            name="test-xpath",
        )
        assert sc.find(page) == "price-el"


# ── Registry completeness ────────────────────────────────────────────

class TestRegistry:
    """Verify that key selectors are registered."""

    EXPECTED_KEYS = [
        "order_card", "order_info_spans", "next_page",
        "purchased_items", "item_title_link", "unit_price",
        "product_price",
        "nav_something_else", "nav_start_chatting",
        "chat_input", "chat_container", "agent_message",
        "end_chat", "captcha",
    ]

    @pytest.mark.parametrize("key", EXPECTED_KEYS)
    def test_selector_registered(self, key):
        assert key in SELECTORS
        sc = SELECTORS[key]
        assert len(sc.strategies) >= 1
        assert sc.name == key

    def test_no_empty_chains(self):
        for name, sc in SELECTORS.items():
            assert len(sc.strategies) > 0, f"{name} has no strategies"

    def test_product_price_has_many_fallbacks(self):
        """Price extraction is the most fragile — should have many fallbacks."""
        sc = SELECTORS["product_price"]
        assert len(sc.strategies) >= 5
