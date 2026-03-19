from __future__ import annotations

from src.refund.strategy import ConversationLog, OutcomeDetector, RefundState

__all__ = ["ConversationLog", "OutcomeDetector", "RefundAgent", "RefundState"]


def __getattr__(name: str):
    if name == "RefundAgent":
        from src.refund.agent import RefundAgent

        return RefundAgent
    raise AttributeError(name)
