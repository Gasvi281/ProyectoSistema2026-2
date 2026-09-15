"""
test_listing_agency_resolver.py
--------------------------------
Pruebas unitarias de ListingAgencyResolverPort / FakeListingAgencyResolver
y HttpListingAgencyResolver.
"""
import json

import httpx
import pytest

from agent.fakes import FakeListingAgencyResolver, UnknownListingError, KNOWN_AGENCY_IDS
from agent.listing_agency_resolver import (
    HttpListingAgencyResolver,
    get_listing_agency_resolver_provider,
)

# Listing real de seed (CLAUDE.md) y agencia asignada arbitraria pero coherente.
SEED_LISTING = "c34b9fbb-8d4a-45b8-951a-c8ea585a0afa"
SEED_AGENCY  = "8768a84f-a76a-4de6-8e9e-1a11fcbb4e59"  # Cruz-Oviedo Realty


# ---------------------------------------------------------------------------
# Fake resolver (casos preexistentes, sin modificar)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_known_listing_resolves_to_agency():
    """Un listing mapeado en el constructor retorna exactamente ese agency_id."""
    resolver = FakeListingAgencyResolver({SEED_LISTING: SEED_AGENCY})
    result = await resolver.resolve(SEED_LISTING)
    assert result == SEED_AGENCY


@pytest.mark.asyncio
async def test_known_listing_agency_is_in_known_agencies():
    """El agency_id resuelto pertenece al universo de agencias válidas."""
    resolver = FakeListingAgencyResolver({SEED_LISTING: SEED_AGENCY})
    result = await resolver.resolve(SEED_LISTING)
    assert result in KNOWN_AGENCY_IDS


@pytest.mark.asyncio
async def test_unknown_listing_raises_error():
    """Un listing no mapeado lanza UnknownListingError — nunca retorna None."""
    resolver = FakeListingAgencyResolver()  # sin seed
    with pytest.raises(UnknownListingError):
        await resolver.resolve("00000000-0000-0000-0000-000000000000")


# ---------------------------------------------------------------------------
# HttpListingAgencyResolver — helpers
# ---------------------------------------------------------------------------

_VALID_ENV = {
    "BACKEND_URL": "https://fake-backend.test",
    "BACKEND_SERVICE_TOKEN": "tok-test",
    "AGENCY_ID": SEED_AGENCY,
}

_LISTING_ID = "6c645c15-aba3-41cb-a561-e1e917ec889c"


def _set_valid_env(monkeypatch):
    for k, v in _VALID_ENV.items():
        monkeypatch.setenv(k, v)
    # Asegura que los modos de auth alternativos no interfieran
    monkeypatch.delenv("BOT_EMAIL",    raising=False)
    monkeypatch.delenv("BOT_PASSWORD", raising=False)
    monkeypatch.delenv("DEV_AGENT_ID", raising=False)


def _make_listing_response(status: int = 200) -> httpx.Response:
    """Construye un httpx.Response real que simula la respuesta de GET /listings/{id}."""
    request = httpx.Request("GET", f"https://fake-backend.test/listings/{_LISTING_ID}")
    body = json.dumps({
        "id": _LISTING_ID,
        "agent_id": "45b89cd9-27cb-4f2a-8da0-1097be0f051b",
        "status": "ACTIVE",
    }).encode()
    return httpx.Response(status, content=body, request=request)


def _make_error_response(status: int) -> httpx.Response:
    request = httpx.Request("GET", f"https://fake-backend.test/listings/{_LISTING_ID}")
    return httpx.Response(status, content=b'{"detail":"error"}', request=request)


# ---------------------------------------------------------------------------
# (1) 200 → retorna caller AGENCY_ID
# ---------------------------------------------------------------------------

async def test_http_200_returns_caller_agency_id(monkeypatch):
    """Respuesta 200 → resolve() retorna el caller AGENCY_ID."""
    _set_valid_env(monkeypatch)

    async def mock_get(self, url, *, headers=None, **kw):
        return _make_listing_response(200)

    monkeypatch.setattr(httpx.AsyncClient, "get", mock_get)

    resolver = HttpListingAgencyResolver()
    result = await resolver.resolve(_LISTING_ID)
    assert result == SEED_AGENCY


