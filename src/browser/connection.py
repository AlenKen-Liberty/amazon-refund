from __future__ import annotations

import sys
from typing import TYPE_CHECKING, Any

from src.config import settings

# crystalCDP lives outside this project
sys.path.insert(0, "/home/ubuntu/scripts/crystalCDP")

if TYPE_CHECKING:
    from patchright.sync_api import Browser, BrowserContext, Page, Playwright
else:
    Browser = BrowserContext = Page = Playwright = Any


class BrowserManager:
    """Manage a CDP connection via crystalCDP to the user's already logged-in browser."""

    def __init__(self) -> None:
        self._engine: Any = None
        self._browser: Browser | None = None

    def connect(self) -> Browser:
        if self._browser is not None:
            return self._browser

        from browser import Browser as CrystalBrowser

        self._engine = CrystalBrowser(
            cdp_url=f"http://127.0.0.1:{settings.cdp_port}",
        )
        self._engine.launch()
        self._browser = self._engine._browser
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
        if self._engine is not None:
            self._engine.close()
            self._engine = None
        self._browser = None

    def _require_browser(self) -> Browser:
        if self._browser is None:
            raise RuntimeError("Browser is not connected. Call connect() first.")
        return self._browser
