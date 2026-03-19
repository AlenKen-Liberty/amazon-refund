from __future__ import annotations

import re


class CssSelectorExtractor:
    SELECTORS = [
        "#corePrice_feature_div .a-price .a-offscreen",
        "#priceblock_ourprice",
        "#priceblock_dealprice",
        "#priceblock_saleprice",
        "#price_inside_buybox",
        "#newBuyBoxPrice",
        "span.a-price > span.a-offscreen",
        "#apex_desktop .a-price .a-offscreen",
    ]

    def extract(self, page: object) -> float | None:
        for selector in self.SELECTORS:
            element = page.query_selector(selector)
            if not element:
                continue
            price = self._parse_price(element.inner_text().strip())
            if price is not None and price > 0:
                return price
        return None

    @staticmethod
    def _parse_price(text: str) -> float | None:
        match = re.search(r"(\d[\d,]*\.?\d*)", text)
        return float(match.group(1).replace(",", "")) if match else None
