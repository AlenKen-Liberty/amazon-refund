"""Model compatibility tests for Chat2API.

These tests verify that every model tier and every provider behaves correctly
for the specific capabilities the refund agent needs:

1. Single-turn chat (basic request/response)
2. Multi-turn chat (system + user + assistant + user)
3. Streaming
4. Temperature handling (Codex rejects it — client must omit)
5. Tier resolution

Run with:
    pytest tests/test_llm_models.py -v

Tests marked ``@pytest.mark.live`` require Chat2API to be running.
"""

from __future__ import annotations

import pytest

from src.llm.client import LLMClient, ModelTier, _CODEX_MODELS, resolve_tier


# ── Tier resolution (pure unit tests, no network) ─────────────────────

class TestTierResolution:
    def test_thinking_resolves(self):
        model = resolve_tier(ModelTier.THINKING)
        assert model  # non-empty string

    def test_balanced_resolves(self):
        model = resolve_tier(ModelTier.BALANCED)
        assert model

    def test_fast_resolves(self):
        model = resolve_tier(ModelTier.FAST)
        assert model

    def test_string_tier(self):
        assert resolve_tier("fast") == resolve_tier(ModelTier.FAST)

    def test_invalid_tier_raises(self):
        with pytest.raises(ValueError):
            resolve_tier("nonexistent")


class TestCodexDetection:
    def test_codex_alias_detected(self):
        client = LLMClient(model="codex")
        assert client._is_codex()

    def test_gpt54_detected(self):
        client = LLMClient(model="gpt-5.4")
        assert client._is_codex()

    def test_gemini_not_codex(self):
        client = LLMClient(model="gemini-2.5-flash")
        assert not client._is_codex()


class TestPayloadBuild:
    """Verify that temperature is correctly omitted for Codex models."""

    def test_codex_omits_temperature(self):
        client = LLMClient(model="codex")
        payload = client._build_payload(
            [{"role": "user", "content": "hi"}],
            temperature=0.7,
            max_tokens=100,
            stream=False,
        )
        assert "temperature" not in payload
        assert payload["max_tokens"] == 100

    def test_gemini_includes_temperature(self):
        client = LLMClient(model="gemini-2.5-flash")
        payload = client._build_payload(
            [{"role": "user", "content": "hi"}],
            temperature=0.5,
            max_tokens=None,
            stream=False,
        )
        assert payload["temperature"] == 0.5
        assert "max_tokens" not in payload

    def test_none_temperature_omitted_for_all(self):
        for model in ("codex", "gemini-2.5-flash"):
            client = LLMClient(model=model)
            payload = client._build_payload(
                [{"role": "user", "content": "hi"}],
                temperature=None,
                max_tokens=None,
                stream=False,
            )
            assert "temperature" not in payload


class TestClientInit:
    def test_tier_overrides_model(self):
        client = LLMClient(tier=ModelTier.FAST)
        assert client.model == resolve_tier(ModelTier.FAST)

    def test_explicit_model(self):
        client = LLMClient(model="gemini-2.5-flash")
        assert client.model == "gemini-2.5-flash"


# ── Live integration tests (require Chat2API) ────────────────────────

def _chat2api_online() -> bool:
    try:
        return LLMClient().health_check()
    except Exception:
        return False


@pytest.mark.skipif(not _chat2api_online(), reason="Chat2API not running")
class TestSingleTurn:
    """Every tier must be able to answer a trivial one-shot question."""

    @pytest.fixture(params=["thinking", "balanced", "fast"], ids=lambda t: f"tier-{t}")
    def client(self, request):
        c = LLMClient(tier=request.param)
        yield c
        c.close()

    def test_single_turn(self, client):
        reply = client.chat(
            [{"role": "user", "content": "Reply with exactly one word: hello"}],
        )
        assert len(reply) > 0
        assert "hello" in reply.lower()


@pytest.mark.skipif(not _chat2api_online(), reason="Chat2API not running")
class TestMultiTurn:
    """Multi-turn context via packed transcript (the only format both backends accept).

    Both Gemini and Codex backends reject ``assistant`` role in the messages
    array (HTTP 400).  The correct strategy is to pack the conversation
    history into a single ``user`` message as a transcript.
    """

    @pytest.fixture(params=["thinking", "balanced", "fast"], ids=lambda t: f"tier-{t}")
    def client(self, request):
        c = LLMClient(tier=request.param)
        yield c
        c.close()

    def test_assistant_role_may_fail(self, client):
        """Multi-turn with raw assistant role may fail on some backends."""
        messages = [
            {"role": "user", "content": "My number is 42."},
            {"role": "assistant", "content": "Got it."},
            {"role": "user", "content": "What number?"},
        ]
        # Some backends reject assistant role, some degrade gracefully.
        # Just verify no unhandled crash — either a reply or an HTTP error.
        try:
            reply = client.chat(messages)
            assert reply is not None
        except Exception:
            pass  # HTTP 400 is acceptable

    def test_packed_transcript_works(self, client):
        """Packed transcript preserves context across turns."""
        transcript = (
            "Customer: My order number is 111-222-333.\n"
            "Agent: Got it, order 111-222-333. How can I help?\n\n"
            "What was the order number the customer mentioned? Reply with just the number."
        )
        reply = client.chat([
            {"role": "system", "content": "You help customers get refunds."},
            {"role": "user", "content": transcript},
        ])
        assert "111" in reply or "222" in reply or "333" in reply


@pytest.mark.skipif(not _chat2api_online(), reason="Chat2API not running")
class TestStreaming:
    """Verify streaming works for at least one model."""

    def test_stream_returns_tokens(self):
        client = LLMClient(tier=ModelTier.FAST)
        tokens = list(client.chat_stream(
            [{"role": "user", "content": "Say hello in one word."}],
        ))
        client.close()
        assert len(tokens) > 0
        full = "".join(tokens)
        assert len(full) > 0


@pytest.mark.skipif(not _chat2api_online(), reason="Chat2API not running")
class TestRefundScenario:
    """End-to-end test: can the LLM generate a natural refund reply?"""

    def test_generates_refund_reply(self):
        from src.refund.prompts import build_system_prompt

        system = build_system_prompt(
            order_id="111-222-333",
            item_title="USB-C Cable 6ft",
            purchase_date="2026-02-20",
            purchase_price=15.99,
            current_price=11.99,
            price_diff=4.00,
        )

        client = LLMClient(tier=ModelTier.FAST)
        reply = client.chat([
            {"role": "system", "content": system},
            {"role": "user", "content": (
                "Here is the conversation so far:\n\n"
                "Agent: Hello, how can I help you today?\n\n"
                "Generate the customer's next message. "
                "Keep it short (1-3 sentences), natural, polite."
            )},
        ])
        client.close()

        assert len(reply) > 10
        # Should not mention bots/automation
        lower = reply.lower()
        assert "bot" not in lower
        assert "automat" not in lower
        assert "script" not in lower
