from __future__ import annotations

from dataclasses import dataclass

from src.browser.connection import BrowserManager
from src.browser.stealth import random_delay
from src.db.models import Item
from src.monitor.extractors.css_selector import CssSelectorExtractor
from src.monitor.extractors.jsonld import JsonLdExtractor
from src.monitor.extractors.llm import LlmExtractor
from src.monitor.extractors.regex import RegexExtractor
from src.monitor.voter import PriceVoter


@dataclass(slots=True)
class PriceCheckResult:
    item: Item
    final_price: float | None
    extraction_method: str | None
    raw_prices: dict[str, float | None]


class PriceChecker:
    def __init__(self, browser_mgr: BrowserManager) -> None:
        self.browser = browser_mgr
        self.extractors = {
            "jsonld": JsonLdExtractor(),
            "css": CssSelectorExtractor(),
            "regex": RegexExtractor(),
            "llm": LlmExtractor(),
        }
        self.voter = PriceVoter()

    def check_item(self, item: Item) -> PriceCheckResult:
        page = self.browser.new_page()
        try:
            page.goto(
                item.product_url or f"https://www.amazon.com/dp/{item.asin}",
                wait_until="domcontentloaded",
            )
            try:
                page.wait_for_load_state("networkidle", timeout=8_000)
            except Exception:
                pass
            random_delay(1.0, 2.0)

            raw_prices = {
                name: extractor.extract(page)
                for name, extractor in self.extractors.items()
            }
            final_price = self.voter.vote(raw_prices)
            return PriceCheckResult(
                item=item,
                final_price=final_price,
                extraction_method=self._choose_method(raw_prices, final_price),
                raw_prices=raw_prices,
            )
        finally:
            page.close()

    def check_items(self, items: list[Item]) -> list[PriceCheckResult]:
        return [self.check_item(item) for item in items]

    @staticmethod
    def _choose_method(
        raw_prices: dict[str, float | None], final_price: float | None
    ) -> str | None:
        if final_price is None:
            return None

        valid_matches = [
            name
            for name, price in raw_prices.items()
            if price is not None and abs(price - final_price) <= PriceVoter.TOLERANCE
        ]
        if len(valid_matches) == 1:
            return valid_matches[0]
        return "voted"
