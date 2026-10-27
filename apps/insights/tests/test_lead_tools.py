import json

import httpx
import pytest

from insights import backend
from insights.context import auth_header, sources
from insights.tools import _format_cop, list_leads

INES_ID = "11111111-1111-1111-1111-111111111111"
CARLOS_ID = "22222222-2222-2222-2222-222222222222"
AGENTS = [
    {"id": INES_ID, "agency_id": "g1", "role": "AGENT", "active": True, "full_name": "Inés Mora"},
    {"id": CARLOS_ID, "agency_id": "g1", "role": "AGENT", "active": False, "full_name": "Carlos Ruiz"},
]


def _card(n=0, **over):
    card = {
        "id": f"lead-{n}",
        "agent_id": INES_ID,
        "current_stage": "INTERESTED",
        "created_at": f"2026-08-{10 + n % 15:02d}T15:00:00Z",
        "updated_at": "2026-09-01T00:00:00Z",
        "client_name": f"Cliente {n}",
        "neighborhood": "Chapinero",
        "operation_type": "SALE",
        "asking_price": "450000000.00",
        "last_interaction": {"direction": "OUTBOUND", "type": "NOTE"},
    }
    card.update(over)
    return card


@pytest.fixture(autouse=True)
def _ctx():
    auth_header.set("Bearer t")
    sources.set([])


@pytest.fixture
def seen():
    return []


def _use(monkeypatch, seen, leads, agents=AGENTS, leads_status=200, agents_status=200):
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if isinstance(leads, Exception) and request.url.path == "/leads":
            raise leads
        if request.url.path == "/leads":
            return httpx.Response(leads_status, json=leads if leads_status == 200 else {})
        if request.url.path == "/agents":
            return httpx.Response(agents_status, json=agents if agents_status == 200 else {})
        return httpx.Response(404)

    monkeypatch.setattr(backend, "_transport", httpx.MockTransport(handler))


def _paths(seen):
    return [r.url.path for r in seen]


async def test_single_request_with_exact_params(monkeypatch, seen):
    _use(monkeypatch, seen, [_card()])
    await list_leads.ainvoke({"agent_id": INES_ID})
    assert _paths(seen) == ["/leads"]  # con agent_id no se llama a /agents
    expected = {"active": "true", "limit": "200", "offset": "0", "agent_id": INES_ID}
    assert dict(seen[0].url.params) == expected
    assert sources.get() == [
        {
            "tool": "list_leads",
            "endpoint": "GET /leads",
            "params": {"active": True, "limit": 200, "offset": 0, "agent_id": INES_ID},
        }
    ]


async def test_filters_forwarded_and_stage_uppercased(monkeypatch, seen):
    _use(monkeypatch, seen, [_card()])
    out = json.loads(
        await list_leads.ainvoke(
            {"stage": "visited", "created_from": "2026-08-01", "created_to": "2026-08-31"}
        )
    )
    assert dict(seen[0].url.params) == {
        "active": "true", "limit": "200", "offset": "0",
        "stage": "VISITED", "created_from": "2026-08-01", "created_to": "2026-08-31",
    }
    assert out["period"] == "open leads created 2026-08-01 to 2026-08-31"


async def test_no_filters_period(monkeypatch, seen):
    _use(monkeypatch, seen, [_card()])
    out = json.loads(await list_leads.ainvoke({}))
    assert out["period"] == "all open leads"
    assert out["order"] == "oldest created first"


async def test_open_ended_period(monkeypatch, seen):
    _use(monkeypatch, seen, [_card()])
    out = json.loads(await list_leads.ainvoke({"created_to": "2026-08-31"}))
    assert out["period"] == "open leads created (no start) to 2026-08-31"


