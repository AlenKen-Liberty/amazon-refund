"""Unified LLM client for the configured OpenAI-compatible LLM service.

Model tiers
-----------
- **thinking** — deep reasoning (codex / gpt-5.4 by default)
- **balanced** — quality + speed  (gemini-2.5-pro by default)
- **fast**     — low-latency     (gemini-2.5-flash by default)

Callers pick a tier; the tier resolves to a concrete model name exposed
by the configured endpoint.

Provider quirks
---------------
- **Codex** backend does NOT support ``temperature`` / ``top_p``.
  Sending those parameters causes HTTP 400.
- **Gemini** backend supports ``temperature``.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from enum import Enum
from typing import Any

import httpx

from src.config import settings


# ── Codex models (no temperature support) ────────────────────────────
_CODEX_MODELS = frozenset({
    "codex",
    "gpt-5.4",
    "gpt-5.4-mini",
    "gpt-5.3-codex",
    "gpt-5.2-codex",
    "gpt-5.2",
    "gpt-5.1-codex-max",
    "gpt-5.1-codex-mini",
    "gpt-oss-120b",
    "gpt-oss-20b",
})


class ModelTier(str, Enum):
    """Semantic model tiers — callers express *intent*, not a model name."""
    THINKING = "thinking"
    BALANCED = "balanced"
    FAST = "fast"


def resolve_tier(tier: ModelTier | str) -> str:
    """Map a tier to the concrete configured model name."""
    if isinstance(tier, str):
        tier = ModelTier(tier)
    mapping = {
        ModelTier.THINKING: settings.llm_tier_thinking,
        ModelTier.BALANCED: settings.llm_tier_balanced,
        ModelTier.FAST: settings.llm_tier_fast,
    }
    return mapping[tier]


class LLMClient:
    """OpenAI-compatible client for the configured LLM service."""

    def __init__(
        self,
        *,
        base_url: str | None = None,
        model: str | None = None,
        tier: ModelTier | str | None = None,
        timeout: float = 120.0,
    ) -> None:
        self.base_url = (base_url or settings.llm_base_url).rstrip("/")
        if tier is not None:
            self.model = resolve_tier(tier)
        else:
            self.model = model or settings.llm_model
        self._client = httpx.Client(timeout=timeout)

    # ------------------------------------------------------------------ #
    #  Chat                                                               #
    # ------------------------------------------------------------------ #

    def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        temperature: float | None = 0.7,
        max_tokens: int | None = None,
    ) -> str:
        payload = self._build_payload(
            messages, temperature=temperature, max_tokens=max_tokens, stream=False,
        )
        response = self._client.post(
            f"{self.base_url}/v1/chat/completions", json=payload,
        )
        response.raise_for_status()

        data = response.json()
        choices = data.get("choices") or []
        if not choices:
            raise ValueError("LLM service returned no choices.")

        message = choices[0].get("message") or {}
        content = message.get("content")

        # Log degradation if it happened.
        self._log_degradation(response)

        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            text_parts = [
                part.get("text", "")
                for part in content
                if isinstance(part, dict) and part.get("type") == "text"
            ]
            return "".join(text_parts).strip()
        raise ValueError("LLM service returned an unsupported message format.")

    # ------------------------------------------------------------------ #
    #  Streaming                                                          #
    # ------------------------------------------------------------------ #

    def chat_stream(
        self,
        messages: list[dict[str, Any]],
        *,
        temperature: float | None = 0.7,
        max_tokens: int | None = None,
    ) -> Iterator[str]:
        payload = self._build_payload(
            messages, temperature=temperature, max_tokens=max_tokens, stream=True,
        )
        with self._client.stream(
            "POST", f"{self.base_url}/v1/chat/completions", json=payload,
        ) as response:
            response.raise_for_status()
            for line in response.iter_lines():
                token = self._parse_stream_line(line)
                if token:
                    yield token

    # ------------------------------------------------------------------ #
    #  Utilities                                                          #
    # ------------------------------------------------------------------ #

    def health_check(self) -> bool:
        for method, url in (
            ("GET", f"{self.base_url}/health"),
            ("GET", f"{self.base_url}/v1/models"),
        ):
            try:
                r = self._client.request(method, url)
            except httpx.HTTPError:
                continue
            if r.status_code < 500:
                return True
        return False

    def close(self) -> None:
        self._client.close()

    # ------------------------------------------------------------------ #
    #  Internals                                                          #
    # ------------------------------------------------------------------ #

    def _build_payload(
        self,
        messages: list[dict[str, Any]],
        *,
        temperature: float | None,
        max_tokens: int | None,
        stream: bool,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "stream": stream,
        }
        # Codex backend rejects temperature/top_p with HTTP 400.
        if temperature is not None and not self._is_codex():
            payload["temperature"] = temperature
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        return payload

    def _is_codex(self) -> bool:
        return self.model in _CODEX_MODELS

    @staticmethod
    def _log_degradation(response: httpx.Response) -> None:
        """Print a warning if the upstream gateway degraded to a different model."""
        headers = response.headers
        if headers.get("x-llm-degraded", "").lower() == "true":
            actual = headers.get("x-llm-actual-model", "?")
            reason = headers.get("x-llm-degraded-reason", "unknown")
            import sys
            print(
                f"[LLM] degraded to {actual} ({reason})",
                file=sys.stderr,
            )

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
