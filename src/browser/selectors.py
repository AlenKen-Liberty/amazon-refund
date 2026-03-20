"""Resilient selector engine with fallback chains.

Amazon frequently changes its DOM structure (class names, IDs, data
attributes).  Rather than hard-coding a single CSS selector, each UI
target is expressed as a **SelectorChain**: an ordered list of
strategies tried from most-specific to most-generic.

Strategy types
--------------
- ``css``      — standard CSS selector
- ``text``     — Playwright ``:has-text()`` or ``text=`` locator
- ``attr``     — attribute-contains pattern  (e.g. ``[data-*="..."]``)
- ``xpath``    — XPath fallback for structural matching

When the *primary* (index-0) strategy fails but a later one succeeds,
a warning is logged so the maintainer can update the primary selector
before the last fallback also breaks.

Usage::

    from src.browser.selectors import SELECTORS

    el = SELECTORS["order_card"].find(page)        # first match
    els = SELECTORS["order_card"].find_all(page)    # all matches
    el = SELECTORS["order_card"].wait(page, 5000)   # wait up to 5 s
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger("ar.selectors")


# ── Core data structures ─────────────────────────────────────────────

@dataclass(frozen=True, slots=True)
class Strategy:
    """One way to locate an element."""
    kind: str          # "css" | "text" | "xpath"
    value: str         # the selector / pattern
    label: str = ""    # human description for logging


@dataclass(slots=True)
class SelectorChain:
    """Ordered list of strategies for locating a UI element."""
    name: str
    strategies: list[Strategy] = field(default_factory=list)

    # --- Public API ------------------------------------------------- #

    def find(self, page_or_element: Any) -> Any | None:
        """Return the first matching element, or ``None``."""
        for idx, strat in enumerate(self.strategies):
            el = self._try(page_or_element, strat)
            if el is not None:
                if idx > 0:
                    self._warn_degraded(idx, strat)
                return el
        log.debug("selector-miss name=%s — all %d strategies failed",
                  self.name, len(self.strategies))
        return None

    def find_all(self, page_or_element: Any) -> list[Any]:
        """Return all matching elements from the first successful strategy."""
        for idx, strat in enumerate(self.strategies):
            els = self._try_all(page_or_element, strat)
            if els:
                if idx > 0:
                    self._warn_degraded(idx, strat)
                return els
        log.warning("selector-miss name=%s — all %d strategies failed",
                    self.name, len(self.strategies))
        return []

    def wait(self, page: Any, timeout_ms: int = 10_000) -> Any | None:
        """Wait for the element using each strategy in turn."""
        per_strategy = max(timeout_ms // len(self.strategies), 2000)
        for idx, strat in enumerate(self.strategies):
            el = self._try_wait(page, strat, per_strategy)
            if el is not None:
                if idx > 0:
                    self._warn_degraded(idx, strat)
                return el
        log.warning("selector-timeout name=%s after %d ms",
                    self.name, timeout_ms)
        return None

    # --- CSS string for backward compat ----------------------------- #

    @property
    def css(self) -> str:
        """Return the primary CSS selector (for code that needs a raw string)."""
        for s in self.strategies:
            if s.kind == "css":
                return s.value
        return self.strategies[0].value if self.strategies else ""

    # --- Internals -------------------------------------------------- #

    def _try(self, ctx: Any, strat: Strategy) -> Any | None:
        try:
            if strat.kind == "css":
                return ctx.query_selector(strat.value)
            if strat.kind == "text":
                # Playwright text= locator → evaluate to element handle
                loc = ctx.locator(strat.value)
                if loc.count() > 0:
                    return loc.first.element_handle()
            if strat.kind == "xpath":
                return ctx.query_selector(f"xpath={strat.value}")
        except Exception:
            pass
        return None

    def _try_all(self, ctx: Any, strat: Strategy) -> list[Any]:
        try:
            if strat.kind == "css":
                return ctx.query_selector_all(strat.value)
            if strat.kind == "text":
                loc = ctx.locator(strat.value)
                count = loc.count()
                return [loc.nth(i).element_handle() for i in range(count)] if count else []
            if strat.kind == "xpath":
                return ctx.query_selector_all(f"xpath={strat.value}")
        except Exception:
            pass
        return []

    def _try_wait(self, page: Any, strat: Strategy, timeout_ms: int) -> Any | None:
        try:
            if strat.kind == "css":
                return page.wait_for_selector(strat.value, timeout=timeout_ms)
            if strat.kind == "text":
                loc = page.locator(strat.value)
                loc.first.wait_for(timeout=timeout_ms)
                return loc.first.element_handle()
            if strat.kind == "xpath":
                return page.wait_for_selector(f"xpath={strat.value}", timeout=timeout_ms)
        except Exception:
            pass
        return None

    def _warn_degraded(self, idx: int, strat: Strategy) -> None:
        primary = self.strategies[0]
        label = strat.label or strat.value
        log.warning(
            "selector-degraded name=%s primary=%r failed, "
            "using fallback #%d (%s: %s)",
            self.name, primary.value, idx, strat.kind, label,
        )


# ── Helper constructors ──────────────────────────────────────────────

def css(*selectors: str, name: str = "") -> SelectorChain:
    """Build a chain from multiple CSS selectors (most-specific first)."""
    return SelectorChain(
        name=name,
        strategies=[Strategy("css", s) for s in selectors],
    )


def chain(*strategies: Strategy, name: str = "") -> SelectorChain:
    """Build a chain from mixed strategy types."""
    return SelectorChain(name=name, strategies=list(strategies))


# ── Selector registry ────────────────────────────────────────────────
# All selectors used across the project, organised by module.

SELECTORS: dict[str, SelectorChain] = {}


def _register(name: str, sc: SelectorChain) -> SelectorChain:
    sc.name = name
    SELECTORS[name] = sc
    return sc


# ── Order history page ────────────────────────────────────────────────

_register("order_card", css(
    ".order-card",
    ".a-box-group.order",
    ".order-info",
    name="order_card",
))

_register("order_info_spans", css(
    ".a-color-secondary",
    ".order-info .a-column .value",
    name="order_info_spans",
))

_register("order_id_fallback", css(
    ".yohtmlc-order-id span[dir='ltr']",
    "[data-order-id]",
    name="order_id_fallback",
))

_register("next_page", css(
    "li.a-last a",
    ".a-pagination .a-last a",
    "a:has-text('Next')",
    name="next_page",
))

# ── Order detail page ────────────────────────────────────────────────

_register("purchased_items", css(
    '[data-component="purchasedItems"]',
    ".shipment .a-fixed-left-grid",
    ".item-row",
    name="purchased_items",
))

_register("item_title_link", chain(
    Strategy("css", '[data-component="itemTitle"] a[href*="/dp/"]'),
    Strategy("css", 'a[href*="/dp/"]'),
    Strategy("css", '.a-link-normal[href*="/gp/product/"]'),
    name="item_title_link",
))

_register("unit_price", chain(
    Strategy("css", '[data-component="unitPrice"] .a-offscreen'),
    Strategy("css", '[data-component="unitPrice"]'),
    Strategy("css", ".a-color-price"),
    Strategy("css", "span.a-price .a-offscreen"),
    name="unit_price",
))

_register("ordered_merchant", css(
    '[data-component="orderedMerchant"]',
    ".item-seller-info",
    name="ordered_merchant",
))

# ── Product / price page ─────────────────────────────────────────────

_register("product_price", chain(
    Strategy("css", "#corePrice_feature_div .a-price .a-offscreen"),
    Strategy("css", "#apex_desktop .a-price .a-offscreen"),
    Strategy("css", "span.a-price > span.a-offscreen"),
    Strategy("css", "#priceblock_ourprice"),
    Strategy("css", "#priceblock_dealprice"),
    Strategy("css", "#priceblock_saleprice"),
    Strategy("css", "#price_inside_buybox"),
    Strategy("css", "#newBuyBoxPrice"),
    # Generic fallback: any dollar amount near "price" in a nearby label
    Strategy("xpath",
             '//span[contains(@class, "a-price")]//span[contains(@class, "a-offscreen")]',
             label="xpath-a-price-offscreen"),
    name="product_price",
))

# ── Customer service chat navigation ─────────────────────────────────

_register("nav_something_else", chain(
    Strategy("css", 'button.fs-button:has-text("Something else")'),
    Strategy("css", 'button:has-text("Something else")'),
    Strategy("text", 'text="Something else"'),
    name="nav_something_else",
))

_register("nav_give_feedback", chain(
    Strategy("css", 'button.fs-button:has-text("Give feedback on a delivery experience")'),
    Strategy("text", 'text="Give feedback"'),
    name="nav_give_feedback",
))

_register("nav_share_positive", chain(
    Strategy("css", 'button.fs-button:has-text("Share positive feedback")'),
    Strategy("text", 'text="Share positive feedback"'),
    name="nav_share_positive",
))

_register("nav_start_chatting", chain(
    Strategy("css", 'button.fs-button:has-text("Start chatting")'),
    Strategy("css", 'button.fs-button:has-text("Chat with us")'),
    Strategy("css", 'a:has-text("Start chatting now")'),
    Strategy("text", 'text="Start chatting"'),
    name="nav_start_chatting",
))

# ── Chat window ───────────────────────────────────────────────────────

_register("chat_input", css(
    "textarea.fs-textarea",
    "textarea[placeholder*='type']",
    "#chat-text-input",
    name="chat_input",
))

_register("chat_send", css(
    "form.fs-textarea-container button[type='submit']",
    "button[aria-label='Send']",
    name="chat_send",
))

_register("chat_container", css(
    ".scribe-message-list",
    ".chat-messages-container",
    "[role='log']",
    name="chat_container",
))

_register("agent_message", css(
    ".fs-chat-row:has(.fs-chat-row-icon-participant-cs)",
    ".fs-chat-row.agent-message",
    name="agent_message",
))

_register("customer_message", css(
    ".fs-chat-row:has(.fs-chat-row-icon-participant-customer)",
    ".fs-chat-row.customer-message",
    name="customer_message",
))

_register("end_chat", chain(
    Strategy("css", "button:has-text('End this chat')"),
    Strategy("text", 'text="End this chat"'),
    Strategy("text", 'text="End Chat"'),
    name="end_chat",
))

_register("agent_joined", css(
    ".fs-chat-participant-change",
    ".chat-notification",
    name="agent_joined",
))

_register("chat_row_content", css(
    ".fs-chat-row-content-wrapper",
    ".message-content",
    name="chat_row_content",
))

_register("chat_icon_text", css(
    ".fs-chat-icon-text",
    ".participant-icon",
    name="chat_icon_text",
))

# ── Safety / anti-bot ─────────────────────────────────────────────────

_register("captcha", css(
    "#captchacharacters",
    ".a-captcha",
    "#auth-captcha-image",
    name="captcha",
))

_register("identity_verify", css(
    "[data-action='verify']",
    ".identity-verification",
    "#auth-mfa-form",
    name="identity_verify",
))
