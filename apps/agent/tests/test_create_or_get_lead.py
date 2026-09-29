"""Tests para create_or_get_lead tool y LeadPort (3.2c)."""
import pytest
import httpx

from agent.tools_langchain import create_or_get_lead
from agent.leads import HttpLead, get_lead_provider, check_lead_modes
from agent.fakes import FakeLead, UnknownListingError
from agent.fakes import SEED_AGENT_ID, SEED_LISTING_ID, SEED_CLIENT_ID
from agent.ports import LeadPort, ListingAgencyResolverPort
from agent import agency_registry


@pytest.fixture(autouse=True)
def _clear_registry():
    """Aisla el agency_registry entre tests para evitar filtración de estado."""
    agency_registry.clear()
    yield
    agency_registry.clear()


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
    # El tool debe pasar TELEGRAM al provider — verificado contra el backend
    # (homelitics-crm/app/schemas.py:17: Channel = Literal["TELEGRAM","IN_APP","CALL"]).
    assert result["source_channel"] == "TELEGRAM"


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
    # El adapter requiere que el listing_id esté en el registry (Alt 3).
    agency_registry.register(listing_id=LISTING_ID, agency_id="agency-test-x")

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


# ---------------------------------------------------------------------------
# check_lead_modes — startup guard
# ---------------------------------------------------------------------------

def test_check_lead_modes_raises_on_http_lead_with_fake_resolver(monkeypatch):
    """LEAD_MODE=http + LISTING_AGENCY_RESOLVER_MODE=fake → ValueError al arrancar.
    Previene que la combinación silenciosamente falle en el primer turno."""
    monkeypatch.setenv("LEAD_MODE", "http")
    monkeypatch.setenv("LISTING_AGENCY_RESOLVER_MODE", "fake")
    with pytest.raises(ValueError, match="LISTING_AGENCY_RESOLVER_MODE=http"):
        check_lead_modes()


def test_check_lead_modes_ok_both_fake(monkeypatch):
    monkeypatch.setenv("LEAD_MODE", "fake")
    monkeypatch.setenv("LISTING_AGENCY_RESOLVER_MODE", "fake")
    check_lead_modes()  # no debe lanzar


def test_check_lead_modes_ok_both_http(monkeypatch):
    monkeypatch.setenv("LEAD_MODE", "http")
    monkeypatch.setenv("LISTING_AGENCY_RESOLVER_MODE", "http")
    check_lead_modes()  # no debe lanzar


def test_check_lead_modes_ok_http_resolver_fake_lead(monkeypatch):
    """http resolver + fake lead es raro pero inofensivo — el resolver corre
    pero FakeLead no usa el agency_id; no hay razón para bloquearlo."""
    monkeypatch.setenv("LEAD_MODE", "fake")
    monkeypatch.setenv("LISTING_AGENCY_RESOLVER_MODE", "http")
    check_lead_modes()  # no debe lanzar


# ---------------------------------------------------------------------------
# Propagación de excepciones del resolver (end-to-end a nivel de tool)
# ---------------------------------------------------------------------------

class _ResolverRaises(ListingAgencyResolverPort):
    """Stub: resolve() lanza una excepción arbitraria."""
    def __init__(self, exc: Exception):
        self._exc = exc

    async def resolve(self, listing_id: str) -> str:
        raise self._exc


@pytest.mark.asyncio
async def test_tool_resolver_403_dict_no_exception(monkeypatch):
    """HTTPStatusError 403 del resolver → dict de error, no propaga excepción al grafo.
    (MemorySaver queda consistente: nunca escapa una excepción del tool.)
    Los casos BACKEND_AUTH_ERROR con aserciones de `code` están en las pruebas de Diff 4."""
    _err_resp = httpx.Response(
        403,
        content=b'{"detail":"no AI_AGENT row"}',
        request=httpx.Request("GET", "https://fake-backend.test/listings/x"),
    )
    exc = httpx.HTTPStatusError("forbidden", request=_err_resp.request, response=_err_resp)

    monkeypatch.setattr(
        "agent.listing_agency_resolver.get_listing_agency_resolver_provider",
        lambda: _ResolverRaises(exc),
    )

    result = await create_or_get_lead.ainvoke(
        {"client_id": CLIENT_ID, "listing_id": LISTING_ID}
    )
    assert isinstance(result, dict)
    assert result["error_code"] == 403
    assert result.get("code") == "BACKEND_AUTH_ERROR"
    assert "error" in result and result["error"]


