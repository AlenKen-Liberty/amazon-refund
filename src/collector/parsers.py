from __future__ import annotations

import re
from datetime import datetime, date


ASIN_PATTERNS = (
    r"/dp/([A-Z0-9]{10})",
    r"/gp/product/([A-Z0-9]{10})",
)


def extract_asin(url: str) -> str:
    for pattern in ASIN_PATTERNS:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return ""


def parse_price_text(text: str | None) -> float:
    if not text:
        return 0.0
    match = re.search(r"(\d[\d,]*\.?\d*)", text.replace("\xa0", " "))
    return float(match.group(1).replace(",", "")) if match else 0.0


def parse_order_date(text: str | None) -> date | None:
    if not text:
        return None
    cleaned = " ".join(text.split())
    for fmt in ("%B %d, %Y", "%b %d, %Y", "%m/%d/%Y"):
        try:
            return datetime.strptime(cleaned, fmt).date()
        except ValueError:
            continue
    return None


def truncate_title(title: str, length: int = 500) -> str:
    normalized = " ".join(title.split())
    return normalized[:length]
