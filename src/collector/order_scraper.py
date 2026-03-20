from __future__ import annotations

from datetime import date, timedelta

from src.browser.connection import BrowserManager
from src.browser.selectors import SELECTORS as SEL
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

            next_button = SEL["next_page"].find(page)
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
        item_elements = SEL["purchased_items"].find_all(self.page)

        for element in item_elements:
            # Title and link
            link_element = SEL["item_title_link"].find(element)
            if not link_element:
                continue

            href = link_element.get_attribute("href") or ""
            asin = extract_asin(href)
            if not asin:
                continue

            title = truncate_title(link_element.inner_text().strip())

            # Price
            price_text = ""
            price_el = SEL["unit_price"].find(element)
            if price_el:
                price_text = price_el.inner_text().strip()

            # Seller
            seller_text = ""
            merchant_el = SEL["ordered_merchant"].find(element)
            if merchant_el:
                seller_text = merchant_el.inner_text().strip()

            item = Item(
                order_id=order_id,
                asin=asin,
                title=title,
                purchase_price=parse_price_text(price_text),
                product_url=self._build_product_url(href, asin),
                seller=seller_text,
            )
            items.append(item)

        return items

    def _parse_order_page(self, cutoff: date) -> list[Order]:
        if self.page is None:
            return []

        cards = SEL["order_card"].find_all(self.page)
        orders: list[Order] = []

        for card in cards:
            info = self._extract_order_info(card)
            if not info["order_id"]:
                continue

            parsed_date = parse_order_date(info["date_text"])
            if parsed_date is None:
                continue

            orders.append(
                Order(
                    order_id=info["order_id"],
                    order_date=parsed_date,
                    total_amount=parse_price_text(info["total_text"]),
                    status="collected" if parsed_date >= cutoff else "historical",
                )
            )

        return orders

    @staticmethod
    def _extract_order_info(card: object) -> dict[str, str]:
        """Extract order_id, date, and total from an order card.

        Amazon order cards use a flat list of ``.a-color-secondary`` spans
        laid out as label/value pairs:

            ORDER PLACED | <date> | TOTAL | <amount> | SHIP TO | ... | ORDER # | <id>
        """
        spans = SEL["order_info_spans"].find_all(card)
        texts = [s.inner_text().strip() for s in spans]

        result: dict[str, str] = {"order_id": "", "date_text": "", "total_text": ""}

        for idx, text in enumerate(texts):
            upper = text.upper()
            if idx + 1 < len(texts):
                if "ORDER PLACED" in upper:
                    result["date_text"] = texts[idx + 1]
                elif upper == "TOTAL":
                    result["total_text"] = texts[idx + 1]
                elif "ORDER #" in upper or "ORDER NUMBER" in upper:
                    result["order_id"] = texts[idx + 1]

        # Fallback: try the older selectors
        if not result["order_id"]:
            oid_node = SEL["order_id_fallback"].find(card)
            if oid_node:
                result["order_id"] = oid_node.inner_text().strip()

        return result

    @staticmethod
    def _build_product_url(href: str, asin: str) -> str:
        if href.startswith("http"):
            return href
        if href.startswith("/"):
            return f"https://www.amazon.com{href}"
        return f"https://www.amazon.com/dp/{asin}"