async def test_by_stage_counts_all_rows_before_the_cap(monkeypatch, seen):
    stages = ["INTERESTED"] * 7 + ["VISITED"] * 4 + ["NEGOTIATING"]
    cards = [_card(i, current_stage=s) for i, s in enumerate(stages)]
    _use(monkeypatch, seen, cards)
    out = json.loads(await list_leads.ainvoke({}))
    assert out["by_stage"] == {
        "INTERESTED": 7, "VISIT_SCHEDULED": 0, "VISITED": 4, "NEGOTIATING": 1,
    }
    assert out["total_count"] == 12
    assert out["shown_count"] == 10 == len(out["leads"])
    assert "total_is_lower_bound" not in out


async def test_by_stage_keeps_all_four_keys_in_funnel_order(monkeypatch, seen):
    _use(monkeypatch, seen, [_card(0, current_stage="VISITED")])
    out = json.loads(await list_leads.ainvoke({"stage": "visited"}))
    assert list(out["by_stage"].items()) == [
        ("INTERESTED", 0), ("VISIT_SCHEDULED", 0), ("VISITED", 1), ("NEGOTIATING", 0),
    ]

    _use(monkeypatch, seen, [])
    out = json.loads(await list_leads.ainvoke({}))
    assert out["by_stage"] == dict.fromkeys(
        ["INTERESTED", "VISIT_SCHEDULED", "VISITED", "NEGOTIATING"], 0
    )
    assert out["total_count"] == 0


async def test_ordered_by_created_at_ascending(monkeypatch, seen):
    cards = [
        _card(0, client_name="C", created_at="2026-08-20T15:00:00Z"),
        _card(1, client_name="A", created_at="2026-08-01T15:00:00Z"),
        _card(2, client_name="B", created_at="2026-08-10T15:00:00Z"),
    ]
    _use(monkeypatch, seen, cards)
    out = json.loads(await list_leads.ainvoke({}))
    assert [r["client_name"] for r in out["leads"]] == ["A", "B", "C"]


async def test_cap_keeps_the_oldest_created(monkeypatch, seen):
    cards = [
        _card(i, client_name=f"L{i}", created_at=f"2026-08-{i + 1:02d}T15:00:00Z")
        for i in range(12)
    ][::-1]
    _use(monkeypatch, seen, cards)
    out = json.loads(await list_leads.ainvoke({}))
    assert [r["client_name"] for r in out["leads"]] == [f"L{i}" for i in range(10)]


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("450000000.00", "$450.000.000"),
        ("1372892.26", "$1.372.892"),  # venta con decimales
        ("2500000.50", "$2.500.001"),  # arriendo, redondeo half-up
        ("0", "$0"),
        (None, "no data"),
        ("abc", "no data"),
    ],
)
def test_format_cop(raw, expected):
    assert _format_cop(raw) == expected


async def test_row_fields_and_price_in_payload(monkeypatch, seen):
    _use(monkeypatch, seen, [_card(operation_type="RENT", asking_price="2500000.50")])
    row = json.loads(await list_leads.ainvoke({}))["leads"][0]
    assert row == {
        "client_name": "Cliente 0",
        "neighborhood": "Chapinero",
        "operation_type": "RENT",
        "asking_price": "$2.500.001",
        "stage": "INTERESTED",
        "created_on": "2026-08-10",
        "agent_name": "Inés Mora",
    }


async def test_last_interaction_is_not_exposed(monkeypatch, seen):
    _use(monkeypatch, seen, [_card()])
    raw = await list_leads.ainvoke({})
    assert "last_interaction" not in raw and "NOTE" not in raw


async def test_created_on_uses_bogota_day(monkeypatch, seen):
    _use(monkeypatch, seen, [_card(created_at="2026-08-31T01:30:00Z")])
    row = json.loads(await list_leads.ainvoke({}))["leads"][0]
    assert row["created_on"] == "2026-08-30"


async def test_null_fields_become_no_data(monkeypatch, seen):
    _use(monkeypatch, seen, [_card(client_name=None, neighborhood=None, asking_price=None)])
    row = json.loads(await list_leads.ainvoke({}))["leads"][0]
    assert row["client_name"] == row["neighborhood"] == row["asking_price"] == "no data"


