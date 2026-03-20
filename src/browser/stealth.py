from __future__ import annotations

import random
import time


def random_delay(min_sec: float = 1.0, max_sec: float = 3.0) -> None:
    time.sleep(random.uniform(min_sec, max_sec))


def human_type(
    element: object, text: str, min_delay: int = 50, max_delay: int = 150
) -> None:
    for char in text:
        element.type(char, delay=random.randint(min_delay, max_delay))


def human_scroll(
    page: object, direction: str = "down", amount: int | None = None
) -> None:
    delta = amount or random.randint(200, 600)
    if direction == "up":
        delta = -delta
    page.mouse.wheel(0, delta)
    random_delay(0.3, 1.0)


def jittered_interval(base_seconds: float, jitter_pct: float = 0.3) -> float:
    jitter = base_seconds * jitter_pct
    return base_seconds + random.uniform(-jitter, jitter)


def keep_typing_indicator(page: object, input_selector: str) -> None:
    """Put a few dots in the textarea so the agent sees a typing indicator.

    Call this *before* a potentially slow operation (e.g. LLM call) so the
    agent on the other end sees "..." and knows the customer is composing.
    """
    try:
        el = page.query_selector(input_selector)
        if el:
            el.click()
            el.fill("...")
    except Exception:
        pass


def clear_typing_indicator(page: object, input_selector: str) -> None:
    """Remove the placeholder dots inserted by :func:`keep_typing_indicator`."""
    try:
        el = page.query_selector(input_selector)
        if el:
            el.fill("")
    except Exception:
        pass
