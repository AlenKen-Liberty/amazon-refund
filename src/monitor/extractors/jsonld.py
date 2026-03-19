from __future__ import annotations

import json
import re
from typing import Any


class JsonLdExtractor:
    def extract(self, page: object) -> float | None:
        scripts = page.query_selector_all('script[type="application/ld+json"]')
        for script in scripts:
            try:
                parsed = json.loads(script.inner_text())
            except (json.JSONDecodeError, TypeError):
                continue

            for node in self._walk_nodes(parsed):
                if not isinstance(node, dict):
                    continue
                if not self._is_product(node.get("@type")):
                    continue
                offers = node.get("offers", {})
                price = self._extract_offer_price(offers)
                if price is not None:
                    return price
        return None

    def _walk_nodes(self, value: Any) -> list[Any]:
        if isinstance(value, list):
            nodes: list[Any] = []
            for item in value:
                nodes.extend(self._walk_nodes(item))
            return nodes
        if isinstance(value, dict):
            nodes = [value]
            if "@graph" in value:
                nodes.extend(self._walk_nodes(value["@graph"]))
            return nodes
        return []

    @staticmethod
    def _is_product(type_value: Any) -> bool:
        if isinstance(type_value, str):
            return type_value == "Product"
        if isinstance(type_value, list):
            return "Product" in type_value
        return False

    @staticmethod
    def _extract_offer_price(offers: Any) -> float | None:
        if isinstance(offers, list):
            for offer in offers:
                price = JsonLdExtractor._extract_offer_price(offer)
                if price is not None:
                    return price
            return None
        if not isinstance(offers, dict):
            return None

        for key in ("price", "lowPrice", "highPrice"):
            candidate = offers.get(key)
            if candidate is None:
                continue
            match = re.search(r"(\d[\d,]*\.?\d*)", str(candidate))
            if match:
                return float(match.group(1).replace(",", ""))
        return None
