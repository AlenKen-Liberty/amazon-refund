from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum, auto

from src.config import settings


class RefundState(Enum):
    INIT = auto()
    NAVIGATING = auto()
    OPENING = auto()
    WAITING_REPLY = auto()
    NEGOTIATING = auto()
    ESCALATING = auto()
    COMPLETED = auto()
    FAILED = auto()
    SAFETY_STOP = auto()
    TIMEOUT = auto()


@dataclass(slots=True)
class ConversationLog:
    messages: list[dict[str, str]] = field(default_factory=list)
    rounds: int = 0
    state: RefundState = RefundState.INIT
    refund_amount: float | None = None
    refund_type: str | None = None
    failure_reason: str | None = None

    def add(self, role: str, content: str) -> None:
        self.messages.append({"role": role, "content": content})
        if role == "customer":
            self.rounds += 1

    @property
    def is_terminal(self) -> bool:
        return self.state in {
            RefundState.COMPLETED,
            RefundState.FAILED,
            RefundState.SAFETY_STOP,
            RefundState.TIMEOUT,
        }

    @property
    def should_continue(self) -> bool:
        return not self.is_terminal and self.rounds < settings.max_chat_rounds


class OutcomeDetector:
    SAFETY_KEYWORDS = [
        "verify your identity",
        "suspicious activity",
        "unusual activity",
        "account security",
        "account has been locked",
        "verify your account",
    ]

    SUCCESS_PATTERNS = [
        r"\bissued\b.{0,40}\brefund\b",
        r"\bprocessed\b.{0,40}\brefund\b",
        r"\brefund\b.{0,20}\$\d",
        r"\bcredit has been\b",
        r"\bapplied\b.{0,40}\bcredit\b",
        r"\bcourtesy credit\b",
        r"\bpromotional credit\b",
        r"\bgift card\b",
        r"\bwe have credited\b",
        r"\bamount of \$",
    ]

    REJECT_KEYWORDS = [
        "unable to",
        "cannot",
        "not eligible",
        "not possible",
        "unfortunately",
        "don't have",
        "policy does not",
        "no longer available",
        "outside the window",
    ]

    TRANSFER_KEYWORDS = [
        "transfer",
        "supervisor",
        "specialist",
        "another department",
        "escalat",
    ]

    def detect(self, agent_message: str, current_state: RefundState) -> RefundState:
        lower = agent_message.lower()

        if any(keyword in lower for keyword in self.SAFETY_KEYWORDS):
            return RefundState.SAFETY_STOP

        if any(keyword in lower for keyword in self.REJECT_KEYWORDS):
            if current_state == RefundState.ESCALATING:
                return RefundState.FAILED
            return RefundState.ESCALATING

        if any(re.search(pattern, lower) for pattern in self.SUCCESS_PATTERNS):
            return RefundState.COMPLETED

        if any(keyword in lower for keyword in self.TRANSFER_KEYWORDS):
            return RefundState.WAITING_REPLY

        return RefundState.NEGOTIATING

    def extract_refund_amount(self, text: str) -> float | None:
        patterns = [
            r"\$(\d+\.?\d*)\s*(?:refund|credit|adjustment)",
            r"(?:refund|credit|adjustment)\s*(?:of\s*)?\$(\d+\.?\d*)",
            r"(?:issued|applied|credited)\s*\$(\d+\.?\d*)",
        ]
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return float(match.group(1))
        return None

    def extract_refund_type(self, text: str) -> str | None:
        lower = text.lower()
        if "gift card" in lower or "gift-card" in lower:
            return "gift_card"
        if "promotional" in lower or "promo" in lower:
            return "promotional_credit"
        if "credit card" in lower:
            return "credit_card"
        if "refund" in lower:
            return "refund"
        return None
