from __future__ import annotations

from dataclasses import dataclass

from src.config import settings
from src.db.models import Item, RefundRequest


@dataclass(slots=True)
class PriceDropResult:
    item: Item
    current_price: float
    price_diff: float
    pct_drop: float


class PriceDropAnalyzer:
    def analyze(self, item: Item, current_price: float) -> PriceDropResult | None:
        if current_price >= item.purchase_price:
            return None

        diff = round(item.purchase_price - current_price, 2)
        pct_drop = round((diff / item.purchase_price) * 100, 1)

        if diff < settings.min_refund_amount:
            return None
        if pct_drop < settings.min_refund_pct:
            return None
        if settings.amazon_only and "amazon" not in item.seller.lower():
            return None

        return PriceDropResult(
            item=item,
            current_price=current_price,
            price_diff=diff,
            pct_drop=pct_drop,
        )

    def build_refund_queue(self, drops: list[PriceDropResult]) -> list[RefundRequest]:
        ordered = sorted(drops, key=lambda drop: drop.price_diff, reverse=True)
        return [
            RefundRequest(
                item_id=drop.item.item_id or 0,
                purchase_price=drop.item.purchase_price,
                current_price=drop.current_price,
                price_diff=drop.price_diff,
            )
            for drop in ordered
            if drop.item.item_id is not None
        ]
