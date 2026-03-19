from __future__ import annotations

import pytest

from src.llm.client import LLMClient


def _chat2api_available() -> bool:
    client = LLMClient()
    try:
        return client.health_check()
    finally:
        client.close()


def test_parse_stream_line_extracts_content() -> None:
    token = LLMClient._parse_stream_line(
        'data: {"choices":[{"delta":{"content":"hello"}}]}'
    )
    assert token == "hello"


def test_parse_stream_line_ignores_done_marker() -> None:
    assert LLMClient._parse_stream_line("data: [DONE]") is None


@pytest.fixture
def llm():
    client = LLMClient()
    yield client
    client.close()


@pytest.mark.skipif(not _chat2api_available(), reason="Chat2API not running")
class TestLLMClientIntegration:
    def test_health_check(self, llm) -> None:
        assert llm.health_check()

    def test_simple_chat(self, llm) -> None:
        reply = llm.chat([{"role": "user", "content": "Say hello and nothing else."}])
        assert reply
        assert "hello" in reply.lower()
