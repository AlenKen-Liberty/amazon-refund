from __future__ import annotations

import json
from collections.abc import Iterable, Iterator
from typing import Any

import httpx

from src.config import settings


class LLMClient:
    """OpenAI-compatible client for the local Chat2API service."""

    def __init__(
        self,
        *,
        base_url: str | None = None,
        model: str | None = None,
        timeout: float = 120.0,
    ) -> None:
        self.base_url = (base_url or settings.chat2api_url).rstrip("/")
        self.model = model or settings.chat2api_model
        self._client = httpx.Client(timeout=timeout)

    def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        temperature: float | None = 0.7,
        max_tokens: int | None = None,
    ) -> str:
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
        }
        if temperature is not None:
            payload["temperature"] = temperature
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens

        response = self._client.post(
            f"{self.base_url}/v1/chat/completions",
            json=payload,
        )
        response.raise_for_status()

        payload = response.json()
        choices = payload.get("choices") or []
        if not choices:
            raise ValueError("Chat2API returned no choices.")

        message = choices[0].get("message") or {}
        content = message.get("content")
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            text_parts = [
                part.get("text", "")
                for part in content
                if isinstance(part, dict) and part.get("type") == "text"
            ]
            return "".join(text_parts).strip()
        raise ValueError("Chat2API returned an unsupported message format.")

    def chat_stream(
        self,
        messages: list[dict[str, Any]],
        *,
        temperature: float | None = 0.7,
        max_tokens: int | None = None,
    ) -> Iterator[str]:
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": True,
        }
        if temperature is not None:
            payload["temperature"] = temperature
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens

        with self._client.stream(
            "POST",
            f"{self.base_url}/v1/chat/completions",
            json=payload,
        ) as response:
            response.raise_for_status()
            for line in response.iter_lines():
                token = self._parse_stream_line(line)
                if token:
                    yield token

    def health_check(self) -> bool:
        checks: Iterable[tuple[str, str]] = (
            ("GET", f"{self.base_url}/health"),
            ("GET", f"{self.base_url}/v1/models"),
        )
        for method, url in checks:
            try:
                response = self._client.request(method, url)
            except httpx.HTTPError:
                continue
            if response.status_code < 500:
                return True
        return False

    def close(self) -> None:
        self._client.close()

    @staticmethod
    def _parse_stream_line(line: str | bytes | None) -> str | None:
        if not line:
            return None
        if isinstance(line, bytes):
            line = line.decode("utf-8", errors="ignore")

        stripped = line.strip()
        if not stripped or stripped == "data: [DONE]":
            return None
        if not stripped.startswith("data: "):
            return None

        payload = json.loads(stripped[6:])
        choices = payload.get("choices") or []
        if not choices:
            return None
        delta = choices[0].get("delta") or {}
        content = delta.get("content")
        if isinstance(content, str):
            return content
        return None
