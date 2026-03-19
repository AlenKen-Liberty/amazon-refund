from __future__ import annotations

from src.refund.strategy import ConversationLog, OutcomeDetector, RefundState


class TestOutcomeDetector:
    def setup_method(self) -> None:
        self.detector = OutcomeDetector()

    def test_detects_refund_issued(self) -> None:
        state = self.detector.detect(
            "I've issued a $5.00 refund to your credit card.",
            RefundState.NEGOTIATING,
        )
        assert state == RefundState.COMPLETED

    def test_detects_promotional_credit(self) -> None:
        state = self.detector.detect(
            "I've applied a $3.50 promotional credit to your account.",
            RefundState.NEGOTIATING,
        )
        assert state == RefundState.COMPLETED

    def test_first_rejection_escalates(self) -> None:
        state = self.detector.detect(
            "Unfortunately, we are unable to process a price adjustment.",
            RefundState.NEGOTIATING,
        )
        assert state == RefundState.ESCALATING

    def test_second_rejection_fails(self) -> None:
        state = self.detector.detect(
            "I'm sorry, it is not possible to adjust the price.",
            RefundState.ESCALATING,
        )
        assert state == RefundState.FAILED

    def test_safety_identity_verify(self) -> None:
        state = self.detector.detect(
            "For security, please verify your identity before we proceed.",
            RefundState.NEGOTIATING,
        )
        assert state == RefundState.SAFETY_STOP

    def test_transfer_keeps_waiting(self) -> None:
        state = self.detector.detect(
            "Let me transfer you to a specialist who can help.",
            RefundState.NEGOTIATING,
        )
        assert state == RefundState.WAITING_REPLY

    def test_neutral_message_negotiates(self) -> None:
        state = self.detector.detect(
            "Sure, let me look into that for you. One moment please.",
            RefundState.OPENING,
        )
        assert state == RefundState.NEGOTIATING


class TestRefundExtraction:
    def setup_method(self) -> None:
        self.detector = OutcomeDetector()

    def test_extract_dollar_amount(self) -> None:
        amount = self.detector.extract_refund_amount(
            "I've issued a $5.00 refund to your original payment method."
        )
        assert amount == 5.00

    def test_extract_credit_amount(self) -> None:
        amount = self.detector.extract_refund_amount(
            "A promotional credit of $12.99 has been applied."
        )
        assert amount == 12.99

    def test_no_amount(self) -> None:
        amount = self.detector.extract_refund_amount("Let me check that for you.")
        assert amount is None

    def test_extract_refund_type(self) -> None:
        assert self.detector.extract_refund_type("gift card balance") == "gift_card"
        assert (
            self.detector.extract_refund_type("promotional credit")
            == "promotional_credit"
        )
        assert self.detector.extract_refund_type("credit card refund") == "credit_card"
        assert self.detector.extract_refund_type("issued a refund") == "refund"


class TestConversationLog:
    def test_round_counting(self) -> None:
        log = ConversationLog()
        log.add("customer", "Hi")
        log.add("agent", "Hello")
        log.add("customer", "I need help")
        assert log.rounds == 2

    def test_terminal_states(self) -> None:
        log = ConversationLog()
        log.state = RefundState.COMPLETED
        assert log.is_terminal
        assert not log.should_continue

    def test_max_rounds_stops(self) -> None:
        log = ConversationLog()
        for index in range(10):
            log.add("customer", f"msg {index}")
        assert not log.should_continue
