from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass
from enum import Enum, auto
from pathlib import Path
from typing import Any

from src.browser.selectors import SELECTORS as SEL
from src.browser.stealth import human_scroll, random_delay

log = logging.getLogger("ar.navigator")

# File where successful navigation paths are persisted.
_PATHS_FILE = Path(os.environ.get(
    "AR_NAV_PATHS",
    Path(__file__).resolve().parent.parent.parent / "data" / "nav_paths.json",
))


class NavResult(Enum):
    SUCCESS = auto()
    ORDER_NOT_FOUND = auto()
    CHAT_UNAVAILABLE = auto()
    CAPTCHA = auto()
    ERROR = auto()


@dataclass(slots=True)
class ChatContext:
    page: Any
    input_selector: str
    send_selector: str
    message_container_selector: str
    agent_message_selector: str


class CustomerServiceNavigator:
    """Navigate Amazon CS pages and locate the chat window.

    Strategy (two-phase):

    **Phase 1 — Replay known paths.**
    Try each previously-successful button sequence.  If the expected
    button is visible, click it; if not, skip to the next saved path.

    **Phase 2 — Explore.**
    Scan all visible ``fs-button`` elements, score them by keyword
    priority, and click the best candidate.  Detect dead-end form
    pages and backtrack automatically.

    Successful paths (the button texts clicked) are saved to
    ``data/nav_paths.json`` so future runs try them first.
    """

    CONTACT_URL = "https://www.amazon.com/gp/help/customer/contact-us"
    MAX_NAV_DEPTH = 8

    # ── Known paths (hard-coded seeds + loaded from file) ─────────────
    # Each path is a list of button-text substrings to click in order.
    # These are tried first before falling back to exploration.
    _SEED_PATHS: list[list[str]] = [
        # Path discovered 2026-03-19 (works for delivered items):
        [
            "Give feedback on a delivery experience",
            "Report Property Damage",
            "No one was injured",
            "Something else",
            "Start chatting now",
        ],
        # Original path (works for some items):
        [
            "Something else",
            "Give feedback on a delivery experience",
            "Share positive feedback",
            "Start chatting now",
        ],
    ]

    # ── Dead ends & skips ─────────────────────────────────────────────
    _DEAD_ENDS = frozenset({
        "what if i found a better price",
        "what if i found a better price?",
    })
    _DEAD_SUBSTRINGS = (
        "call me", "request call", "schedule a call",
    )
    _SKIP_KEYWORDS = frozenset({
        "back to top", "rufus", "show/hide shortcuts",
        "sign in", "sign out",
    })

    # ── Exploration scoring ───────────────────────────────────────────
    _PREFERRED_KEYWORDS = [
        "start chatting",       # 0 — goal
        "chat with us",        # 1 — goal variant
        "something else",      # 2 — opens more options
        "report property",     # 3 — known path
        "no one",              # 4 — known path
        "give feedback",       # 5 — may lead to chat or form
        "share positive",      # 6 — may lead to chat or form
    ]

    _FORM_DEAD_ENDS = ("df-form", "feedback-form", "survey")

    # ================================================================ #
    #  Constructor                                                      #
    # ================================================================ #

    def __init__(self) -> None:
        self._known_paths = list(self._SEED_PATHS)
        self._load_paths()

    # ================================================================ #
    #  Find existing chat popup                                         #
    # ================================================================ #

    def find_open_chat(self, browser: Any) -> tuple[NavResult, ChatContext | None]:
        """Scan all browser pages for an open Amazon CS chat popup."""
        for context in browser.contexts:
            for page in list(context.pages):
                try:
                    url = page.url
                except Exception:
                    continue

                if "message-us" in url:
                    pass
                elif url == "about:blank":
                    try:
                        page.wait_for_url("**/message-us*", timeout=15_000)
                    except Exception:
                        continue
                else:
                    continue

                try:
                    page.bring_to_front()
                except Exception:
                    pass

                # Handle "continue or start new" dialog inside popup
                self._handle_popup_resume(page)

                if SEL["chat_input"].wait(page, timeout_ms=15_000) is None:
                    continue

                ctx = ChatContext(
                    page=page,
                    input_selector=SEL["chat_input"].css,
                    send_selector=SEL["chat_send"].css,
                    message_container_selector=SEL["chat_container"].css,
                    agent_message_selector=SEL["agent_message"].css,
                )
                return NavResult.SUCCESS, ctx

        return NavResult.CHAT_UNAVAILABLE, None

    # ================================================================ #
    #  Main navigation                                                  #
    # ================================================================ #

    def navigate_to_chat(
        self, page: Any, order_id: str, *, item_title: str = ""
    ) -> tuple[NavResult, ChatContext | None]:
        """Navigate to CS chat — tries known paths first, then explores."""
        try:
            # Step 1: Go to Contact Us
            page.goto(self.CONTACT_URL, wait_until="domcontentloaded")
            try:
                page.wait_for_load_state("networkidle", timeout=10_000)
            except Exception:
                pass
            random_delay(1, 2)

            if self._check_safety(page):
                return NavResult.CAPTCHA, None

            try:
                page.wait_for_selector(".entity-card", timeout=15_000)
            except Exception:
                pass
            random_delay(1, 2)

            # Step 2: Select the order entity-card
            if not self._select_order(page, order_id, item_title=item_title):
                return NavResult.ORDER_NOT_FOUND, None

            self._handle_continue_dialog(page)

            browser_obj = page.context.browser
            if browser_obj is None:
                return NavResult.ERROR, None

            # Wait for post-card buttons
            try:
                page.wait_for_selector("button.fs-button", timeout=8_000)
            except Exception:
                pass
            random_delay(0.5, 1)

            # Phase 1: Try known paths
            for path_idx, path in enumerate(self._known_paths):
                log.info("Trying known path #%d: %s", path_idx,
                         " → ".join(s[:25] for s in path))
                result, ctx = self._try_path(page, browser_obj, path)
                if result == NavResult.SUCCESS:
                    # Save this path (moves it to front)
                    self._promote_path(path)
                    return result, ctx
                # Path failed — reload the issues page for next attempt
                log.info("Known path #%d failed, reloading", path_idx)
                page.go_back(wait_until="domcontentloaded")
                random_delay(1, 2)
                # Re-select the entity-card
                try:
                    page.wait_for_selector(".entity-card", timeout=10_000)
                except Exception:
                    pass
                if not self._select_order(page, order_id, item_title=item_title):
                    continue
                self._handle_continue_dialog(page)
                try:
                    page.wait_for_selector("button.fs-button", timeout=8_000)
                except Exception:
                    pass
                random_delay(0.5, 1)

            # Phase 2: Explore
            log.info("All known paths failed. Exploring...")
            result, ctx, path_taken = self._explore(page, browser_obj)
            if result == NavResult.SUCCESS and path_taken:
                self._save_new_path(path_taken)
            return result, ctx

        except Exception as exc:
            log.exception("navigate_to_chat error: %s", exc)
            return NavResult.ERROR, None

    # ================================================================ #
    #  Phase 1: Replay a known path                                     #
    # ================================================================ #

    def _try_path(
        self, page: Any, browser: Any, path: list[str]
    ) -> tuple[NavResult, ChatContext | None]:
        """Try clicking buttons in the given order.  Fail fast if a
        button isn't found."""
        for step_idx, step_text in enumerate(path):
            # Check if chat already opened
            result, ctx = self.find_open_chat(browser)
            if result == NavResult.SUCCESS:
                return result, ctx

            # Dead-end?
            if self._is_form_dead_end(page):
                log.info("path step %d: form dead-end", step_idx)
                return NavResult.CHAT_UNAVAILABLE, None

            # Find button matching this step
            btn = self._find_button_by_text(page, step_text)
            if btn is None:
                log.info("path step %d: button %r not found", step_idx,
                         step_text[:30])
                return NavResult.CHAT_UNAVAILABLE, None

            log.info("path step %d: clicking [%s]", step_idx, step_text[:40])
            self._click_button(page, btn, step_text)

            random_delay(1.5, 3)
            try:
                page.wait_for_selector("button.fs-button, .fs-button",
                                       timeout=5_000)
            except Exception:
                pass
            random_delay(0.5, 1)
            self._handle_continue_dialog(page)

        # Final poll for popup
        for _ in range(6):
            random_delay(1.5, 2.5)
            result, ctx = self.find_open_chat(browser)
            if result == NavResult.SUCCESS:
                return result, ctx

        return NavResult.CHAT_UNAVAILABLE, None

    # ================================================================ #
    #  Phase 2: Explore                                                 #
    # ================================================================ #

    def _explore(
        self, page: Any, browser: Any
    ) -> tuple[NavResult, ChatContext | None, list[str]]:
        """Exploratory navigation — returns (result, ctx, path_taken)."""
        clicked_texts: set[str] = set()
        path_taken: list[str] = []

        for depth in range(self.MAX_NAV_DEPTH):
            result, ctx = self.find_open_chat(browser)
            if result == NavResult.SUCCESS:
                return result, ctx, path_taken

            if self._is_form_dead_end(page):
                log.info("explore depth=%d: form dead-end, going back", depth)
                self._go_back(page)
                random_delay(1.5, 2.5)
                # Remove the last step that led to the dead end
                if path_taken:
                    path_taken.pop()
                continue

            btn = self._pick_best_button(page, clicked_texts)
            if btn is None:
                log.warning("explore depth=%d: no more buttons", depth)
                break

            btn_text = self._btn_text(btn)
            log.info("explore depth=%d: clicking [%s]", depth, btn_text[:50])
            clicked_texts.add(btn_text.lower())
            path_taken.append(btn_text)

            self._click_button(page, btn, btn_text)

            random_delay(1.5, 3)
            try:
                page.wait_for_selector("button.fs-button, .fs-button",
                                       timeout=5_000)
            except Exception:
                pass
            random_delay(0.5, 1)
            self._handle_continue_dialog(page)

        # Final poll
        for _ in range(6):
            random_delay(1.5, 2.5)
            result, ctx = self.find_open_chat(browser)
            if result == NavResult.SUCCESS:
                return result, ctx, path_taken

        return NavResult.CHAT_UNAVAILABLE, None, path_taken

    # ================================================================ #
    #  Button helpers                                                   #
    # ================================================================ #

    def _click_button(self, page: Any, btn: Any, btn_text: str) -> None:
        """Click a button, using expect_popup for chat buttons."""
        btn_lower = btn_text.lower()
        if "start chatting" in btn_lower or "chat with us" in btn_lower:
            log.info("Expecting popup from chat button")
            try:
                with page.expect_popup(timeout=15_000) as popup_info:
                    btn.click()
                popup = popup_info.value
                log.info("Popup opened: %s", popup.url[:60])
                random_delay(2, 4)
                return
            except Exception:
                log.info("No popup event, clicking normally")
        try:
            btn.click()
        except Exception:
            pass

    def _find_button_by_text(self, page: Any, text: str) -> Any | None:
        """Find a visible fs-button whose text contains *text*."""
        text_lower = text.lower()
        for selector in ("button.fs-button", ".fs-button",
                         "button.fs-btn-style-squared"):
            for el in page.query_selector_all(selector):
                try:
                    if not el.is_visible():
                        continue
                    el_text = self._btn_text(el).lower()
                    if text_lower in el_text or el_text in text_lower:
                        return el
                except Exception:
                    continue
        return None

    def _pick_best_button(
        self, page: Any, already_clicked: set[str]
    ) -> Any | None:
        """Find the best visible CS-flow button to click next."""
        candidates: list[tuple[int, Any, str]] = []

        for selector in ("button.fs-button", ".fs-button",
                         "button.fs-btn-style-squared"):
            for el in page.query_selector_all(selector):
                try:
                    if not el.is_visible():
                        continue
                    text = self._btn_text(el)
                    if not text or len(text) < 3 or len(text) > 120:
                        continue
                except Exception:
                    continue

                text_lower = text.lower()
                if text_lower in already_clicked:
                    continue
                if text_lower in self._DEAD_ENDS:
                    continue
                if any(ds in text_lower for ds in self._DEAD_SUBSTRINGS):
                    continue
                if any(kw in text_lower for kw in self._SKIP_KEYWORDS):
                    continue

                score = 100
                for rank, kw in enumerate(self._PREFERRED_KEYWORDS):
                    if kw in text_lower:
                        score = rank
                        break

                candidates.append((score, el, text))

        if not candidates:
            return None

        candidates.sort(key=lambda x: x[0])
        best_score, best_el, best_text = candidates[0]
        log.info("pick_best: %d candidates, best=%r (score=%d)",
                 len(candidates), best_text[:50], best_score)
        return best_el

    # ================================================================ #
    #  Entity-card selection                                            #
    # ================================================================ #

    def _select_order(
        self, page: Any, order_id: str, *, item_title: str = ""
    ) -> bool:
        """Click the entity-card matching *order_id* or *item_title*."""
        title_words = item_title.lower().split()[:6]
        title_prefix = " ".join(title_words) if title_words else ""

        for attempt in range(5):
            cards = page.query_selector_all(".entity-card")
            log.info("_select_order attempt %d: %d cards, title_prefix=%r",
                     attempt, len(cards), title_prefix)

            if title_prefix:
                for i, card in enumerate(cards):
                    try:
                        text = (card.inner_text() or "").lower()
                    except Exception:
                        continue
                    log.debug("  card[%d] text (first 80): %s", i, text[:80].replace('\n', ' | '))
                    if title_prefix in text:
                        log.info("  → matched card[%d] by title prefix", i)
                        card.click()
                        random_delay(1, 2)
                        return True

            for card in cards:
                if self._matches_order(card, order_id):
                    card.click()
                    random_delay(1, 2)
                    return True

            if self._click_load_more(page):
                random_delay(1.5, 2.5)
                continue

            if not title_prefix:
                for card in cards:
                    try:
                        text = card.inner_text() or ""
                    except Exception:
                        continue
                    first_line = text.split("\n", 1)[0].strip().lower()
                    if first_line in ("delivered", "returning", "refunded",
                                      "cancelled"):
                        continue
                    card.click()
                    random_delay(1, 2)
                    return True

            human_scroll(page)
            random_delay(1, 2)
        return False

    # ================================================================ #
    #  Dialog handlers                                                  #
    # ================================================================ #

    def _handle_popup_resume(self, page: Any) -> None:
        """Handle 'continue or start new' dialog inside the popup window.

        The popup at message-us may show:
          "Looks like you're already chatting..."
          [Chat with associate now]  [Start a new chat]

        We always click "Start a new chat".
        """
        random_delay(0.5, 1.0)
        for sel in (
            'a:has-text("Start a new chat")',
            'button:has-text("Start a new chat")',
            'a:has-text("New chat")',
            'button:has-text("New chat")',
        ):
            try:
                el = page.query_selector(sel)
                if el and el.is_visible():
                    log.info("Popup resume: clicking %r", sel)
                    el.click()
                    random_delay(2, 3)
                    return
            except Exception:
                continue

    def _handle_continue_dialog(self, page: Any) -> None:
        """Handle 'continue or start new' on the main contact-us page."""
        random_delay(0.5, 1.0)

        all_btns = page.query_selector_all("button.fs-button, .fs-button")
        has_continue = False
        for b in all_btns:
            try:
                if b.is_visible() and "continue" in (b.inner_text() or "").lower():
                    has_continue = True
                    break
            except Exception:
                continue

        if not has_continue:
            return

        log.info("Detected continue/new dialog on main page")
        for sel in (
            'button:has-text("Start a new chat")',
            'button:has-text("New chat")',
            'button:has-text("Start new")',
            'a:has-text("Start a new chat")',
        ):
            try:
                el = page.query_selector(sel)
                if el and el.is_visible():
                    el.click()
                    random_delay(1, 2)
                    return
            except Exception:
                continue

    # ================================================================ #
    #  Misc helpers                                                     #
    # ================================================================ #

    def _is_form_dead_end(self, page: Any) -> bool:
        url = page.url.lower()
        if any(p in url for p in self._FORM_DEAD_ENDS):
            return True
        has_submit = page.query_selector(".cs-form-submit-button")
        has_cancel = page.query_selector(".cs-form-cancel-button")
        return bool(has_submit and has_cancel)

    @staticmethod
    def _go_back(page: Any) -> None:
        cancel = page.query_selector(
            '.cs-form-cancel-button, button:has-text("Cancel"), '
            'button:has-text("Go back")'
        )
        if cancel:
            try:
                cancel.click()
                return
            except Exception:
                pass
        try:
            page.go_back(wait_until="domcontentloaded")
        except Exception:
            pass

    @staticmethod
    def _click_load_more(page: Any) -> bool:
        for sel in (
            '.predicted-entities-section-footer',        # "Load more" (verified)
            '.browse-more-toggle-list-header',           # "Show more" toggle
            'div:has-text("Load more")',
            'button:has-text("Load more")',
            'a:has-text("Load more")',
            'button:has-text("See more orders")',
        ):
            try:
                el = page.query_selector(sel)
                if el and el.is_visible():
                    log.info("_click_load_more: clicking %s (%s)",
                             sel, (el.inner_text() or "").strip()[:30])
                    el.click()
                    time.sleep(2)  # wait for new cards to render
                    return True
            except Exception:
                continue
        return False

    def _check_safety(self, page: Any) -> bool:
        return any(SEL[k].find(page) is not None
                   for k in ("captcha", "identity_verify"))

    @staticmethod
    def _matches_order(card: Any, order_id: str) -> bool:
        try:
            text = (card.inner_text() or "").replace(" ", "")
        except Exception:
            return False
        return order_id.replace(" ", "") in text

    @staticmethod
    def _btn_text(el: Any) -> str:
        try:
            return (el.inner_text() or "").strip().replace("\n", " ")
        except Exception:
            return ""

    # ================================================================ #
    #  Path persistence                                                 #
    # ================================================================ #

    def _load_paths(self) -> None:
        """Load saved paths from disk and prepend them (most recent first)."""
        if not _PATHS_FILE.exists():
            return
        try:
            data = json.loads(_PATHS_FILE.read_text())
            saved = data.get("paths", [])
            # Deduplicate against seed paths
            seed_set = {tuple(p) for p in self._SEED_PATHS}
            for path in reversed(saved):
                if tuple(path) not in seed_set:
                    self._known_paths.insert(0, path)
            log.info("Loaded %d saved nav paths", len(saved))
        except Exception:
            pass

    def _save_new_path(self, path: list[str]) -> None:
        """Persist a newly-discovered successful path."""
        if not path:
            return
        log.info("Saving new nav path: %s",
                 " → ".join(s[:25] for s in path))
        existing: list[list[str]] = []
        if _PATHS_FILE.exists():
            try:
                existing = json.loads(_PATHS_FILE.read_text()).get("paths", [])
            except Exception:
                pass
        # Don't duplicate
        if path not in existing:
            existing.insert(0, path)
            # Keep at most 20 paths
            existing = existing[:20]
        _PATHS_FILE.parent.mkdir(parents=True, exist_ok=True)
        _PATHS_FILE.write_text(json.dumps({"paths": existing}, indent=2))
        # Also add to in-memory list
        self._known_paths.insert(0, path)

    def _promote_path(self, path: list[str]) -> None:
        """Move a path to the front (most recently successful) and persist."""
        key = tuple(path)
        self._known_paths = [path] + [
            p for p in self._known_paths if tuple(p) != key
        ]
        # Persist to disk (write directly, don't call _save_new_path which
        # would also insert into _known_paths again)
        existing = list(self._known_paths)
        if len(existing) > 20:
            existing = existing[:20]
        _PATHS_FILE.parent.mkdir(parents=True, exist_ok=True)
        _PATHS_FILE.write_text(json.dumps({"paths": existing}, indent=2))
