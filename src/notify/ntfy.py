from __future__ import annotations

import httpx

from src.config import settings
from src.notify.base import Notifier


class NtfyNotifier(Notifier):
    def __init__(self, *, server: str | None = None, topic: str | None = None) -> None:
        self.server = (server or settings.ntfy_server).rstrip("/")
        self.topic = topic or settings.ntfy_topic

    def send(self, title: str, body: str) -> bool:
        if not self.topic:
            return False

        response = httpx.post(
            f"{self.server}/{self.topic}",
            content=body.encode("utf-8"),
            headers={"Title": title},
            timeout=15.0,
        )
        response.raise_for_status()
        return True
