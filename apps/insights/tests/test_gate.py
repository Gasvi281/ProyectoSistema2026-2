import httpx
import pytest
from fastapi.testclient import TestClient

from insights import backend
from insights.main import app

TOKEN = "jwt-abc"
ME_ADMIN = {"id": "a1", "agency_id": "g1", "role": "TEAM_ADMIN", "active": True}


@pytest.fixture
def seen():
    return []


def _client(monkeypatch, seen, handler):
    def wrapped(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    monkeypatch.setattr(backend, "_transport", httpx.MockTransport(wrapped))
    return TestClient(app)


def _post(client, token=TOKEN):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    return client.post("/insights/chat", json={"message": "hi"}, headers=headers)


def test_no_header_401_without_backend_call(monkeypatch, seen):
    client = _client(monkeypatch, seen, lambda r: httpx.Response(200, json=ME_ADMIN))
    assert _post(client, token=None).status_code == 401
    assert seen == []


def test_agent_role_403(monkeypatch, seen):
    me = {**ME_ADMIN, "role": "AGENT"}
    client = _client(monkeypatch, seen, lambda r: httpx.Response(200, json=me))
    assert _post(client).status_code == 403


def test_inactive_team_admin_403(monkeypatch, seen):
    me = {**ME_ADMIN, "active": False}
    client = _client(monkeypatch, seen, lambda r: httpx.Response(200, json=me))
    assert _post(client).status_code == 403


def test_backend_401_maps_to_401(monkeypatch, seen):
    client = _client(monkeypatch, seen, lambda r: httpx.Response(401))
    assert _post(client).status_code == 401


def test_backend_403_maps_to_403(monkeypatch, seen):
    client = _client(monkeypatch, seen, lambda r: httpx.Response(403))
    assert _post(client).status_code == 403


def test_backend_down_502(monkeypatch, seen):
    def boom(request):
        raise httpx.ConnectError("down")

    client = _client(monkeypatch, seen, boom)
    assert _post(client).status_code == 502


def test_backend_5xx_502(monkeypatch, seen):
    client = _client(monkeypatch, seen, lambda r: httpx.Response(500))
    assert _post(client).status_code == 502


def test_team_admin_200_forwards_token_as_is(monkeypatch, seen):
    client = _client(monkeypatch, seen, lambda r: httpx.Response(200, json=ME_ADMIN))
    resp = _post(client)
    assert resp.status_code == 200
    assert resp.json()["conversation_id"]
    assert seen[0].url.path == "/me"
    assert seen[0].headers["authorization"] == f"Bearer {TOKEN}"
    assert "x-agency-id" not in seen[0].headers
