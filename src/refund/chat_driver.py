from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from src.browser.stealth import human_type, random_delay
from src.refund.navigator import ChatContext


@dataclass(slots=True)
class ChatMessage:
    role: str
    content: str
    timestamp: datetime = field(default_factory=datetime.now)


class ChatDriver:
    def __init__(self, ctx: ChatContext):
        self.ctx = ctx
        self.page = ctx.page
        self._seen_count = 0

    def send_message(self, text: str) -> None:
        input_el = self.page.wait_for_selector(self.ctx.input_selector, timeout=10_000)
        input_el.click()
        input_el.fill("")
        human_type(input_el, text)
        random_delay(0.3, 0.8)

        send_btn = self.page.query_selector(self.ctx.send_selector)
        if send_btn and send_btn.is_visible():
            send_btn.click()
        else:
            input_el.press("Enter")
        random_delay(1, 2)

    def wait_for_agent_reply(self, timeout_sec: int = 90) -> str | None:
        deadline = time.monotonic() + timeout_sec
        baseline = max(self._seen_count, self._count_agent_messages())

        while time.monotonic() < deadline:
            random_delay(2, 4)
            current_count = self._count_agent_messages()
            if current_count <= baseline:
                continue

            random_delay(1, 2)
            messages = self.page.query_selector_all(self.ctx.agent_message_selector)
            if not messages:
                continue

            latest_text = self._safe_text(messages[-1])
            if latest_text:
                self._seen_count = current_count
                return latest_text
        return None

    def get_all_messages(self) -> list[ChatMessage]:
        container = self.page.query_selector(self.ctx.message_container_selector)
        if not container:
            return []

        messages: list[ChatMessage] = []
        for element in container.query_selector_all(
            ".chat-bubble, .message-bubble, [data-message-id]"
        ):
            content = self._safe_text(element)
            if not content:
                continue
            role = self._infer_role(element)
            messages.append(ChatMessage(role=role, content=content))
        return messages

    def is_chat_ended(self) -> bool:
        container = self.page.query_selector(self.ctx.message_container_selector)
        if not container:
            return False

        text = self._safe_text(container).lower()
        indicators = (
            "chat has ended",
            "conversation has been closed",
            "thank you for contacting",
        )
        return any(indicator in text for indicator in indicators)

    def _count_agent_messages(self) -> int:
        return len(self.page.query_selector_all(self.ctx.agent_message_selector))

    def _infer_role(self, element: Any) -> str:
        classes = (element.get_attribute("class") or "").lower()
        if "agent" in classes or "support" in classes:
            return "agent"
        if "customer" in classes or "user" in classes or "self" in classes:
            return "customer"
        return "customer"

    @staticmethod
    def _safe_text(element: Any) -> str:
        try:
            return (element.inner_text() or "").strip()
        except Exception:
            return ""
