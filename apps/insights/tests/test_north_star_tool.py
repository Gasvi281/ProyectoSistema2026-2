import json

import httpx
import pytest

from insights import backend
from insights.context import auth_header, sources
from insights.tools import get_north_star

NORTH_STAR = {
    "leads": 40,
    "median_first_response_hours": None,
    "pct_with_follow_up": 62.5,
    "lead_to_visit_conversion_pct": 30.0,
    "pct_lost_within_48h": 5.0,
    "stage_conversion": [
        {"stage": "INTERESTED", "sort_order": 1, "leads_reached": 40,
         "leads_prev_stage": None, "pct_from_prev": None},
    ],
}


@pytest.fixture(autouse=True)
def _ctx():
    auth_header.set("Bearer t")
    sources.set([])


def _use(monkeypatch, handler):
    monkeypatch.setattr(backend, "_transport", httpx.MockTransport(handler))


async def test_null_metric_is_no_data_and_source_recorded(monkeypatch):
    _use(monkeypatch, lambda r: httpx.Response(200, json=NORTH_STAR))
    out = json.loads(await get_north_star.ainvoke({}))
    assert out["median_first_response_hours"] == "no data"
    assert out["stage_conversion"][0]["pct_from_prev"] == "no data"
    assert out["leads"] == 40
    assert "full history" in out["period"]
    assert sources.get() == [
        {"tool": "get_north_star", "endpoint": "GET /analytics/north-star", "params": {}}
    ]


async def test_5xx_leaves_sources_empty(monkeypatch):
    _use(monkeypatch, lambda r: httpx.Response(500, json={"code": "x", "detail": "boom"}))
    out = await get_north_star.ainvoke({})
    assert "unavailable" in out
    assert "boom" not in out
    assert sources.get() == []


async def test_401_maps_by_status_and_leaves_sources_empty(monkeypatch):
    _use(monkeypatch, lambda r: httpx.Response(401, json={"detail": "anything"}))
    out = await get_north_star.ainvoke({})
    assert "session" in out
    assert sources.get() == []


async def test_connection_error_leaves_sources_empty(monkeypatch):
    def boom(request):
        raise httpx.ConnectError("down")

    _use(monkeypatch, boom)
    assert "unavailable" in await get_north_star.ainvoke({})
    assert sources.get() == []
