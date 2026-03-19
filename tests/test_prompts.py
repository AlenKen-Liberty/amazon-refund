from __future__ import annotations

from src.refund.prompts import build_opening_message, build_system_prompt


def test_opening_message_contains_order_context() -> None:
    message = build_opening_message(
        order_id="111-2222222-3333333",
        item_title="USB-C Cable",
        purchase_price=19.99,
        current_price=14.99,
        price_diff=5.00,
    )

    assert "111-2222222-3333333" in message
    assert "USB-C Cable" in message
    assert "19.99" in message
    assert "14.99" in message
    assert "5.00" in message


def test_system_prompt_contains_guardrails() -> None:
    prompt = build_system_prompt(
        order_id="111-2222222-3333333",
        item_title="USB-C Cable",
        purchase_date="2026-02-15",
        purchase_price=19.99,
        current_price=14.99,
        price_diff=5.00,
    )

    assert "automation" in prompt.lower()
    assert "1-3 sentences" in prompt
    assert "19.99" in prompt
