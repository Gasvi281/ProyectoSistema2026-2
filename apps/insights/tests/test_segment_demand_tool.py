import json

import httpx
import pytest

from insights import backend
from insights.context import auth_header, sources
from insights.tools import TOOLS, segment_demand

PERIOD = "all time (no date filter), all listings including paused and closed"


def _row(n, **over):
    row = {
        "listing_id": f"00000000-0000-0000-0000-{n:012d}",
        "operation_type": "SALE",
        "city": "Medellín",
        "neighborhood": "Laureles",
        "property_type": "APARTMENT",
        "asking_price": "450000000.00",
        "views": 100,
        "leads": 4,
        "visits": 2,
        "won": 1,
    }
    row.update(over)
    return row


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


def _ok(rows):
    return httpx.Response(200, json=rows)


async def _run(monkeypatch, seen, rows, **args):
    _use(monkeypatch, seen, _ok(rows))
    return json.loads(await segment_demand.ainvoke(args))


def _names(out):
    return [s["segment"] for s in out["segments"]]


def test_registered_in_tools():
    assert segment_demand in TOOLS


async def test_one_request_with_limit_500_and_source(monkeypatch, seen):
    out = await _run(monkeypatch, seen, [_row(1)], by="NEIGHBORHOOD", operation_type="sale")
    assert len(seen) == 1
    assert seen[0].url.path == "/analytics/listing-performance"
    assert dict(seen[0].url.params) == {"limit": "500"}
    assert sources.get() == [
        {
            "tool": "segment_demand",
            "endpoint": "GET /analytics/listing-performance",
            "params": {"limit": 500},
        }
    ]
    assert out["period"] == PERIOD
    assert out["by"] == "neighborhood"
    assert out["order"] == "most leads first"


async def test_hand_checked_segment_and_totals(monkeypatch, seen):
    rows = [
        _row(1, neighborhood="Castilla", views=150, leads=20, visits=1, won=1),
        _row(2, neighborhood="Castilla", views=54, leads=12, visits=0, won=1),
        _row(3, neighborhood="Belén", views=10, leads=0, visits=0, won=0),
    ]
    out = await _run(monkeypatch, seen, rows, by="neighborhood")
    assert out["segments"][0] == {
        "segment": "Castilla",
        "listings": 2,
        "views": 204,
        "leads": 32,
        "visits": 1,
        "won": 2,
        "visit_pct": 3.13,  # 1/32 = 3.125 -> 3.13 (half-up)
        "won_pct": 6.25,
    }
    assert out["segments"][1]["visit_pct"] == out["segments"][1]["won_pct"] == "no data"
    assert out["totals"] == {
        "listings": 3,
        "views": 214,
        "leads": 32,
        "visits": 1,
        "won": 2,
        "visit_pct": 3.13,
        "won_pct": 6.25,
    }
    assert "listing_id" not in json.dumps(out)


async def test_accent_and_case_variants_merge_display_most_frequent(monkeypatch, seen):
    rows = [
        _row(1, neighborhood="usaquen"),
        _row(2, neighborhood="Usaquén"),
        _row(3, neighborhood="Usaquén"),
        _row(4, neighborhood="USAQUÉN "),
    ]
    out = await _run(monkeypatch, seen, rows, by="neighborhood")
    assert _names(out) == ["Usaquén"]
    assert out["segments"][0]["listings"] == 4


async def test_spelling_tie_is_alphabetical_regardless_of_order(monkeypatch, seen):
    for names in (["Usaquén", "usaquen"], ["usaquen", "Usaquén"]):
        rows = [_row(i, neighborhood=n) for i, n in enumerate(names)]
        out = await _run(monkeypatch, seen, rows, by="neighborhood")
        assert _names(out) == ["Usaquén"]  # "U" < "u"


