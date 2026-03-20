from __future__ import annotations

import re

from src.browser.selectors import SELECTORS as SEL


class CssSelectorExtractor:
    """Extract price using the resilient selector chain."""

    def extract(self, page: object) -> float | None:
        el = SEL["product_price"].find(page)
        if el is not None:
            price = self._parse_price(el.inner_text().strip())
            if price is not None and price > 0:
                return price
        return None

    @staticmethod
    def _parse_price(text: str) -> float | None:
        match = re.search(r"(\d[\d,]*\.?\d*)", text)
        return float(match.group(1).replace(",", "")) if match else None
