"""Loads anonymized amo responses and builds mock transports (no real HTTP)."""

import copy
import json
from collections.abc import Callable
from pathlib import Path

import httpx

FIXTURES = Path(__file__).parent / "fixtures" / "amo"
BASE_URL = "https://example.amocrm.com"
TOKEN = "test-token-not-a-real-secret"


def load(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def rows(name: str, key: str) -> list[dict]:
    return load(name)["_embedded"][key]


def page(key: str, items: list[dict], next_href: str | None = None) -> dict:
    links: dict = {"self": {"href": f"{BASE_URL}/api/v4/{key}?page=1&limit=250"}}
    if next_href is not None:
        links["next"] = {"href": next_href}
    return {"_page": 1, "_links": links, "_embedded": {key: copy.deepcopy(items)}}


def task(**overrides) -> dict:
    """A task with the real shape: result is [] unless overridden."""
    return {**load("task_empty_result.json"), **overrides}


def field_event(event_id, lead_id, created_at, before=None, after=None) -> dict:
    """A Site Visit Result change with the real shape; None means amo's empty []."""
    template = rows("events_field_784029.json", "events")[1]
    base = template["value_after"][0]["custom_field_value"]

    def value(enum_id):
        return [] if enum_id is None else [{"custom_field_value": {**base, "enum_id": enum_id}}]

    return {
        **template,
        "id": event_id,
        "entity_id": lead_id,
        "created_at": created_at,
        "value_before": value(before),
        "value_after": value(after),
    }


def deadline_event(event_id, task_id, created_at, before, after) -> dict:
    template = rows("events_task_deadline_changed.json", "events")[0]
    return {
        **template,
        "id": event_id,
        "entity_id": task_id,
        "created_at": created_at,
        "value_before": [{"task_deadline": {"timestamp": before}}],
        "value_after": [{"task_deadline": {"timestamp": after}}],
    }


def transport(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.MockTransport:
    return httpx.MockTransport(handler)
