from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

log = logging.getLogger("ar.chat_driver")

from src.browser.stealth import (
    clear_typing_indicator,
    keep_typing_indicator,
    random_delay,
)
from src.browser.selectors import SELECTORS as SEL
from src.refund.navigator import ChatContext


@dataclass(slots=True)
class ChatMessage:
    role: str  # "customer" | "agent" | "system"
    content: str
    timestamp: datetime = field(default_factory=datetime.now)


class ChatDriver:
    """
    Send and receive messages on the Amazon CS chat popup.

    Selector reference (verified 2026-03):
      - Agent messages:   .fs-chat-row with child .fs-chat-row-icon-participant-cs
      - Customer messages: .fs-chat-row with child .fs-chat-row-icon-participant-customer
      - Input:            textarea.fs-textarea
      - Send:             Enter key (no dedicated send button)
      - Chat ended:       "End this chat" button disappears, or agent-left notification
    """

    # How long to wait after detecting a new message before concluding the
    # agent has finished typing (agents often send 2-3 rows in quick
    # succession).
    CONTINUED_SETTLE_SEC = 3.0

    def __init__(self, ctx: ChatContext) -> None:
        self.ctx = ctx
        self.page = ctx.page
        self._seen_count = self._count_agent_messages()

    # ------------------------------------------------------------------ #
    #  Sending                                                            #
    # ------------------------------------------------------------------ #

    def send_message(self, text: str) -> None:
        """Fill the textarea and send via Enter."""
        input_el = self.page.wait_for_selector(
            self.ctx.input_selector, timeout=10_000
        )
        input_el.click()
        input_el.fill("")
        # Use fill() for all messages — fast and indistinguishable from
        # a customer typing quickly or pasting.  The typing indicator
        # ("...") shown earlier already signals human presence.
        random_delay(0.3, 0.8)
        input_el.fill(text)
        random_delay(0.3, 0.6)
        input_el.press("Enter")
        random_delay(0.3, 0.6)

    # ------------------------------------------------------------------ #
    #  Typing indicator (keep the agent waiting patiently)                #
    # ------------------------------------------------------------------ #

    def start_typing(self) -> None:
        """Show a typing indicator ("...") so the agent sees activity."""
        keep_typing_indicator(self.page, self.ctx.input_selector)

    def stop_typing(self) -> None:
        """Clear the typing indicator before sending the real message."""
        clear_typing_indicator(self.page, self.ctx.input_selector)

    # ------------------------------------------------------------------ #
    #  Receiving                                                          #
    # ------------------------------------------------------------------ #

    def get_initial_greeting(self, timeout_sec: int = 60) -> str | None:
        """Return the agent's greeting message(s).

        Reads all agent messages and filters out typing indicators and ghost
        rows.  If this is a resumed chat, old messages will be included
        (that's expected — Amazon may resume previous conversations).
        """
        log.info("get_initial_greeting: waiting up to %ds", timeout_sec)
        deadline = time.monotonic() + timeout_sec
        while time.monotonic() < deadline:
            texts = self._get_agent_message_texts()
            real_texts = [t for t in texts if len(t.strip()) > 2]
            if real_texts:
                self._seen_count = len(texts)
                log.info("get_initial_greeting: got %d real texts (of %d total)",
                         len(real_texts), len(texts))
                return "\n".join(real_texts)
            time.sleep(1.0)
        return None

    def wait_for_agent_reply(self, timeout_sec: int = 90) -> str | None:
        """
        Wait until new agent message(s) appear with actual text content.

        Polls every ~1 second.  Ignores typing-indicator rows (dot loader)
        and ghost rows (icon-only ≤2 chars).  Once real content is found,
        waits :pyattr:`CONTINUED_SETTLE_SEC` for follow-up rows.

        Returns ``None`` on timeout.
        """
        deadline = time.monotonic() + timeout_sec
        baseline = self._seen_count
        log.info("wait_for_agent_reply: baseline=%d, timeout=%ds",
                 baseline, timeout_sec)

        poll_n = 0
        while time.monotonic() < deadline:
            time.sleep(0.8)

            # Check for new texts (skips typing indicators & empty rows)
            all_texts = self._get_agent_message_texts()
            new_texts = all_texts[baseline:]

            # Filter out ghost rows (icon-only ≤2 chars)
            real_texts = [t for t in new_texts if len(t.strip()) > 2]

            poll_n += 1
            if poll_n % 10 == 1:  # log every 10th poll (~8s)
                log.debug(
                    "wait poll #%d: all=%d new=%d real=%d | page_url=%s",
                    poll_n, len(all_texts), len(new_texts), len(real_texts),
                    self.page.url[:60] if self.page else "?",
                )

            if not real_texts:
                # Maybe the row count increased but it's a typing indicator
                # or content hasn't loaded yet — just keep polling
                continue

            # Real content found — settle window: wait for follow-up rows
            log.info("wait_for_agent_reply: got %d real texts, settling...",
                     len(real_texts))
            settle_deadline = time.monotonic() + self.CONTINUED_SETTLE_SEC
            while time.monotonic() < settle_deadline:
                time.sleep(0.4)
                all_texts_2 = self._get_agent_message_texts()
                new_texts_2 = all_texts_2[baseline:]
                real_texts_2 = [t for t in new_texts_2 if len(t.strip()) > 2]
                if len(real_texts_2) > len(real_texts):
                    # More real rows arrived — extend settle window
                    real_texts = real_texts_2
                    settle_deadline = time.monotonic() + self.CONTINUED_SETTLE_SEC

            self._seen_count = len(all_texts)
            return "\n".join(real_texts)

        return None

    @staticmethod
    def agent_still_working(reply: str) -> bool:
        """Return True if the agent's reply suggests they are still looking
        something up and haven't finished yet (e.g. 'let me check',
        'please wait', 'one moment').  The caller should wait for a follow-up
        instead of sending a farewell."""
        lower = reply.lower().strip()
        # Check the *last* line — the most recent thing the agent said
        last_line = lower.rsplit("\n", 1)[-1].strip()
        _WORKING_PHRASES = (
            "let me check",
            "let me look",
            "allow me",
            "one moment",
            "just a moment",
            "a minute",
            "a moment",
            "please wait",
            "please hold",
            "hold on",
            "looking into",
            "checking",
            "i'll check",
            "i will check",
            "let me see",
            "give me a sec",
            "bear with me",
        )
        return any(phrase in last_line for phrase in _WORKING_PHRASES)

    # ------------------------------------------------------------------ #
    #  Reading                                                            #
    # ------------------------------------------------------------------ #

    def get_all_messages(self) -> list[ChatMessage]:
        """Read all visible messages from the chat window."""
        container = self.page.query_selector(
            self.ctx.message_container_selector
        )
        if not container:
            return []

        messages: list[ChatMessage] = []
        rows = container.query_selector_all(
            ".fs-chat-row:not(.fs-chat-participant-change)"
        )
        for row in rows:
            content = self._extract_row_text(row)
            if not content:
                continue
            role = self._infer_role(row)
            messages.append(ChatMessage(role=role, content=content))

        return messages

    def is_chat_ended(self) -> bool:
        """Detect whether the chat session has ended."""
        changes = SEL["agent_joined"].find_all(self.page)
        for change in changes:
            text = self._safe_text(change).lower()
            if "has left" in text or "ended" in text:
                return True

        end_btn = SEL["end_chat"].find(self.page)
        if not end_btn:
            return True

        container = self.page.query_selector(
            self.ctx.message_container_selector
        )
        if container:
            text = self._safe_text(container).lower()
            indicators = (
                "chat has ended",
                "conversation has been closed",
                "has left the chat",
            )
            if any(ind in text for ind in indicators):
                return True

        return False

    # ------------------------------------------------------------------ #
    #  Internals                                                          #
    # ------------------------------------------------------------------ #

    def _extract_row_text(self, row: Any) -> str:
        """Extract message text from a chat row, excluding the icon letter.

        Returns empty string for typing-indicator rows (``fs-dot-loader``).
        """
        # Check for typing indicator (dot loader) — not a real message yet
        try:
            if row.query_selector(".fs-dot-loader"):
                return ""
        except Exception:
            pass

        # Primary: look inside fs-chat-row-children (the content area,
        # excluding the icon wrapper)
        for sel in (
            ".fs-chat-row-children",
            ".fs-chat-row-content-wrapper",
            ".message-content",
        ):
            try:
                el = row.query_selector(sel)
                if el:
                    text = self._safe_text(el)
                    if len(text.strip()) > 2:
                        return text
            except Exception:
                pass

        # Secondary: try broader CSS selectors
        for sel in (
            "[class*='content-wrapper']",
            "[class*='message-text']",
            "[class*='chat-row-content']",
        ):
            try:
                el = row.query_selector(sel)
                if el:
                    text = self._safe_text(el)
                    if len(text.strip()) > 2:
                        log.debug("extract_row_text matched alt selector: %s", sel)
                        return text
            except Exception:
                pass

        # Fallback: strip the icon letter(s) from the row text.
        raw = self._safe_text(row)
        lines = raw.split("\n")
        while lines and len(lines[0].strip()) <= 2:
            lines.pop(0)
        result = "\n".join(lines).strip() if lines else raw

        if len(result.strip()) <= 2:
            try:
                html = row.inner_html() or ""
                log.warning(
                    "extract_row_text got icon-only text=%r, HTML (first 500): %s",
                    result, html[:500],
                )
            except Exception:
                pass

        return result

    def _count_agent_messages(self) -> int:
        return len(
            self.page.query_selector_all(self.ctx.agent_message_selector)
        )

    def _get_agent_message_texts(self) -> list[str]:
        rows = self.page.query_selector_all(self.ctx.agent_message_selector)
        texts: list[str] = []
        for row in rows:
            t = self._extract_row_text(row)
            if t:
                texts.append(t)
        return texts

    def _infer_role(self, element: Any) -> str:
        html = ""
        try:
            html = element.inner_html() or ""
        except Exception:
            pass

        if "participant-cs" in html:
            return "agent"
        if "participant-customer" in html:
            return "customer"

        icon = SEL["chat_icon_text"].find(element)
        if icon:
            icon_text = self._safe_text(icon)
            if icon_text.lower() == "you":
                return "customer"
            if len(icon_text) == 1 and icon_text.isalpha():
                return "agent"

        return "agent"

    @staticmethod
    def _safe_text(element: Any) -> str:
        try:
            return (element.inner_text() or "").strip()
        except Exception:
            return ""
