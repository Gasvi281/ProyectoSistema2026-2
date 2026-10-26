import json

import httpx
import pytest

from insights import backend
from insights.context import auth_header, sources
from insights.tools import TOOLS, get_lost_reasons

REASONS = [
    {"reason": "PRICE", "leads": 600, "pct": 41.18},
    {"reason": "NO_RESPONSE", "leads": 500, "pct": 34.32},
    {"reason": "OTHER", "leads": 357, "pct": 24.5},
]


@pytest.fixture(autouse=True)
def _ctx():
    auth_header.set("Bearer t")
    sources.set([])


@pytest.fixture
def seen():
    return []


def _use(monkeypatch, seen, response):
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if isinstance(response, Exception):
            raise response
        return response

    monkeypatch.setattr(backend, "_transport", httpx.MockTransport(handler))


def test_registered_in_tools():
    assert get_lost_reasons in TOOLS


async def test_default_window_is_730_days(monkeypatch, seen):
    _use(monkeypatch, seen, httpx.Response(200, json=REASONS))
    out = json.loads(await get_lost_reasons.ainvoke({}))
    assert seen[0].url.path == "/analytics/lost-reasons"
    assert dict(seen[0].url.params) == {"days": "730"}
    assert out["period"] == "all lost leads on record (last 730 days)"
    assert sources.get() == [
        {
            "tool": "get_lost_reasons",
            "endpoint": "GET /analytics/lost-reasons",
            "params": {"days": 730},
        }
    ]


async def test_explicit_days_forwarded_and_in_period(monkeypatch, seen):
    _use(monkeypatch, seen, httpx.Response(200, json=REASONS))
    out = json.loads(await get_lost_reasons.ainvoke({"days": 90}))
    assert dict(seen[0].url.params) == {"days": "90"}
    assert sources.get()[0]["params"] == {"days": 90}
    assert out["period"] == "leads lost in the last 90 days, counted back from today"


async def test_explicit_730_uses_the_on_record_period(monkeypatch, seen):
    _use(monkeypatch, seen, httpx.Response(200, json=REASONS))
    out = json.loads(await get_lost_reasons.ainvoke({"days": 730}))
    assert out["period"] == "all lost leads on record (last 730 days)"


async def test_total_computed_in_code_and_backend_order_kept(monkeypatch, seen):
    _use(monkeypatch, seen, httpx.Response(200, json=REASONS))
    out = json.loads(await get_lost_reasons.ainvoke({}))
    assert out["total_lost_with_reason"] == 1457
    assert out["order"] == "most lost leads first"
    assert [r["reason"] for r in out["reasons"]] == ["PRICE", "NO_RESPONSE", "OTHER"]
    assert out["reasons"][0] == {"reason": "PRICE", "leads": 600, "pct": 41.18}


async def test_empty_window_has_zero_total_and_keeps_period(monkeypatch, seen):
    _use(monkeypatch, seen, httpx.Response(200, json=[]))
    out = json.loads(await get_lost_reasons.ainvoke({"days": 30}))
    assert out["total_lost_with_reason"] == 0
    assert out["reasons"] == []
    assert "last 30 days" in out["period"]
    assert len(sources.get()) == 1  # un 200 vacío sigue siendo una fuente válida


@pytest.mark.parametrize("days", [0, -1, 731, 10_000])
async def test_invalid_days_makes_no_request(monkeypatch, seen, days):
    _use(monkeypatch, seen, httpx.Response(200, json=REASONS))
    out = await get_lost_reasons.ainvoke({"days": days})
    assert out.startswith("Invalid days")
    assert seen == []
    assert sources.get() == []


@pytest.mark.parametrize("days", [1, 730])
async def test_boundary_days_are_accepted(monkeypatch, seen, days):
    _use(monkeypatch, seen, httpx.Response(200, json=REASONS))
    await get_lost_reasons.ainvoke({"days": days})
    assert dict(seen[0].url.params) == {"days": str(days)}


async def test_422_is_invalid_days(monkeypatch, seen):
    _use(monkeypatch, seen, httpx.Response(422, json={"detail": "secret detail"}))
    out = await get_lost_reasons.ainvoke({"days": 90})
    assert out.startswith("Invalid days")
    assert "secret detail" not in out
    assert sources.get() == []


@pytest.mark.parametrize(
    "status, fragment",
    [(401, "sign in again"), (403, "not allowed"), (404, "not available"), (500, "unavailable")],
)
async def test_status_mapping_leaves_sources_empty(monkeypatch, seen, status, fragment):
    _use(monkeypatch, seen, httpx.Response(status, json={"detail": "secret detail"}))
    out = await get_lost_reasons.ainvoke({})
    assert fragment in out
    assert "secret detail" not in out
    assert sources.get() == []


async def test_connection_error_is_unavailable(monkeypatch, seen):
    _use(monkeypatch, seen, httpx.ConnectError("down"))
    assert "unavailable" in await get_lost_reasons.ainvoke({})
    assert sources.get() == []
