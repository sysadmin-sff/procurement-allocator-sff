"""The read-only amo client against mocked HTTP (ADR-0051 §4, §5)."""

import logging

import httpx
import pytest
from pydantic import SecretStr

from app.measurements.amo_client import (
    AmoAuthError,
    AmoClient,
    AmoHttpError,
    AmoRateLimitError,
    AmoTransportError,
)
from tests.measurements.amo_fixtures import BASE_URL, TOKEN, load, page, rows, transport


class FakeTime:
    def __init__(self):
        self.now = 1000.0
        self.sleeps: list[float] = []

    def clock(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def make_client(handler, time_source: FakeTime | None = None) -> AmoClient:
    fake = time_source or FakeTime()
    return AmoClient(
        BASE_URL,
        SecretStr(TOKEN),
        transport=transport(handler),
        sleep=fake.sleep,
        clock=fake.clock,
    )


def collect(client: AmoClient, params=()) -> list[dict]:
    return [row for batch in client.iter_pages("/tasks", "tasks", params) for row in batch]


def test_204_means_empty():
    client = make_client(lambda request: httpx.Response(204))
    assert collect(client) == []


def test_real_task_page_is_returned():
    body = load("tasks_page.json")
    client = make_client(lambda request: httpx.Response(200, json=body))
    assert collect(client) == body["_embedded"]["tasks"]


def test_every_first_request_asks_for_250_rows_and_keeps_filters():
    seen = []

    def handler(request):
        seen.append(request.url)
        return httpx.Response(204)

    collect(make_client(handler), [("filter[task_type][]", 2), ("filter[task_type][]", 4410970)])
    assert seen[0].path == "/api/v4/tasks"
    assert seen[0].params["limit"] == "250"
    assert seen[0].params.get_list("filter[task_type][]") == ["2", "4410970"]


def test_pagination_follows_links_next():
    first, second = rows("tasks_page.json", "tasks")
    urls = []

    def handler(request):
        urls.append(str(request.url))
        if "page=2" in str(request.url):
            return httpx.Response(200, json=page("tasks", [second]))
        return httpx.Response(
            200, json=page("tasks", [first], f"{BASE_URL}/api/v4/tasks?limit=250&page=2")
        )

    assert [row["id"] for row in collect(make_client(handler))] == [first["id"], second["id"]]
    assert len(urls) == 2


def test_next_link_on_another_host_never_receives_the_token():
    hosts = []

    def handler(request):
        hosts.append(request.url.host)
        if request.url.params.get("page") == "2":
            return httpx.Response(204)
        return httpx.Response(
            200, json=page("tasks", [], "https://evil.example/api/v4/tasks?limit=250&page=2")
        )

    collect(make_client(handler))
    assert hosts == ["example.amocrm.com", "example.amocrm.com"]


def test_repeating_next_link_stops_instead_of_looping():
    def handler(request):
        return httpx.Response(
            200, json=page("tasks", [], f"{BASE_URL}/api/v4/tasks?limit=250&page=2")
        )

    with pytest.raises(AmoHttpError, match="pagination"):
        collect(make_client(handler))


def test_429_with_retry_after_waits_that_long():
    fake = FakeTime()
    responses = [httpx.Response(429, headers={"Retry-After": "7"}), httpx.Response(204)]
    client = make_client(lambda request: responses.pop(0), fake)
    assert collect(client) == []
    assert 7 in fake.sleeps


def test_429_without_retry_after_backs_off_exponentially():
    fake = FakeTime()
    responses = [httpx.Response(429), httpx.Response(429), httpx.Response(429), httpx.Response(204)]
    client = make_client(lambda request: responses.pop(0), fake)
    collect(client)
    assert [delay for delay in fake.sleeps if delay >= 1] == [1, 2, 4]


def test_429_gives_up_after_the_retry_budget():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(429)

    with pytest.raises(AmoRateLimitError) as exc_info:
        collect(make_client(handler))
    assert exc_info.value.status_code == 429
    assert len(calls) > 1


@pytest.mark.parametrize("status", [401, 403])
def test_auth_failures_raise_without_retry(status):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(status)

    with pytest.raises(AmoAuthError) as exc_info:
        collect(make_client(handler))
    assert exc_info.value.status_code == status
    assert len(calls) == 1


def test_server_error_keeps_its_status_code():
    with pytest.raises(AmoHttpError) as exc_info:
        collect(make_client(lambda request: httpx.Response(502)))
    assert exc_info.value.status_code == 502


def test_redirects_are_not_followed():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(302, headers={"Location": "https://evil.example/"})

    with pytest.raises(AmoHttpError):
        collect(make_client(handler))
    assert len(calls) == 1


def test_network_failure_is_wrapped_without_the_token():
    def handler(request):
        raise httpx.ConnectError("connection refused")

    with pytest.raises(AmoTransportError) as exc_info:
        collect(make_client(handler))
    assert TOKEN not in str(exc_info.value)


def test_get_object_returns_the_body():
    body = load("task_with_result.json")
    client = make_client(lambda request: httpx.Response(200, json=body))
    assert client.get_object("/tasks/1") == body


@pytest.mark.parametrize("status", [204, 404])
def test_get_object_returns_none_when_absent(status):
    client = make_client(lambda request: httpx.Response(status))
    assert client.get_object("/tasks/1") is None


def test_get_object_still_raises_on_auth_failure():
    client = make_client(lambda request: httpx.Response(401))
    with pytest.raises(AmoAuthError):
        client.get_object("/tasks/1")


def test_requests_are_limited_to_five_per_second():
    fake = FakeTime()
    client = make_client(lambda request: httpx.Response(204), fake)
    for _ in range(3):
        collect(client)
    assert fake.sleeps == pytest.approx([0.2, 0.2])


@pytest.mark.parametrize("name", ["post", "put", "patch", "delete", "request", "head", "options"])
def test_client_has_no_write_methods(name):
    assert not hasattr(AmoClient, name)
    assert not hasattr(make_client(lambda request: httpx.Response(204)), name)


def test_every_request_is_a_get():
    methods = []

    def handler(request):
        methods.append(request.method)
        return httpx.Response(204)

    client = make_client(handler)
    collect(client)
    client.get_object("/tasks/1")
    assert set(methods) == {"GET"}


def test_token_travels_only_in_the_authorization_header():
    captured = []

    def handler(request):
        captured.append(request)
        return httpx.Response(204)

    collect(make_client(handler))
    assert captured[0].headers["authorization"] == f"Bearer {TOKEN}"
    assert TOKEN not in str(captured[0].url)


def test_token_is_not_in_repr():
    client = make_client(lambda request: httpx.Response(204))
    assert TOKEN not in repr(client)
    assert TOKEN not in str(client)


def test_token_is_not_logged(caplog):
    caplog.set_level(logging.DEBUG)
    collect(make_client(lambda request: httpx.Response(204)))
    assert TOKEN not in caplog.text


def test_httpx_loggers_are_raised_to_warning():
    assert logging.getLogger("httpx").level == logging.WARNING
    assert logging.getLogger("httpcore").level == logging.WARNING