async def test_null_and_blank_values_form_one_no_data_segment(monkeypatch, seen):
    rows = [
        _row(1, neighborhood=None, leads=1),
        _row(2, neighborhood="", leads=1),
        _row(3, neighborhood="   ", leads=1),
        _row(4, neighborhood="Laureles", leads=9),
    ]
    out = await _run(monkeypatch, seen, rows, by="neighborhood")
    assert _names(out) == ["Laureles", "no data"]
    assert out["segments"][1]["listings"] == 3


async def test_order_is_leads_desc_with_name_tie_break(monkeypatch, seen):
    rows = [
        _row(1, neighborhood="Calasanz", leads=5),
        _row(2, neighborhood="Belén", leads=5),
        _row(3, neighborhood="El Tesoro", leads=9),
        _row(4, neighborhood="Aranjuez", leads=1),
    ]
    out = await _run(monkeypatch, seen, rows, by="neighborhood")
    assert _names(out) == ["El Tesoro", "Belén", "Calasanz", "Aranjuez"]


async def test_cap_15_with_totals_over_all_segments(monkeypatch, seen):
    rows = [_row(i, neighborhood=f"Barrio {i:02d}", leads=i, visits=0, won=0) for i in range(1, 39)]
    out = await _run(monkeypatch, seen, rows, by="neighborhood")
    assert out["total_segments"] == 38
    assert out["shown_segments"] == 15 == len(out["segments"])
    assert out["segments"][0]["segment"] == "Barrio 38"
    assert out["totals"]["listings"] == 38
    assert out["totals"]["leads"] == sum(range(1, 39))


async def test_group_by_property_type_with_operation_filter(monkeypatch, seen):
    rows = [
        _row(1, property_type="HOUSE", operation_type="RENT", leads=3),
        _row(2, property_type="STUDIO", operation_type="RENT", leads=7),
        _row(3, property_type="STUDIO", operation_type="SALE", leads=50),
    ]
    out = await _run(monkeypatch, seen, rows, by="property_type", operation_type="rent")
    assert _names(out) == ["STUDIO", "HOUSE"]
    assert out["totals"]["listings"] == 2 and out["totals"]["leads"] == 10


async def test_group_by_operation_type(monkeypatch, seen):
    rows = [_row(1, leads=2), _row(2, operation_type="RENT", leads=6), _row(3, leads=1)]
    out = await _run(monkeypatch, seen, rows, by="operation_type")
    assert [(s["segment"], s["listings"]) for s in out["segments"]] == [("RENT", 1), ("SALE", 2)]


async def test_lower_bound_only_when_backend_returns_exactly_500(monkeypatch, seen):
    out = await _run(monkeypatch, seen, [_row(i) for i in range(500)], by="neighborhood")
    assert out["total_is_lower_bound"] is True

    out = await _run(monkeypatch, seen, [_row(i) for i in range(207)], by="neighborhood")
    assert "total_is_lower_bound" not in out


@pytest.mark.parametrize(
    "args",
    [
        {"by": "price_band"},
        {"by": ""},
        {"by": "city"},
        {"by": "neighborhood", "operation_type": "LEASE"},
        {"by": "operation_type", "operation_type": "SALE"},
    ],
)
async def test_invalid_input_makes_no_request(monkeypatch, seen, args):
    _use(monkeypatch, seen, _ok([_row(1)]))
    out = await segment_demand.ainvoke(args)
    assert out.startswith("Invalid")
    assert seen == []
    assert sources.get() == []


@pytest.mark.parametrize(
    "status, fragment",
    [(401, "sign in again"), (403, "not allowed"), (404, "not available"), (500, "unavailable")],
)
async def test_status_mapping_leaves_sources_empty(monkeypatch, seen, status, fragment):
    _use(monkeypatch, seen, httpx.Response(status, json={"detail": "secret detail"}))
    out = await segment_demand.ainvoke({"by": "neighborhood"})
    assert fragment in out
    assert "secret detail" not in out
    assert sources.get() == []


async def test_connection_error_is_unavailable(monkeypatch, seen):
    _use(monkeypatch, seen, httpx.ConnectError("down"))
    assert "unavailable" in await segment_demand.ainvoke({"by": "neighborhood"})
    assert sources.get() == []
