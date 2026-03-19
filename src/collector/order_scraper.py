from __future__ import annotations

from datetime import date, timedelta

from src.browser.connection import BrowserManager
from src.browser.stealth import human_scroll, random_delay
from src.collector.parsers import (
    extract_asin,
    parse_order_date,
    parse_price_text,
    truncate_title,
)
from src.db.models import Item, Order


class OrderScraper:
    """Collect orders and order items from Amazon order history."""

    ORDER_HISTORY_URL = "https://www.amazon.com/gp/your-account/order-history"

    def __init__(self, browser_mgr: BrowserManager) -> None:
        self.browser = browser_mgr
        self.page = None

    def scrape_orders(self, days: int = 90) -> list[Order]:
        cutoff = date.today() - timedelta(days=days)
        page = self.browser.new_page()
        self.page = page
        page.goto(self.ORDER_HISTORY_URL, wait_until="domcontentloaded")
        random_delay(1.5, 3.0)

        orders: list[Order] = []
        seen_order_ids: set[str] = set()

        while True:
            current_page_orders = self._parse_order_page(cutoff)
            stale_dates = 0
            for order in current_page_orders:
                if order.order_date < cutoff:
                    stale_dates += 1
                    continue
                if order.order_id in seen_order_ids:
                    continue
                seen_order_ids.add(order.order_id)
                orders.append(order)

            if current_page_orders and stale_dates == len(current_page_orders):
                break

            next_button = page.query_selector("li.a-last a")
            if not next_button:
                break

            human_scroll(page)
            next_button.click()
            page.wait_for_load_state("domcontentloaded")
            random_delay(1.5, 3.0)

        return orders

    def scrape_order_items(self, order_id: str) -> list[Item]:
        if self.page is None:
            self.page = self.browser.new_page()

        detail_url = (
            f"https://www.amazon.com/gp/your-account/order-details?orderID={order_id}"
        )
        self.page.goto(detail_url, wait_until="domcontentloaded")
        random_delay(1.0, 2.5)

        items: list[Item] = []
        item_elements = self.page.query_selector_all(".shipment .a-fixed-left-grid")

        for element in item_elements:
            link_element = element.query_selector(
                'a[href*="/dp/"], a[href*="/gp/product/"]'
            )
            if not link_element:
                continue

            href = link_element.get_attribute("href") or ""
            asin = extract_asin(href)
            if not asin:
                continue

            title = truncate_title(link_element.inner_text().strip())
            price_element = element.query_selector(".a-color-price")
            seller_element = element.query_selector(".a-size-small.a-color-secondary")

            item = Item(
                order_id=order_id,
                asin=asin,
                title=title,
                purchase_price=parse_price_text(
                    price_element.inner_text() if price_element else ""
                ),
                product_url=self._build_product_url(href, asin),
                seller=seller_element.inner_text().strip() if seller_element else "",
            )
            items.append(item)

        return items

    def _parse_order_page(self, cutoff: date) -> list[Order]:
        if self.page is None:
            return []

        cards = self.page.query_selector_all(".order-card, .a-box-group.order")
        orders: list[Order] = []

        for card in cards:
            order_id = self._extract_order_id(card)
            if not order_id:
                continue

            date_text = self._extract_first_text(
                card,
                [
                    ".order-info .a-column:nth-child(1) .value",
                    ".order-info .value",
                ],
            )
            parsed_date = parse_order_date(date_text)
            if parsed_date is None:
                continue

            total_text = self._extract_first_text(
                card,
                [".yohtmlc-order-total .value", ".a-color-price"],
            )
            orders.append(
                Order(
                    order_id=order_id,
                    order_date=parsed_date,
                    total_amount=parse_price_text(total_text),
                    status="collected" if parsed_date >= cutoff else "historical",
                )
            )

        return orders

    @staticmethod
    def _extract_order_id(card: object) -> str:
        attr_node = card.query_selector("[data-order-id]")
        if attr_node:
            attr_value = attr_node.get_attribute("data-order-id")
            if attr_value:
                return attr_value.strip()

        text_node = card.query_selector(".yohtmlc-order-id span.value")
        if text_node:
            return text_node.inner_text().strip()
        return ""

    @staticmethod
    def _extract_first_text(node: object, selectors: list[str]) -> str:
        for selector in selectors:
            found = node.query_selector(selector)
            if found:
                return found.inner_text().strip()
        return ""

    @staticmethod
    def _build_product_url(href: str, asin: str) -> str:
        if href.startswith("http"):
            return href
        if href.startswith("/"):
            return f"https://www.amazon.com{href}"
        return f"https://www.amazon.com/dp/{asin}"
