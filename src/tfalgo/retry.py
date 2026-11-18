"""Retry with exponential backoff and a simple rate limiter (for broker providers)."""

from __future__ import annotations

import functools
import logging
import random
import time
from collections.abc import Callable
from typing import ParamSpec, TypeVar

P = ParamSpec("P")
R = TypeVar("R")
log = logging.getLogger(__name__)


def retry(
    max_attempts: int = 5,
    base_delay: float = 0.5,
    max_delay: float = 30.0,
    exceptions: tuple[type[BaseException], ...] = (Exception,),
    sleep: Callable[[float], None] = time.sleep,
) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """Retry decorator: delay = min(max_delay, base * 2**attempt) + jitter."""

    def deco(fn: Callable[P, R]) -> Callable[P, R]:
        @functools.wraps(fn)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            for attempt in range(max_attempts):
                try:
                    return fn(*args, **kwargs)
                except exceptions as exc:
                    if attempt == max_attempts - 1:
                        raise
                    delay = min(max_delay, base_delay * 2**attempt) + random.uniform(0, 0.1)
                    log.warning("retry %s attempt=%d delay=%.2f err=%r", fn.__name__, attempt + 1, delay, exc)
                    sleep(delay)
            raise RuntimeError("unreachable")

        return wrapper

    return deco


class RateLimiter:
    """Minimum spacing between calls (calls_per_sec)."""

    def __init__(self, calls_per_sec: float, clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] = time.sleep) -> None:
        self._gap = 1.0 / calls_per_sec
        self._clock, self._sleep = clock, sleep
        self._last = -1e18

    def wait(self) -> None:
        now = self._clock()
        remaining = self._gap - (now - self._last)
        if remaining > 0:
            self._sleep(remaining)
        self._last = self._clock()
