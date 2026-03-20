from __future__ import annotations

import pytest


@pytest.mark.manual
class TestRefundE2E:
    def test_llm_health(self) -> None:
        from src.llm.client import LLMClient

        llm = LLMClient()
        try:
            assert llm.health_check(), "Configured LLM service is offline"
        finally:
            llm.close()
