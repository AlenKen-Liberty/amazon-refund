from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto
from typing import Any

from src.browser.stealth import human_scroll, random_delay


class NavResult(Enum):
    SUCCESS = auto()
    ORDER_NOT_FOUND = auto()
    CHAT_UNAVAILABLE = auto()
    CAPTCHA = auto()
    ERROR = auto()


@dataclass(slots=True)
class ChatContext:
    page: Any
    input_selector: str
    send_selector: str
    message_container_selector: str
    agent_message_selector: str


class CustomerServiceNavigator:
    SELECTORS = {
        "order_list_item": ".cs-order-card, [data-order-id]",
        "problem_category": "[data-item-id*='problem'], .category-item",
        "price_charge_option": "[data-item-id*='charge'], [data-item-id*='price']",
        "chat_button": "#contact-chat-btn, button[data-action='chat']",
        "chat_input": "textarea.chat-textarea, #chat-input, textarea[placeholder]",
        "chat_send": "button.send-btn, button[type='submit']",
        "chat_container": ".chat-messages, #chat-messages",
        "agent_message": ".agent-bubble, .cs-agent-message",
        "captcha": "#captchacharacters, .a-captcha",
        "identity_verify": "[data-action='verify'], .identity-verification",
    }

    CONTACT_URL = "https://www.amazon.com/gp/help/customer/contact-us"

    def navigate_to_chat(
        self, page: Any, order_id: str
    ) -> tuple[NavResult, ChatContext | None]:
        try:
            page.goto(self.CONTACT_URL, wait_until="domcontentloaded")
            try:
                page.wait_for_load_state("networkidle", timeout=10_000)
            except Exception:
                pass
            random_delay(2, 4)

            if self._check_safety(page):
                return NavResult.CAPTCHA, None

            if not self._select_order(page, order_id):
                return NavResult.ORDER_NOT_FOUND, None

            self._select_problem_category(page)

            if not self._click_first_available(page, self.SELECTORS["chat_button"]):
                return NavResult.CHAT_UNAVAILABLE, None

            random_delay(3, 6)
            page.wait_for_selector(self.SELECTORS["chat_input"], timeout=15_000)
        except Exception:
            return NavResult.ERROR, None

        context = ChatContext(
            page=page,
            input_selector=self.SELECTORS["chat_input"],
            send_selector=self.SELECTORS["chat_send"],
            message_container_selector=self.SELECTORS["chat_container"],
            agent_message_selector=self.SELECTORS["agent_message"],
        )
        return NavResult.SUCCESS, context

    def _select_order(self, page: Any, order_id: str) -> bool:
        for _ in range(3):
            cards = page.query_selector_all(self.SELECTORS["order_list_item"])
            for card in cards:
                if self._matches_order(card, order_id):
                    card.click()
                    random_delay(1, 2)
                    return True
            human_scroll(page)
            random_delay(1, 2)
        return False

    def _select_problem_category(self, page: Any) -> None:
        self._click_first_available(page, self.SELECTORS["problem_category"])
        random_delay(1, 2)
        self._click_first_available(page, self.SELECTORS["price_charge_option"])
        random_delay(1, 2)

    def _check_safety(self, page: Any) -> bool:
        return any(
            page.query_selector(self.SELECTORS[key])
            for key in ("captcha", "identity_verify")
        )

    def _click_first_available(self, page: Any, selector: str) -> bool:
        element = page.query_selector(selector)
        if not element:
            return False
        element.click()
        return True

    @staticmethod
    def _matches_order(card: Any, order_id: str) -> bool:
        try:
            text = (card.inner_text() or "").replace(" ", "")
        except Exception:
            return False
        return order_id.replace(" ", "") in text
