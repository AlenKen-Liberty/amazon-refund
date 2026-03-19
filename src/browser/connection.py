from __future__ import annotations

from typing import TYPE_CHECKING, Any

from src.config import settings

if TYPE_CHECKING:
    from patchright.sync_api import Browser, BrowserContext, Page, Playwright
else:
    Browser = BrowserContext = Page = Playwright = Any


class BrowserManager:
    """Manage a CDP connection to the user's already logged-in browser."""

    def __init__(self) -> None:
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None

    def connect(self) -> Browser:
        if self._browser is not None:
            return self._browser

        from patchright.sync_api import sync_playwright

        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.connect_over_cdp(
            endpoint_url=f"http://127.0.0.1:{settings.cdp_port}",
            timeout=10_000,
        )
        return self._browser

    def get_context(self) -> BrowserContext:
        browser = self._require_browser()
        if browser.contexts:
            return browser.contexts[0]
        return browser.new_context()

    def get_page(self, url_pattern: str = "amazon.com") -> Page:
        browser = self._require_browser()
        for context in browser.contexts:
            for page in context.pages:
                if url_pattern in page.url:
                    return page
        return self.get_context().new_page()

    def new_page(self) -> Page:
        return self.get_context().new_page()

    def close(self) -> None:
        if self._browser is not None:
            self._browser.close()
            self._browser = None
        if self._playwright is not None:
            self._playwright.stop()
            self._playwright = None

    def _require_browser(self) -> Browser:
        if self._browser is None:
            raise RuntimeError("Browser is not connected. Call connect() first.")
        return self._browser
