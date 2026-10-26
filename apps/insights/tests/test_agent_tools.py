import json

import httpx
import pytest

from insights import backend
from insights.context import auth_header, sources
from insights.tools import get_agent_response_times, get_funnel, list_agents

AGENT_ID = "02627f73-1292-4f83-af8c-485bc07a30f2"
FUNNEL = {
    "stages": [
        {"stage": "INTERESTED", "leads_reached": 10, "pct_from_prev": None, "pct_of_first": 100.0},
        {"stage": "VISIT_SCHEDULED", "leads_reached": 4, "pct_from_prev": 40.0, "pct_of_first": 40.0},
    ],
    "lost": 3,
    "filters": {"agent_id": AGENT_ID},
}


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


async def test_list_agents_path_params_and_trimmed_fields(monkeypatch, seen):
    agents = [{"id": "a1", "agency_id": "g1", "role": "AGENT", "active": True, "full_name": "Inés"}]
    _use(monkeypatch, seen, httpx.Response(200, json=agents))
    out = json.loads(await list_agents.ainvoke({}))
    assert seen[0].url.path == "/agents"
    assert dict(seen[0].url.params) == {"include_bots": "false", "active": "true", "limit": "200"}
    assert out["agents"] == [{"id": "a1", "full_name": "Inés", "role": "AGENT"}]
    assert sources.get() == [
        {
            "tool": "list_agents",
            "endpoint": "GET /agents",
            "params": {"include_bots": False, "active": True, "limit": 200},
        }
    ]


async def test_response_times_path_nulls_and_period(monkeypatch, seen):
    rows = [
        {"agent_id": "a1", "agent_name": None, "leads": 5, "avg_first_response_hours": None,
         "median_first_response_hours": 2.5, "never_answered": 1},
    ]
    _use(monkeypatch, seen, httpx.Response(200, json=rows))
    out = json.loads(await get_agent_response_times.ainvoke({}))
    assert seen[0].url.path == "/analytics/agent-response-time"
    assert seen[0].url.query == b""
    assert out["period"] == "full history (no date filter)"
    assert out["agents"][0]["agent_name"] == "no data"
    assert out["agents"][0]["avg_first_response_hours"] == "no data"
    assert out["agents"][0]["median_first_response_hours"] == 2.5
    assert sources.get()[0]["params"] == {}


async def test_funnel_forwards_exact_params(monkeypatch, seen):
    _use(monkeypatch, seen, httpx.Response(200, json=FUNNEL))
    out = json.loads(
        await get_funnel.ainvoke(
            {
                "agent_id": AGENT_ID,
                "created_from": "2026-08-01",
                "created_to": "2026-08-31",
                "operation_type": "sale",
            }
        )
    )
    assert seen[0].url.path == "/analytics/funnel"
    expected = {
        "created_from": "2026-08-01",
        "created_to": "2026-08-31",
        "agent_id": AGENT_ID,
        "operation_type": "SALE",
    }
    assert dict(seen[0].url.params) == expected
    assert sources.get()[0]["params"] == expected
    assert out["period"] == "leads created 2026-08-01 to 2026-08-31"
    assert out["filters"] == {"agent_id": AGENT_ID}
    assert out["stages"][0]["pct_from_prev"] == "no data"
    assert out["stages"][1]["pct_from_prev"] == 40.0


async def test_funnel_without_filters(monkeypatch, seen):
    _use(monkeypatch, seen, httpx.Response(200, json={**FUNNEL, "filters": {}}))
    out = json.loads(await get_funnel.ainvoke({}))
    assert seen[0].url.query == b""
    assert out["period"] == "all leads ever created"
    assert sources.get()[0]["params"] == {}


async def test_funnel_open_ended_period(monkeypatch, seen):
    _use(monkeypatch, seen, httpx.Response(200, json=FUNNEL))
    out = json.loads(await get_funnel.ainvoke({"created_from": "2026-08-01"}))
    assert out["period"] == "leads created 2026-08-01 to (no end)"


@pytest.mark.parametrize(
    "args",
    [
        {"agent_id": "not-a-uuid"},
        {"created_from": "2026-13-01"},
        {"created_to": "20260801"},
        {"created_from": "01/08/2026"},
        {"operation_type": "LEASE"},
    ],
)
async def test_invalid_input_makes_no_request(monkeypatch, seen, args):
    _use(monkeypatch, seen, httpx.Response(200, json=FUNNEL))
    out = await get_funnel.ainvoke(args)
    assert out.startswith("Invalid")
    assert seen == []
    assert sources.get() == []


async def test_funnel_403_mapped_by_status(monkeypatch, seen):
    _use(monkeypatch, seen, httpx.Response(403, json={"detail": "secret detail"}))
    out = await get_funnel.ainvoke({})
    assert "not allowed" in out
    assert "secret detail" not in out
    assert sources.get() == []


async def test_funnel_422_is_invalid_date_range(monkeypatch, seen):
    _use(monkeypatch, seen, httpx.Response(422, json={"detail": "secret detail"}))
    out = await get_funnel.ainvoke({"created_from": "2026-09-01", "created_to": "2026-08-01"})
    assert "Invalid date range" in out
    assert "secret detail" not in out
    assert sources.get() == []


@pytest.mark.parametrize("tool", [list_agents, get_agent_response_times])
async def test_failures_leave_sources_empty(monkeypatch, seen, tool):
    _use(monkeypatch, seen, httpx.Response(500))
    assert "unavailable" in await tool.ainvoke({})
    _use(monkeypatch, seen, httpx.ConnectError("down"))
    assert "unavailable" in await tool.ainvoke({})
    assert sources.get() == []


def test_normalize_rounds_floats_and_keeps_the_rest():
    from insights.tools import _normalize

    out = _normalize(
        {
            "median": 31.3372382241667,
            "leads": 7,
            "flag": True,
            "missing": None,
            "label": "no data",
            "nested": [{"pct": 33.333333, "n": 2}],
        }
    )
    assert out == {
        "median": 31.34,
        "leads": 7,
        "flag": True,
        "missing": "no data",
        "label": "no data",
        "nested": [{"pct": 33.33, "n": 2}],
    }
    assert isinstance(out["leads"], int) and out["flag"] is True


async def test_response_times_rounds_hours(monkeypatch, seen):
    rows = [
        {"agent_id": "a1", "agent_name": "Inés", "leads": 5,
         "avg_first_response_hours": 40.987654321,
         "median_first_response_hours": 31.3372382241667, "never_answered": 1},
    ]
    _use(monkeypatch, seen, httpx.Response(200, json=rows))
    out = json.loads(await get_agent_response_times.ainvoke({}))
    assert out["period"] == "full history (no date filter)"
    assert out["agents"][0]["median_first_response_hours"] == 31.34
    assert out["agents"][0]["avg_first_response_hours"] == 40.99
    assert out["agents"][0]["leads"] == 5
