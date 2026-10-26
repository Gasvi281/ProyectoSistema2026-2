import httpx
from fastapi.testclient import TestClient

from insights import agent, backend
from insights.fake_llm import FakeInsightsLLM
from insights.main import app

ME_ADMIN = {"id": "a1", "agency_id": "g1", "role": "TEAM_ADMIN", "active": True}
NORTH_STAR = {
    "leads": 40,
    "median_first_response_hours": None,
    "pct_with_follow_up": 62.5,
    "lead_to_visit_conversion_pct": 30.0,
    "pct_lost_within_48h": 5.0,
    "stage_conversion": [],
}


def _handler(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/me":
        return httpx.Response(200, json=ME_ADMIN)
    if request.url.path == "/analytics/north-star":
        return httpx.Response(200, json=NORTH_STAR)
    return httpx.Response(404)


def _chat(client, message, conversation_id=None):
    return client.post(
        "/insights/chat",
        json={"message": message, "conversation_id": conversation_id},
        headers={"Authorization": "Bearer t"},
    )


def test_chat_end_to_end_with_fake_llm(monkeypatch):
    monkeypatch.setenv("INSIGHTS_LLM_MODE", "fake")
    monkeypatch.setattr(backend, "_transport", httpx.MockTransport(_handler))
    client = TestClient(app)

    body = _chat(client, "How is the agency doing?").json()
    assert body["conversation_id"]
    assert "leads: 40" in body["reply"]
    assert "median_first_response_hours: no data" in body["reply"]
    assert body["sources"] == [
        {"tool": "get_north_star", "endpoint": "GET /analytics/north-star", "params": {}}
    ]

    # Segundo turno con el mismo id: el hilo conserva el historial (2 turnos x 4 mensajes).
    cid = body["conversation_id"]
    again = _chat(client, "And now?", cid).json()
    assert again["conversation_id"] == cid
    assert len(again["sources"]) == 1  # sources es por request
    state = agent.get_graph().checkpointer.get_tuple({"configurable": {"thread_id": cid}})
    assert len(state.checkpoint["channel_values"]["messages"]) == 8


# --- Slice 2: LLM falso con script ---

INES_ID = "11111111-1111-1111-1111-111111111111"
CARLOS_1 = "22222222-2222-2222-2222-222222222222"
CARLOS_2 = "33333333-3333-3333-3333-333333333333"
AGENTS = [
    {"id": INES_ID, "agency_id": "g1", "role": "AGENT", "active": True, "full_name": "Inés Mora"},
    {"id": CARLOS_1, "agency_id": "g1", "role": "AGENT", "active": True, "full_name": "Carlos Pérez"},
    {"id": CARLOS_2, "agency_id": "g1", "role": "AGENT", "active": True, "full_name": "Carlos Ruiz"},
]
RESPONSE_TIMES = [
    {"agent_id": CARLOS_2, "agent_name": "Carlos Ruiz", "leads": 12,
     "avg_first_response_hours": 30.0, "median_first_response_hours": 26.5, "never_answered": 4},
    {"agent_id": INES_ID, "agent_name": "Inés Mora", "leads": 10,
     "avg_first_response_hours": 3.0, "median_first_response_hours": 2.0, "never_answered": 0},
]
FUNNEL = {
    "stages": [
        {"stage": "INTERESTED", "leads_reached": 10, "pct_from_prev": None, "pct_of_first": 100.0},
        {"stage": "WON", "leads_reached": 2, "pct_from_prev": 50.0, "pct_of_first": 20.0},
    ],
    "lost": 3,
    "filters": {"agent_id": INES_ID},
}


LEADS = [
    {"id": "l1", "agent_id": INES_ID, "current_stage": "VISITED",
     "created_at": "2026-08-05T15:00:00Z", "client_name": "Germán Elías González",
     "neighborhood": "Chapinero", "operation_type": "SALE", "asking_price": "1372892.26"},
]


LOST_REASONS = [
    {"reason": "PRICE", "leads": 12, "pct": 60.0},
    {"reason": "FINANCING", "leads": 8, "pct": 40.0},
]


LISTING_PERFORMANCE = [
    {"listing_id": "00000000-0000-0000-0000-000000000001", "operation_type": "SALE",
     "city": "Bogotá", "neighborhood": "Usaquén", "property_type": "APARTMENT",
     "asking_price": "450000000.00", "views": 204, "leads": 8, "visits": 4, "won": 1},
    {"listing_id": "00000000-0000-0000-0000-000000000002", "operation_type": "RENT",
     "city": "Bogotá", "neighborhood": "Chapinero", "property_type": "STUDIO",
     "asking_price": "2500000.00", "views": 90, "leads": 2, "visits": 0, "won": 0},
]


def _scripted_client(monkeypatch, script):
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        routes = {
            "/me": ME_ADMIN,
            "/agents": AGENTS,
            "/analytics/agent-response-time": RESPONSE_TIMES,
            "/analytics/funnel": FUNNEL,
            "/leads": LEADS,
            "/analytics/lost-reasons": LOST_REASONS,
            "/analytics/listing-performance": LISTING_PERFORMANCE,
        }
        if request.url.path in routes:
            return httpx.Response(200, json=routes[request.url.path])
        return httpx.Response(404)

    monkeypatch.setattr(backend, "_transport", httpx.MockTransport(handler))
    monkeypatch.setattr(agent, "_graph", agent.build_graph(FakeInsightsLLM(script=script)))
    return TestClient(app), seen


def test_slowest_agent_uses_response_times(monkeypatch):
    script = [
        {"name": "get_agent_response_times", "args": {}},
        "Más lento: {get_agent_response_times[agents][0][agent_name]}, "
        "mediana {get_agent_response_times[agents][0][median_first_response_hours]} h "
        "({get_agent_response_times[period]}).",
    ]
    client, seen = _scripted_client(monkeypatch, script)
    body = _chat(client, "Which agent responds slowest?").json()
    assert "Carlos Ruiz" in body["reply"] and "26.5" in body["reply"]
    assert "full history" in body["reply"]
    assert [s["tool"] for s in body["sources"]] == ["get_agent_response_times"]


def test_agent_funnel_lists_agents_then_funnel(monkeypatch):
    script = [
        {"name": "list_agents", "args": {}},
        {"name": "get_funnel", "args": {"agent_id": INES_ID}},
        "Embudo de Inés: {get_funnel[stages][1][leads_reached]} ganados, "
        "{get_funnel[stages][1][pct_of_first]}% ({get_funnel[period]}).",
    ]
    client, seen = _scripted_client(monkeypatch, script)
    body = _chat(client, "How is Inés's funnel?").json()
    funnel_req = [r for r in seen if r.url.path == "/analytics/funnel"]
    assert len(funnel_req) == 1
    assert dict(funnel_req[0].url.params) == {"agent_id": INES_ID}
    assert "20.0%" in body["reply"] and "all leads ever created" in body["reply"]
    assert [s["tool"] for s in body["sources"]] == ["list_agents", "get_funnel"]
    assert body["sources"][1]["params"] == {"agent_id": INES_ID}


def test_ambiguous_name_does_not_call_funnel(monkeypatch):
    script = [
        {"name": "list_agents", "args": {}},
        "Hay dos agentes: {list_agents[agents][1][full_name]} y "
        "{list_agents[agents][2][full_name]}. ¿A cuál te refieres?",
    ]
    client, seen = _scripted_client(monkeypatch, script)
    body = _chat(client, "How is Carlos's funnel?").json()
    assert not [r for r in seen if r.url.path == "/analytics/funnel"]
    assert "Carlos Pérez" in body["reply"] and "Carlos Ruiz" in body["reply"]
    assert [s["tool"] for s in body["sources"]] == ["list_agents"]


def test_agent_open_leads_lists_agents_then_leads(monkeypatch):
    script = [
        {"name": "list_agents", "args": {}},
        {"name": "list_leads", "args": {"agent_id": INES_ID}},
        "{list_leads[total_count]} abiertos ({list_leads[period]}): "
        "{list_leads[leads][0][client_name]}, {list_leads[leads][0][asking_price]}.",
    ]
    client, seen = _scripted_client(monkeypatch, script)
    body = _chat(client, "¿Qué leads abiertos tiene Inés?").json()
    leads_req = [r for r in seen if r.url.path == "/leads"]
    assert len(leads_req) == 1
    assert dict(leads_req[0].url.params) == {
        "active": "true", "limit": "200", "offset": "0", "agent_id": INES_ID,
    }
    assert "1 abiertos (all open leads): Germán Elías González, $1.372.892." in body["reply"]
    assert [s["tool"] for s in body["sources"]] == ["list_agents", "list_leads"]


def test_lost_reasons_last_quarter(monkeypatch):
    script = [
        {"name": "get_lost_reasons", "args": {"days": 90}},
        "{get_lost_reasons[total_lost_with_reason]} perdidos; "
        "{get_lost_reasons[reasons][0][reason]} {get_lost_reasons[reasons][0][pct]}% "
        "({get_lost_reasons[period]}).",
    ]
    client, seen = _scripted_client(monkeypatch, script)
    body = _chat(client, "¿Por qué perdimos leads el último trimestre?").json()
    req = [r for r in seen if r.url.path == "/analytics/lost-reasons"]
    assert len(req) == 1 and dict(req[0].url.params) == {"days": "90"}
    assert "20 perdidos; PRICE 60.0% (leads lost in the last 90 days" in body["reply"]
    assert body["sources"] == [
        {
            "tool": "get_lost_reasons",
            "endpoint": "GET /analytics/lost-reasons",
            "params": {"days": 90},
        }
    ]


def test_listing_performance_filtered_by_neighborhood(monkeypatch):
    script = [
        {"name": "get_listing_performance", "args": {"neighborhood": "usaquen"}},
        "{get_listing_performance[total_count]} inmueble: "
        "{get_listing_performance[listings][0][neighborhood]}, "
        "{get_listing_performance[listings][0][views]} vistas, "
        "{get_listing_performance[listings][0][visit_pct]}% visita, "
        "{get_listing_performance[listings][0][asking_price]}.",
    ]
    client, seen = _scripted_client(monkeypatch, script)
    body = _chat(client, "¿Cómo van los inmuebles de Usaquén?").json()
    req = [r for r in seen if r.url.path == "/analytics/listing-performance"]
    assert len(req) == 1 and dict(req[0].url.params) == {"limit": "500"}
    assert "1 inmueble: Usaquén, 204 vistas, 50.0% visita, $450.000.000." in body["reply"]
    assert [s["tool"] for s in body["sources"]] == ["get_listing_performance"]