@pytest.mark.asyncio
async def test_tool_resolver_read_timeout_returns_backend_unavailable(monkeypatch):
    """ReadTimeout del resolver → code='BACKEND_UNAVAILABLE', error_code=None, no propaga."""
    monkeypatch.setattr(
        "agent.listing_agency_resolver.get_listing_agency_resolver_provider",
        lambda: _ResolverRaises(httpx.ReadTimeout("timed out")),
    )

    result = await create_or_get_lead.ainvoke(
        {"client_id": CLIENT_ID, "listing_id": LISTING_ID}
    )
    assert result["error_code"] is None
    assert result.get("code") == "BACKEND_UNAVAILABLE"
    assert "timed out" in result["error"]


@pytest.mark.asyncio
async def test_tool_resolver_unknown_listing_returns_code_unknown_listing(monkeypatch):
    """UnknownListingError del resolver → code='UNKNOWN_LISTING', retorna sin llamar al provider.

    El mensaje no debe mencionar create_or_get_lead (sería circular: estamos dentro de él).
    """
    monkeypatch.setattr(
        "agent.listing_agency_resolver.get_listing_agency_resolver_provider",
        lambda: _ResolverRaises(UnknownListingError("listing not found")),
    )

    result = await create_or_get_lead.ainvoke(
        {"client_id": CLIENT_ID, "listing_id": LISTING_ID}
    )
    assert result.get("code") == "UNKNOWN_LISTING"
    assert result["error_code"] is None
    assert "create_or_get_lead" not in result["error"]


@pytest.mark.asyncio
async def test_tool_resolver_connect_error_returns_backend_unavailable(monkeypatch):
    """ConnectError del resolver → code='BACKEND_UNAVAILABLE', error_code=None."""
    monkeypatch.setattr(
        "agent.listing_agency_resolver.get_listing_agency_resolver_provider",
        lambda: _ResolverRaises(httpx.ConnectError("connection refused")),
    )

    result = await create_or_get_lead.ainvoke(
        {"client_id": CLIENT_ID, "listing_id": LISTING_ID}
    )
    assert result.get("code") == "BACKEND_UNAVAILABLE"
    assert result["error_code"] is None


@pytest.mark.asyncio
async def test_tool_resolver_503_returns_backend_unavailable(monkeypatch):
    """HTTPStatusError 503 del resolver → code='BACKEND_UNAVAILABLE', error_code=503."""
    resp = httpx.Response(503, request=httpx.Request("GET", "http://x"))
    exc = httpx.HTTPStatusError("service unavailable", request=resp.request, response=resp)
    monkeypatch.setattr(
        "agent.listing_agency_resolver.get_listing_agency_resolver_provider",
        lambda: _ResolverRaises(exc),
    )

    result = await create_or_get_lead.ainvoke(
        {"client_id": CLIENT_ID, "listing_id": LISTING_ID}
    )
    assert result.get("code") == "BACKEND_UNAVAILABLE"
    assert result["error_code"] == 503


@pytest.mark.asyncio
async def test_tool_resolver_403_returns_backend_auth_error(monkeypatch):
    """HTTPStatusError 403 del resolver → code='BACKEND_AUTH_ERROR', error_code=403."""
    resp = httpx.Response(
        403,
        content=b'{"detail":"no AI_AGENT row"}',
        request=httpx.Request("GET", "http://x"),
    )
    exc = httpx.HTTPStatusError("forbidden", request=resp.request, response=resp)
    monkeypatch.setattr(
        "agent.listing_agency_resolver.get_listing_agency_resolver_provider",
        lambda: _ResolverRaises(exc),
    )

    result = await create_or_get_lead.ainvoke(
        {"client_id": CLIENT_ID, "listing_id": LISTING_ID}
    )
    assert result.get("code") == "BACKEND_AUTH_ERROR"
    assert result["error_code"] == 403


@pytest.mark.asyncio
async def test_tool_all_fake_happy_path_uses_default_agency(monkeypatch):
    """Modo todo-fake: el resolver retorna FAKE_DEFAULT_AGENCY_ID y el tool devuelve lead."""
    from agent.fakes import FAKE_DEFAULT_AGENCY_ID
    monkeypatch.setenv("LEAD_MODE", "fake")
    monkeypatch.delenv("LISTING_AGENCY_RESOLVER_MODE", raising=False)  # default=fake

    result = await create_or_get_lead.ainvoke(
        {"client_id": CLIENT_ID, "listing_id": LISTING_ID}
    )
    assert result["error"] is None
    assert result["error_code"] is None
    # El registry debe haber recibido el listing_id con FAKE_DEFAULT_AGENCY_ID
    from agent import agency_registry
    assert agency_registry.lookup(LISTING_ID) == FAKE_DEFAULT_AGENCY_ID
