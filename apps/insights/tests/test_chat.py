import httpx
from fastapi.testclient import TestClient

from insights import agent, backend
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
