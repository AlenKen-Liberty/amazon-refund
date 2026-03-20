from __future__ import annotations

import httpx

from src.config import settings
from src.llm.client import LLMClient


class LlmExtractor:
    PROMPT = """Extract the current selling price from this Amazon product page text.
Return ONLY the numeric price (for example 29.99). If no price is found, return NONE.

Page text:
{text}
"""

    def extract(self, page: object) -> float | None:
        try:
            text = page.inner_text("body")[:3000]
        except Exception:
            return None

        provider = settings.llm_provider.lower()
        if provider in {"openai_compatible", "gateway"}:
            return self._query_llm_service(text)
        if provider == "ollama":
            return self._query_ollama(text)
        if provider == "anthropic" and settings.anthropic_api_key:
            return self._query_anthropic(text)
        if provider == "openai" and settings.openai_api_key:
            return self._query_openai(text)
        return None

    def _query_ollama(self, text: str) -> float | None:
        try:
            response = httpx.post(
                f"{settings.ollama_url}/api/generate",
                json={
                    "model": settings.ollama_model,
                    "prompt": self.PROMPT.format(text=text),
                    "stream": False,
                },
                timeout=30.0,
            )
            response.raise_for_status()
        except Exception:
            return None

        return self._coerce_price(response.json().get("response", ""))

    def _query_llm_service(self, text: str) -> float | None:
        client = LLMClient()
        try:
            reply = client.chat(
                [{"role": "user", "content": self.PROMPT.format(text=text)}],
                temperature=0.0,
            )
        except Exception:
            return None
        finally:
            client.close()

        return self._coerce_price(reply)

    def _query_anthropic(self, text: str) -> float | None:
        from anthropic import Anthropic

        try:
            client = Anthropic(api_key=settings.anthropic_api_key)
            message = client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=50,
                messages=[{"role": "user", "content": self.PROMPT.format(text=text)}],
            )
        except Exception:
            return None

        parts = getattr(message, "content", [])
        if not parts:
            return None
        return self._coerce_price(getattr(parts[0], "text", ""))

    def _query_openai(self, text: str) -> float | None:
        from openai import OpenAI

        try:
            client = OpenAI(api_key=settings.openai_api_key)
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                max_tokens=50,
                messages=[{"role": "user", "content": self.PROMPT.format(text=text)}],
            )
        except Exception:
            return None

        content = response.choices[0].message.content if response.choices else None
        return self._coerce_price(content or "")

    @staticmethod
    def _coerce_price(raw: str) -> float | None:
        value = raw.strip()
        if not value or value.upper() == "NONE":
            return None
        try:
            return float(value)
        except ValueError:
            return None
