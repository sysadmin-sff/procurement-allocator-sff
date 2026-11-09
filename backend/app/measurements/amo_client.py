"""Read-only amoCRM API v4 client (ADR-0051 §4, §5).

The module only ever reads from amo, so this class deliberately has no method
that could issue anything other than GET.
"""

import logging
import time
from collections.abc import Callable, Iterator, Sequence
from typing import Any
from urllib.parse import urlsplit

import httpx
from pydantic import SecretStr

# httpx logs full request lines at INFO (ADR-0051 §5).
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

_API_PREFIX = "/api/v4"
_PAGE_LIMIT = 250
_MIN_REQUEST_INTERVAL = 0.2  # 5 requests per second
_MAX_429_RETRIES = 6
_MAX_BACKOFF_SECONDS = 60
_TIMEOUT_SECONDS = 30.0

Params = Sequence[tuple[str, Any]]


class AmoError(Exception):
    """Holds a status code and error class only, never a URL or a header."""

    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


class AmoAuthError(AmoError):
    """401/403: retrying cannot help, the sync loop must stop."""


class AmoRateLimitError(AmoError):
    """429 persisted past the retry budget."""


class AmoHttpError(AmoError):
    """Any other unexpected response."""


class AmoTransportError(AmoError):
    """No HTTP response at all: DNS, connection, timeout."""


class AmoClient:
    def __init__(
        self,
        base_url: str,
        token: SecretStr,
        *,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ):
        self._token = token
        self._sleep = sleep
        self._clock = clock
        self._next_request_at = 0.0
        # Redirects stay off: following one could carry the header to another host.
        self._http = httpx.Client(
            base_url=base_url,
            transport=transport,
            timeout=_TIMEOUT_SECONDS,
            follow_redirects=False,
        )

    def __repr__(self) -> str:
        return "AmoClient()"

    def close(self) -> None:
        self._http.close()

    def iter_pages(self, path: str, key: str, params: Params = ()) -> Iterator[list[dict]]:
        """Yields one list per page, following `_links.next`. 204 means no rows."""
        url = f"{_API_PREFIX}{path}"
        query: list[tuple[str, Any]] | None = [*params, ("limit", _PAGE_LIMIT)]
        seen: set[str] = set()
        while True:
            response = self._send(url, query)
            if response.status_code == 204:
                return
            self._require_ok(response)
            body = self._json(response)
            yield body.get("_embedded", {}).get(key, [])

            next_href = body.get("_links", {}).get("next", {}).get("href")
            if not next_href:
                return
            # Only path and query are taken, so the token cannot follow a foreign host.
            parts = urlsplit(next_href)
            url = f"{parts.path}?{parts.query}"
            query = None
            if url in seen:
                raise AmoHttpError("amo pagination returned the same page twice")
            seen.add(url)

    def get_object(self, path: str) -> dict | None:
        """Returns one object, or None when amo reports that it does not exist."""
        response = self._send(f"{_API_PREFIX}{path}", None)
        if response.status_code in (204, 404):
            return None
        self._require_ok(response)
        return self._json(response)

    def _send(self, url: str, params: list[tuple[str, Any]] | None) -> httpx.Response:
        for attempt in range(_MAX_429_RETRIES + 1):
            self._wait_for_slot()
            try:
                response = self._http.get(
                    url,
                    params=params,
                    headers={"Authorization": f"Bearer {self._token.get_secret_value()}"},
                )
            except httpx.TransportError as exc:
                raise AmoTransportError(f"amo transport failure: {type(exc).__name__}") from None
            if response.status_code in (401, 403):
                raise AmoAuthError("amo rejected the token", response.status_code)
            if response.status_code != 429:
                return response
            if attempt < _MAX_429_RETRIES:
                self._sleep(self._backoff(response, attempt))
        raise AmoRateLimitError("amo kept answering 429", 429)

    def _wait_for_slot(self) -> None:
        now = self._clock()
        wait = self._next_request_at - now
        if wait > 0:
            self._sleep(wait)
            now += wait
        self._next_request_at = now + _MIN_REQUEST_INTERVAL

    @staticmethod
    def _backoff(response: httpx.Response, attempt: int) -> float:
        retry_after = response.headers.get("Retry-After", "")
        if retry_after.isdigit():
            return int(retry_after)
        return min(2**attempt, _MAX_BACKOFF_SECONDS)

    @staticmethod
    def _require_ok(response: httpx.Response) -> None:
        if response.status_code != 200:
            raise AmoHttpError(
                f"unexpected amo status {response.status_code}", response.status_code
            )

    @staticmethod
    def _json(response: httpx.Response) -> dict:
        try:
            return response.json()
        except ValueError:
            raise AmoHttpError("amo returned invalid JSON", response.status_code) from None
