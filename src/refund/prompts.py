from __future__ import annotations

SYSTEM_PROMPT = """\
You are a helpful assistant guiding a customer through an Amazon customer service chat \
to request a price adjustment (partial refund) on a recent order.

## Your role
Generate the customer's next chat message. Be polite, natural, and concise, like a normal \
person texting customer support, not a formal letter.

## Context
- Order ID: {order_id}
- Item: {item_title}
- Purchase date: {purchase_date}
- Purchase price: ${purchase_price:.2f}
- Current price: ${current_price:.2f}
- Price difference: ${price_diff:.2f}

## Rules
1. Sound like a regular customer. Use casual but polite language.
2. Never mention automation, scripts, bots, or AI.
3. Keep messages short, 1-3 sentences max.
4. Stick to facts. Do not fabricate order details.
5. If the agent offers a gift card or promotional credit instead of a direct refund, accept it.
6. If refused, politely ask if a supervisor could review the request.
7. If refused again, thank them and end the conversation.
8. Do not ask questions that the agent already answered.
"""

OPENING_TEMPLATE = """\
Hi! I recently bought {item_title} (order #{order_id}) for ${purchase_price:.2f}, and I noticed \
the price has dropped to ${current_price:.2f}. That's a ${price_diff:.2f} difference. Is there \
any way to get a price adjustment or partial refund?\
"""

ESCALATION_TEMPLATE = """\
I understand. Would it be possible to have a supervisor or specialist take a look? I've been a \
loyal customer and would really appreciate any help with this.\
"""

ACCEPT_CREDIT_TEMPLATE = """\
That works for me, thank you! I appreciate the help.\
"""

CLOSING_TEMPLATE = """\
I understand. Thank you for your time and help. Have a great day!\
"""


def build_system_prompt(
    order_id: str,
    item_title: str,
    purchase_date: str,
    purchase_price: float,
    current_price: float,
    price_diff: float,
) -> str:
    return SYSTEM_PROMPT.format(
        order_id=order_id,
        item_title=item_title,
        purchase_date=purchase_date,
        purchase_price=purchase_price,
        current_price=current_price,
        price_diff=price_diff,
    )


def build_opening_message(
    order_id: str,
    item_title: str,
    purchase_price: float,
    current_price: float,
    price_diff: float,
) -> str:
    return OPENING_TEMPLATE.format(
        order_id=order_id,
        item_title=item_title,
        purchase_price=purchase_price,
        current_price=current_price,
        price_diff=price_diff,
    )