# ---------------------------------------------------------------------------
# (2) 200 → X-Agency-Id enviado al backend == caller AGENCY_ID
# ---------------------------------------------------------------------------

async def test_http_200_sends_caller_agency_id_in_header(monkeypatch):
    """En la petición GET /listings/{id} se manda X-Agency-Id == caller AGENCY_ID."""
    _set_valid_env(monkeypatch)
    captured = {}

    async def mock_get(self, url, *, headers=None, **kw):
        captured["headers"] = headers or {}
        return _make_listing_response(200)

    monkeypatch.setattr(httpx.AsyncClient, "get", mock_get)

    resolver = HttpListingAgencyResolver()
    await resolver.resolve(_LISTING_ID)

    assert captured["headers"].get("X-Agency-Id") == SEED_AGENCY
    assert "Authorization" in captured["headers"]


# ---------------------------------------------------------------------------
# (3) 404 → UnknownListingError (fail-loud, caso de negocio esperado)
# ---------------------------------------------------------------------------

async def test_http_404_raises_unknown_listing_error(monkeypatch):
    """Respuesta 404 → UnknownListingError; nunca None ni silencioso."""
    _set_valid_env(monkeypatch)

    async def mock_get(self, url, *, headers=None, **kw):
        return _make_error_response(404)

    monkeypatch.setattr(httpx.AsyncClient, "get", mock_get)

    resolver = HttpListingAgencyResolver()
    with pytest.raises(UnknownListingError):
        await resolver.resolve(_LISTING_ID)


# ---------------------------------------------------------------------------
# (4) 403 → propaga HTTPStatusError (no se traga; no se convierte en None)
# ---------------------------------------------------------------------------

async def test_http_403_raises_http_status_error(monkeypatch):
    """Respuesta 403 (auth/config) → HTTPStatusError — nunca cae a None."""
    _set_valid_env(monkeypatch)

    async def mock_get(self, url, *, headers=None, **kw):
        return _make_error_response(403)

    monkeypatch.setattr(httpx.AsyncClient, "get", mock_get)

    resolver = HttpListingAgencyResolver()
    with pytest.raises(httpx.HTTPStatusError):
        await resolver.resolve(_LISTING_ID)


# ---------------------------------------------------------------------------
# (5) Guard fail-loud: AGENCY_ID ausente → ValueError al construir
# ---------------------------------------------------------------------------

def test_missing_agency_id_raises_on_construction(monkeypatch):
    """Sin AGENCY_ID, construir HttpListingAgencyResolver falla fuerte."""
    _set_valid_env(monkeypatch)
    monkeypatch.delenv("AGENCY_ID", raising=False)
    with pytest.raises(ValueError, match="AGENCY_ID"):
        HttpListingAgencyResolver()


# ---------------------------------------------------------------------------
# (6) Factory: LISTING_AGENCY_RESOLVER_MODE=http → HttpListingAgencyResolver
# ---------------------------------------------------------------------------

def test_factory_http_mode_returns_http_resolver(monkeypatch):
    """get_listing_agency_resolver_provider() con modo http devuelve HttpListingAgencyResolver."""
    _set_valid_env(monkeypatch)
    monkeypatch.setenv("LISTING_AGENCY_RESOLVER_MODE", "http")

    provider = get_listing_agency_resolver_provider()
    assert isinstance(provider, HttpListingAgencyResolver)


# ---------------------------------------------------------------------------
# (7) Factory: LISTING_AGENCY_RESOLVER_MODE=fake (default) → FakeListingAgencyResolver
# ---------------------------------------------------------------------------

def test_factory_fake_mode_returns_fake_resolver(monkeypatch):
    """get_listing_agency_resolver_provider() por defecto devuelve FakeListingAgencyResolver."""
    monkeypatch.delenv("LISTING_AGENCY_RESOLVER_MODE", raising=False)

    provider = get_listing_agency_resolver_provider()
    assert isinstance(provider, FakeListingAgencyResolver)
