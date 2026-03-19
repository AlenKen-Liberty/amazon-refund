from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime


@dataclass(slots=True)
class Order:
    order_id: str
    order_date: date
    total_amount: float
    status: str = "collected"


@dataclass(slots=True)
class Item:
    order_id: str
    asin: str
    title: str
    purchase_price: float
    product_url: str
    seller: str = ""
    is_eligible: bool = True
    item_id: int | None = None


@dataclass(slots=True)
class PriceRecord:
    asin: str
    price: float
    extraction_method: str
    checked_at: datetime | None = None


@dataclass(slots=True)
class RefundRequest:
    item_id: int
    purchase_price: float
    current_price: float
    price_diff: float
    status: str = "pending"
    refund_amount: float | None = None
    refund_type: str | None = None
    conversation_log: str | None = None
    failure_reason: str | None = None
    attempted_at: datetime | None = None
    refund_id: int | None = None


@dataclass(slots=True)
class LatestPriceSnapshot:
    item: Item
    current_price: float
    extraction_method: str
    checked_at: datetime
