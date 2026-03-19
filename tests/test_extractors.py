from __future__ import annotations

import re

from src.monitor.extractors.css_selector import CssSelectorExtractor
from src.monitor.extractors.jsonld import JsonLdExtractor
from src.monitor.extractors.regex import RegexExtractor


class FakeElement:
    def __init__(self, text: str) -> None:
        self._text = text

    def inner_text(self) -> str:
        return self._text


class FakePage:
    def __init__(self, html: str, selector_map: dict[str, str] | None = None) -> None:
        self._html = html
        self._selector_map = selector_map or {}

    def query_selector_all(self, selector: str) -> list[FakeElement]:
        if selector != 'script[type="application/ld+json"]':
            return []

        pattern = re.compile(
            r'<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>',
            flags=re.DOTALL,
        )
        return [
            FakeElement(match.group(1).strip())
            for match in pattern.finditer(self._html)
        ]

    def query_selector(self, selector: str) -> FakeElement | None:
        text = self._selector_map.get(selector)
        return FakeElement(text) if text is not None else None

    def content(self) -> str:
        return self._html

    def inner_text(self, _: str) -> str:
        return re.sub(r"<[^>]+>", " ", self._html)


def test_jsonld_extracts_price(product_page_html: str) -> None:
    page = FakePage(product_page_html)
    extractor = JsonLdExtractor()
    assert extractor.extract(page) == 29.99


def test_css_selector_extracts_price(product_page_html: str) -> None:
    page = FakePage(
        product_page_html,
        selector_map={"#corePrice_feature_div .a-price .a-offscreen": "$29.99"},
    )
    extractor = CssSelectorExtractor()
    assert extractor.extract(page) == 29.99


def test_regex_extracts_price(product_page_html: str) -> None:
    page = FakePage(product_page_html)
    extractor = RegexExtractor()
    assert extractor.extract(page) == 29.99
