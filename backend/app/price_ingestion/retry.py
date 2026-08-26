"""Retry with exponential backoff on openai.RateLimitError — see ADR-0022
§2. Up to 3 attempts, 1s/2s/4s delay between attempts (2 sleeps total for
3 attempts). Isolates failure to whatever unit calls this — exhausting
retries raises RetryExhaustedError instead of letting RateLimitError
propagate, so callers running many of these in a thread pool can degrade
one call without affecting the others (see matching.py)."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import TypeVar

from openai import RateLimitError

MAX_ATTEMPTS = 3
_BACKOFF_SECONDS = [1, 2, 4]

T = TypeVar("T")


class RetryExhaustedError(Exception):
    """Raised when a call still fails with RateLimitError after
    MAX_ATTEMPTS attempts. Wraps the last RateLimitError as __cause__."""


def call_with_retry(fn: Callable[[], T]) -> T:
    for attempt in range(MAX_ATTEMPTS):
        try:
            return fn()
        except RateLimitError as exc:
            if attempt == MAX_ATTEMPTS - 1:
                raise RetryExhaustedError(
                    f"Rate limit retry exhausted after {MAX_ATTEMPTS} attempts"
                ) from exc
            time.sleep(_BACKOFF_SECONDS[attempt])
    raise AssertionError("unreachable")
