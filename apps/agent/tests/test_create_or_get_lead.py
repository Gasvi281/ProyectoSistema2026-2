"""Tests para create_or_get_lead tool y LeadPort (3.2c)."""
import pytest
import httpx

from agent.tools_langchain import create_or_get_lead
from agent.leads import HttpLead, get_lead_provider
from agent.fakes import FakeLead
from agent.fakes import SEED_AGENT_ID, SEED_LISTING_ID, SEED_CLIENT_ID
from agent.ports import LeadPort


CLIENT_ID  = SEED_CLIENT_ID
LISTING_ID = SEED_LISTING_ID


# --- FakeLead ---

@pytest.mark.asyncio
async def test_fake_returns_lead():
    provider = FakeLead()
    result = await provider.create_or_get_lead(CLIENT_ID, LISTING_ID)
    assert result["client_id"] == CLIENT_ID
    assert result["listing_id"] == LISTING_ID
    assert result["agent_id"] == SEED_AGENT_ID
    assert result["source_channel"] == "IN_APP"
    assert result["status"] == "NEW"
    assert result["id"].startswith("lead-")
    assert "created_at" in result and "updated_at" in result


@pytest.mark.asyncio
async def test_fake_upsert_same_pair_returns_same_lead():
    """Dos llamadas con el mismo (client_id, listing_id) devuelven el mismo lead."""
    provider = FakeLead()
    first  = await provider.create_or_get_lead(CLIENT_ID, LISTING_ID)
    second = await provider.create_or_get_lead(CLIENT_ID, LISTING_ID)
    assert first["id"] == second["id"]
    assert first["agent_id"] == second["agent_id"]


@pytest.mark.asyncio
async def test_fake_upsert_different_listing_returns_different_lead():
    """Distinta combinación genera un lead distinto."""
    other_listing = "92698698-61a1-4729-bcb9-83501b4da0fe"
    provider = FakeLead()
    lead_a = await provider.create_or_get_lead(CLIENT_ID, LISTING_ID)
    lead_b = await provider.create_or_get_lead(CLIENT_ID, other_listing)
    assert lead_a["id"] != lead_b["id"]


# --- tool create_or_get_lead (modo fake por defecto) ---

@pytest.mark.asyncio
async def test_tool_fake_mode_success(monkeypatch):
    monkeypatch.setenv("LEAD_MODE", "fake")
    result = await create_or_get_lead.ainvoke(
        {"client_id": CLIENT_ID, "listing_id": LISTING_ID}
    )
    assert result["client_id"] == CLIENT_ID
    assert result["agent_id"] == SEED_AGENT_ID
    assert result["id"].startswith("lead-")
    assert result["error"] is None
    assert result["error_code"] is None


@pytest.mark.asyncio
async def test_tool_422_invalid_ids(monkeypatch):
    class InvalidProvider(LeadPort):
        async def create_or_get_lead(self, client_id, listing_id, source_channel="IN_APP"):
            resp = httpx.Response(422, request=httpx.Request("POST", "http://x"))
            raise httpx.HTTPStatusError("unprocessable", request=resp.request, response=resp)

    monkeypatch.setattr("agent.leads.get_lead_provider", lambda: InvalidProvider())
    result = await create_or_get_lead.ainvoke(
        {"client_id": CLIENT_ID, "listing_id": LISTING_ID}
    )
    assert result["error_code"] == 422
    assert "inválido" in result["error"]


@pytest.mark.asyncio
async def test_tool_generic_error(monkeypatch):
    class FailingProvider(LeadPort):
        async def create_or_get_lead(self, client_id, listing_id, source_channel="IN_APP"):
            raise RuntimeError("connection refused")

    monkeypatch.setattr("agent.leads.get_lead_provider", lambda: FailingProvider())
    result = await create_or_get_lead.ainvoke(
        {"client_id": CLIENT_ID, "listing_id": LISTING_ID}
    )
    assert result["error_code"] is None
    assert "connection refused" in result["error"]


# --- HttpLead (unit, sin HTTP real) ---

@pytest.mark.asyncio
async def test_http_provider_post_body_and_response(monkeypatch):
    captured = {}
    backend_response = {
        "id": "lead-uuid-abc",
        "client_id": CLIENT_ID,
        "listing_id": LISTING_ID,
        "agent_id": SEED_AGENT_ID,
        "source_channel": "IN_APP",
        "status": "NEW",
        "created_at": "2026-09-10T00:00:00+00:00",
        "updated_at": "2026-09-10T00:00:00+00:00",
    }

    async def mock_post(self, url, json=None, headers=None):
        captured["url"] = url
        captured["json"] = json
        captured["headers"] = headers

        class FakeResp:
            status_code = 201
            def raise_for_status(self): pass
            def json(self): return backend_response
        return FakeResp()

    monkeypatch.setenv("BACKEND_URL", "http://localhost:8000")
    monkeypatch.setenv("BACKEND_SERVICE_TOKEN", "test-token")
    monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)

    provider = HttpLead()
    result = await provider.create_or_get_lead(CLIENT_ID, LISTING_ID)

    assert captured["url"] == "http://localhost:8000/leads"
    assert captured["json"] == {
        "client_id": CLIENT_ID,
        "listing_id": LISTING_ID,
        "source_channel": "IN_APP",
    }
    assert captured["headers"]["Authorization"] == "Bearer test-token"
    assert result["id"] == "lead-uuid-abc"
    assert result["agent_id"] == SEED_AGENT_ID


def test_http_provider_raises_if_no_auth(monkeypatch):
    monkeypatch.setenv("BACKEND_URL", "http://localhost:8000")
    monkeypatch.delenv("BACKEND_SERVICE_TOKEN", raising=False)
    monkeypatch.delenv("DEV_AGENT_ID", raising=False)
    with pytest.raises(ValueError, match="BACKEND_SERVICE_TOKEN"):
        HttpLead()


# --- factory ---

def test_factory_default_is_fake(monkeypatch):
    monkeypatch.delenv("LEAD_MODE", raising=False)
    provider = get_lead_provider()
    assert isinstance(provider, FakeLead)


def test_factory_fake_mode(monkeypatch):
    monkeypatch.setenv("LEAD_MODE", "fake")
    provider = get_lead_provider()
    assert isinstance(provider, FakeLead)


def test_factory_http_mode(monkeypatch):
    monkeypatch.setenv("LEAD_MODE", "http")
    monkeypatch.setenv("BACKEND_URL", "http://localhost:8000")
    monkeypatch.setenv("DEV_AGENT_ID", "dev-agent-test")
    provider = get_lead_provider()
    assert isinstance(provider, HttpLead)


def test_factory_invalid_mode(monkeypatch):
    monkeypatch.setenv("LEAD_MODE", "invalid")
    with pytest.raises(ValueError, match="LEAD_MODE inválido"):
        get_lead_provider()
