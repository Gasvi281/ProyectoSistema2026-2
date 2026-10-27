import json

import httpx
import pytest

from insights import backend
from insights.context import auth_header, sources
from insights.tools import TOOLS, _pct, get_listing_performance

PERIOD = "all time (no date filter), all listings including paused and closed"


def _row(n, **over):
    row = {
        "listing_id": f"00000000-0000-0000-0000-{n:012d}",
        "operation_type": "SALE",
        "city": "Bogotá",
        "neighborhood": "Chapinero",
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
    return json.loads(await get_listing_performance.ainvoke(args))


def test_registered_in_tools():
    assert get_listing_performance in TOOLS


@pytest.mark.parametrize(
    "n, of, expected",
    [(1, 3, 33.33), (2, 3, 66.67), (1, 8, 12.5), (1, 32, 3.13), (0, 5, 0.0), (5, 0, None)],
)
def test_pct_is_half_up_and_none_without_base(n, of, expected):
    assert _pct(n, of) == expected  # 1/32 = 3.125 -> 3.13 (half-up, no banker's rounding)


async def test_one_request_with_limit_500_and_source(monkeypatch, seen):
    out = await _run(monkeypatch, seen, [_row(1)], operation_type="rent", sort_by="LEADS")
    assert len(seen) == 1
    assert seen[0].url.path == "/analytics/listing-performance"
    assert dict(seen[0].url.params) == {"limit": "500"}  # los filtros no viajan al backend
    assert sources.get() == [
        {
            "tool": "get_listing_performance",
            "endpoint": "GET /analytics/listing-performance",
            "params": {"limit": 500},
        }
    ]
    assert out["period"] == PERIOD


async def test_row_fields_rates_and_price(monkeypatch, seen):
    out = await _run(monkeypatch, seen, [_row(1, views=204, leads=32, visits=1, won=2)])
    assert out["listings"] == [
        {
            "neighborhood": "Chapinero",
            "city": "Bogotá",
            "property_type": "APARTMENT",
            "operation_type": "SALE",
            "asking_price": "$450.000.000",
            "views": 204,
            "leads": 32,
            "visits": 1,
            "won": 2,
            "visit_pct": 3.13,
            "won_pct": 6.25,
        }
    ]
    assert "listing_id" not in json.dumps(out)


async def test_totals_over_all_filtered_rows_before_the_cap(monkeypatch, seen):
    rows = [_row(i, views=100 + i, leads=3, visits=1, won=1) for i in range(12)]
    out = await _run(monkeypatch, seen, rows)
    assert out["total_count"] == 12
    assert out["shown_count"] == 10 == len(out["listings"])
    assert out["totals"] == {
        "views": sum(100 + i for i in range(12)),
        "leads": 36,
        "visits": 12,
        "won": 12,
        "visit_pct": 33.33,
        "won_pct": 33.33,
    }


async def test_default_sort_is_views_desc_with_listing_id_tie_break(monkeypatch, seen):
    rows = [
        _row(3, views=204, neighborhood="C"),
        _row(1, views=204, neighborhood="A"),
        _row(2, views=204, neighborhood="B"),
        _row(4, views=300, neighborhood="TOP"),
        _row(5, views=10, neighborhood="LOW"),
    ]
    out = await _run(monkeypatch, seen, rows)
    assert out["order"] == "most views first"
    assert [r["neighborhood"] for r in out["listings"]] == ["TOP", "A", "B", "C", "LOW"]


@pytest.mark.parametrize("field", ["leads", "visits", "won"])
async def test_sort_by_other_fields(monkeypatch, seen, field):
    rows = [_row(1, **{field: 1}), _row(2, **{field: 9}), _row(3, **{field: 5})]
    out = await _run(monkeypatch, seen, rows, sort_by=field)
    assert out["order"] == f"most {field} first"
    assert [r[field] for r in out["listings"]] == [9, 5, 1]


async def test_cap_keeps_the_top_ten(monkeypatch, seen):
    rows = [_row(i, views=i) for i in range(1, 16)]
    out = await _run(monkeypatch, seen, rows)
    assert [r["views"] for r in out["listings"]] == list(range(15, 5, -1))


async def test_operation_type_filter_is_case_insensitive(monkeypatch, seen):
    rows = [_row(1), _row(2, operation_type="RENT", views=7), _row(3, operation_type="RENT")]
    out = await _run(monkeypatch, seen, rows, operation_type="rent")
    assert out["total_count"] == 2
    assert {r["operation_type"] for r in out["listings"]} == {"RENT"}


@pytest.mark.parametrize("typed", ["usaquen", "USAQUÉN", "  Usaquén ", "usaquén"])
async def test_neighborhood_filter_ignores_case_and_accents(monkeypatch, seen, typed):
    rows = [_row(1, neighborhood="Usaquén"), _row(2, neighborhood="Chapinero")]
    out = await _run(monkeypatch, seen, rows, neighborhood=typed)
    assert [r["neighborhood"] for r in out["listings"]] == ["Usaquén"]
    assert out["total_count"] == 1


async def test_neighborhood_is_an_exact_match_not_a_substring(monkeypatch, seen):
    rows = [_row(1, neighborhood="Chapinero Alto"), _row(2, neighborhood="Chapinero")]
    out = await _run(monkeypatch, seen, rows, neighborhood="chapinero")
    assert [r["neighborhood"] for r in out["listings"]] == ["Chapinero"]


async def test_no_match_returns_zero_totals_and_no_rates(monkeypatch, seen):
    out = await _run(monkeypatch, seen, [_row(1)], neighborhood="Narnia")
    assert out["total_count"] == 0 and out["shown_count"] == 0
    assert out["listings"] == []
    assert out["totals"]["views"] == 0
    assert out["totals"]["visit_pct"] == out["totals"]["won_pct"] == "no data"


async def test_zero_leads_gives_no_data_rates(monkeypatch, seen):
    out = await _run(monkeypatch, seen, [_row(1, views=50, leads=0, visits=0, won=0)])
    row = out["listings"][0]
    assert row["visit_pct"] == row["won_pct"] == "no data"
    assert row["views"] == 50 and row["leads"] == 0


async def test_lower_bound_only_when_backend_returns_exactly_500(monkeypatch, seen):
    out = await _run(monkeypatch, seen, [_row(i) for i in range(500)])
    assert out["total_count"] == 500 and out["total_is_lower_bound"] is True

    out = await _run(monkeypatch, seen, [_row(i) for i in range(207)])
    assert out["total_count"] == 207 and "total_is_lower_bound" not in out


async def test_lower_bound_is_set_even_when_a_filter_narrows_the_rows(monkeypatch, seen):
    rows = [_row(i, operation_type="SALE" if i else "RENT") for i in range(500)]
    out = await _run(monkeypatch, seen, rows, operation_type="RENT")
    assert out["total_count"] == 1 and out["total_is_lower_bound"] is True


async def test_accented_text_passes_through_utf8(monkeypatch, seen):
    rows = [_row(1, city="Medellín", neighborhood="Usaquén")]
    _use(monkeypatch, seen, _ok(rows))
    raw = await get_listing_performance.ainvoke({})
    assert "Medellín" in raw and "Usaquén" in raw and "\\u" not in raw


@pytest.mark.parametrize(
    "args",
    [
        {"operation_type": "LEASE"},
        {"neighborhood": ""},
        {"neighborhood": "   "},
        {"sort_by": "price"},
        {"sort_by": ""},
    ],
)
async def test_invalid_input_makes_no_request(monkeypatch, seen, args):
    _use(monkeypatch, seen, _ok([_row(1)]))
    out = await get_listing_performance.ainvoke(args)
    assert out.startswith("Invalid")
    assert seen == []
    assert sources.get() == []


@pytest.mark.parametrize(
    "status, fragment",
    [(401, "sign in again"), (403, "not allowed"), (404, "not available"), (500, "unavailable")],
)
async def test_status_mapping_leaves_sources_empty(monkeypatch, seen, status, fragment):
    _use(monkeypatch, seen, httpx.Response(status, json={"detail": "secret detail"}))
    out = await get_listing_performance.ainvoke({})
    assert fragment in out
    assert "secret detail" not in out
    assert sources.get() == []


async def test_connection_error_is_unavailable(monkeypatch, seen):
    _use(monkeypatch, seen, httpx.ConnectError("down"))
    assert "unavailable" in await get_listing_performance.ainvoke({})
    assert sources.get() == []
