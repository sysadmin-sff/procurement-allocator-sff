"""An in-memory amo behind httpx.MockTransport, answering like the real API."""

import re
from collections.abc import Callable

import httpx

from tests.measurements.amo_fixtures import BASE_URL, load, page


class FakeAmo:
    def __init__(self):
        self.tasks: dict[int, dict] = {}
        self.events: list[dict] = []
        self.leads: dict[int, dict] = {}
        self.custom_fields: dict = load("custom_fields.json")
        self.users: dict = load("users.json")
        self.pipelines: dict = load("pipelines.json")
        self.requests: list[httpx.Request] = []
        self.fail_when: Callable[[httpx.Request], httpx.Response | None] | None = None
        self.page_size = 250

    def add_task(self, task: dict) -> None:
        self.tasks[task["id"]] = task

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self._handle)

    def calls_to(self, path: str) -> list[httpx.Request]:
        return [request for request in self.requests if request.url.path == f"/api/v4{path}"]

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.fail_when is not None:
            failure = self.fail_when(request)
            if failure is not None:
                return failure

        path = request.url.path.removeprefix("/api/v4")
        params = request.url.params
        one_task = re.fullmatch(r"/tasks/(\d+)", path)
        if one_task:
            task = self.tasks.get(int(one_task.group(1)))
            return httpx.Response(200, json=task) if task else httpx.Response(404)
        if path == "/tasks":
            return self._paged("tasks", self._select_tasks(params), request)
        if path == "/events":
            return self._paged("events", self._select_events(params), request)
        if path == "/leads":
            wanted = {int(value) for value in params.get_list("filter[id][]")}
            found = [lead for lead_id, lead in self.leads.items() if lead_id in wanted]
            return self._paged("leads", found, request)
        if path == "/leads/custom_fields":
            return httpx.Response(200, json=self.custom_fields)
        if path == "/users":
            return httpx.Response(200, json=self.users)
        if path == "/leads/pipelines":
            return httpx.Response(200, json=self.pipelines)
        raise AssertionError(f"unexpected amo call: {request.url}")

    def _select_tasks(self, params) -> list[dict]:
        types = {int(value) for value in params.get_list("filter[task_type][]")}
        since = int(params.get("filter[updated_at][from]", 0))
        return [
            task
            for task in self.tasks.values()
            if (not types or task["task_type_id"] in types) and task["updated_at"] >= since
        ]

    def _select_events(self, params) -> list[dict]:
        since = int(params.get("filter[created_at][from]", 0))
        event_type = params.get("filter[type]")
        entity = params.get("filter[entity]")
        entity_ids = {int(value) for value in params.get_list("filter[entity_id][]")}
        return [
            event
            for event in self.events
            if event["created_at"] >= since
            and (event_type is None or event["type"] == event_type)
            and (entity is None or event["entity_type"] == entity)
            and (not entity_ids or event["entity_id"] in entity_ids)
        ]

    def _paged(self, key: str, rows: list[dict], request: httpx.Request) -> httpx.Response:
        if not rows:
            return httpx.Response(204)
        number = int(request.url.params.get("page", 1))
        start = (number - 1) * self.page_size
        chunk = rows[start : start + self.page_size]
        next_href = None
        if start + self.page_size < len(rows):
            query = request.url.params.set("page", str(number + 1))
            next_href = f"{BASE_URL}{request.url.path}?{query}"
        return httpx.Response(200, json=page(key, chunk, next_href))
