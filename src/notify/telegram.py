from __future__ import annotations

import httpx

from src.config import settings
from src.notify.base import Notifier


class TelegramNotifier(Notifier):
    def __init__(
        self,
        *,
        bot_token: str | None = None,
        chat_id: str | None = None,
    ) -> None:
        self.bot_token = bot_token or settings.telegram_bot_token
        self.chat_id = chat_id or settings.telegram_chat_id

    def send(self, title: str, body: str) -> bool:
        if not self.bot_token or not self.chat_id:
            return False

        response = httpx.post(
            f"https://api.telegram.org/bot{self.bot_token}/sendMessage",
            json={"chat_id": self.chat_id, "text": f"{title}\n\n{body}"},
            timeout=15.0,
        )
        response.raise_for_status()
        return True
