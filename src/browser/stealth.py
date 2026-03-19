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