async def test_agent_name_join_includes_inactive_agents(monkeypatch, seen):
    cards = [_card(0), _card(1, agent_id=CARLOS_ID), _card(2, agent_id="unknown-agent")]
    _use(monkeypatch, seen, cards)
    out = json.loads(await list_leads.ainvoke({}))
    assert [r["agent_name"] for r in out["leads"]] == ["Inés Mora", "Carlos Ruiz", "no data"]
    agents_req = [r for r in seen if r.url.path == "/agents"]
    # Sin active=True para que los agentes desactivados también traigan nombre.
    assert dict(agents_req[0].url.params) == {"include_bots": "false", "limit": "200"}
    assert [s["endpoint"] for s in sources.get()] == ["GET /leads", "GET /agents"]


async def test_agents_failure_still_returns_leads_with_no_data_names(monkeypatch, seen):
    _use(monkeypatch, seen, [_card(0), _card(1)], agents_status=500)
    out = json.loads(await list_leads.ainvoke({}))
    assert [r["agent_name"] for r in out["leads"]] == ["no data", "no data"]
    assert out["total_count"] == 2
    assert [s["endpoint"] for s in sources.get()] == ["GET /leads"]


async def test_lower_bound_flag_only_at_exactly_200(monkeypatch, seen):
    _use(monkeypatch, seen, [_card(i) for i in range(200)])
    out = json.loads(await list_leads.ainvoke({"agent_id": INES_ID}))
    assert out["total_count"] == 200 and out["total_is_lower_bound"] is True

    _use(monkeypatch, seen, [_card(i) for i in range(199)])
    out = json.loads(await list_leads.ainvoke({"agent_id": INES_ID}))
    assert out["total_count"] == 199 and "total_is_lower_bound" not in out


async def test_accented_name_passes_through_utf8(monkeypatch, seen):
    _use(monkeypatch, seen, [_card(client_name="Germán Elías González", neighborhood="Usaquén")])
    raw = await list_leads.ainvoke({})
    assert "Germán Elías González" in raw and "Usaquén" in raw
    assert "\\u" not in raw
    assert json.loads(raw)["leads"][0]["client_name"] == "Germán Elías González"


@pytest.mark.parametrize(
    "args",
    [
        {"agent_id": "not-a-uuid"},
        {"created_from": "2026-13-01"},
        {"created_to": "20260801"},
        {"stage": "FLYING"},
        {"stage": "WON"},
        {"stage": "lost"},
    ],
)
async def test_invalid_input_makes_no_request(monkeypatch, seen, args):
    _use(monkeypatch, seen, [_card()])
    out = await list_leads.ainvoke(args)
    assert out.startswith("Invalid")
    assert seen == []
    assert sources.get() == []


async def test_422_is_invalid_date_range(monkeypatch, seen):
    _use(monkeypatch, seen, [], leads_status=422)
    out = await list_leads.ainvoke({"created_from": "2026-09-01", "created_to": "2026-08-01"})
    assert "Invalid date range" in out
    assert sources.get() == []


@pytest.mark.parametrize(
    "status, fragment",
    [(401, "sign in again"), (403, "not allowed"), (404, "not available"), (500, "unavailable")],
)
async def test_status_mapping_leaves_sources_empty(monkeypatch, seen, status, fragment):
    _use(monkeypatch, seen, [], leads_status=status)
    assert fragment in await list_leads.ainvoke({})
    assert _paths(seen) == ["/leads"]  # el error corta antes de /agents
    assert sources.get() == []


async def test_connection_error_is_unavailable(monkeypatch, seen):
    _use(monkeypatch, seen, httpx.ConnectError("down"))
    assert "unavailable" in await list_leads.ainvoke({})
    assert sources.get() == []
