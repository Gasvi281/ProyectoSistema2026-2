"""
test_client_resolver.py
-----------------------
Pruebas unitarias para HttpClientResolver y get_client_resolver_provider().

Patrón: monkeypatch.setenv para configuración + monkeypatch.setattr sobre
httpx.AsyncClient para interceptar llamadas HTTP — mismo estilo que
test_jwt_provider.py y test_create_or_get_lead.py.
Sin red real, sin pytest.mark.asyncio (asyncio_mode = "auto" en pyproject.toml).
"""

import json

import httpx
import pytest

from agent.client_resolver import HttpClientResolver, get_client_resolver_provider
from agent.fakes import FakeClientResolver


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_VALID_ENV = {
    "BACKEND_URL": "https://fake-backend.test",
    "BACKEND_SERVICE_TOKEN": "tok-test",
}

_CHAT_ID = "123456789"
_CLIENT_UUID = "6cdfee4d-a409-44a4-8a64-cf59ac9ec4ad"


def _set_valid_env(monkeypatch):
    for k, v in _VALID_ENV.items():
        monkeypatch.setenv(k, v)
    # Asegura que los modos de auth alternativos no interfieran
    monkeypatch.delenv("BOT_EMAIL",    raising=False)
    monkeypatch.delenv("BOT_PASSWORD", raising=False)
    monkeypatch.delenv("DEV_AGENT_ID", raising=False)


def _make_clients_response(
    client_id: str = _CLIENT_UUID,
    status: int = 201,
) -> httpx.Response:
    """Construye un httpx.Response real que simula la respuesta de POST /clients."""
    request = httpx.Request("POST", "https://fake-backend.test/clients")
    content = json.dumps({"id": client_id, "created_at": "2026-09-14T12:00:00Z"}).encode()
    return httpx.Response(status, content=content, request=request)


def _make_error_response(status: int) -> httpx.Response:
    request = httpx.Request("POST", "https://fake-backend.test/clients")
    return httpx.Response(status, content=b'{"detail":"error"}', request=request)


# ---------------------------------------------------------------------------
# (1) 201 → cliente nuevo, devuelve su id
# ---------------------------------------------------------------------------

async def test_resolve_client_201_returns_id(monkeypatch):
    """Respuesta 201 (cliente nuevo) → devuelve el UUID del campo 'id'."""
    _set_valid_env(monkeypatch)

    async def mock_post(self, url, *, json=None, headers=None, **kw):
        return _make_clients_response(status=201)

    monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)

    resolver = HttpClientResolver()
    result = await resolver.resolve_client(_CHAT_ID)
    assert result == _CLIENT_UUID


# ---------------------------------------------------------------------------
# (2) 200 (dedup) → también éxito, devuelve el id existente
# ---------------------------------------------------------------------------

async def test_resolve_client_200_dedup_also_returns_id(monkeypatch):
    """Respuesta 200 (cliente ya existía, dedup por telegram_user_id) → éxito, mismo id."""
    _set_valid_env(monkeypatch)

    async def mock_post(self, url, *, json=None, headers=None, **kw):
        return _make_clients_response(status=200)

    monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)

    resolver = HttpClientResolver()
    result = await resolver.resolve_client(_CHAT_ID)
    assert result == _CLIENT_UUID


# ---------------------------------------------------------------------------
# (3) Body: placeholder cuando full_name es None; telegram_user_id == int(chat_id)
# ---------------------------------------------------------------------------

async def test_body_placeholder_full_name_when_none(monkeypatch):
    """Sin full_name → manda 'Telegram user <chat_id>'. telegram_user_id = int(chat_id)."""
    _set_valid_env(monkeypatch)
    captured = {}

    async def mock_post(self, url, *, json=None, headers=None, **kw):
        captured["body"] = json
        return _make_clients_response()

    monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)

    resolver = HttpClientResolver()
    await resolver.resolve_client(_CHAT_ID)

    body = captured["body"]
    assert body["full_name"] == f"Telegram user {_CHAT_ID}"
    assert body["telegram_user_id"] == int(_CHAT_ID)
    assert body["email"] is None


# ---------------------------------------------------------------------------
# (4) full_name explícito → se usa tal cual, sin placeholder
# ---------------------------------------------------------------------------

async def test_body_uses_explicit_full_name(monkeypatch):
    """Cuando se pasa full_name, se envía sin modificar."""
    _set_valid_env(monkeypatch)
    captured = {}

    async def mock_post(self, url, *, json=None, headers=None, **kw):
        captured["body"] = json
        return _make_clients_response()

    monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)

    resolver = HttpClientResolver()
    await resolver.resolve_client(_CHAT_ID, full_name="María García")

    assert captured["body"]["full_name"] == "María García"


# ---------------------------------------------------------------------------
# (5) phone pasa a través del body
# ---------------------------------------------------------------------------

async def test_body_passes_phone_through(monkeypatch):
    """El parámetro phone se incluye en el body enviado al backend."""
    _set_valid_env(monkeypatch)
    captured = {}

    async def mock_post(self, url, *, json=None, headers=None, **kw):
        captured["body"] = json
        return _make_clients_response()

    monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)

    resolver = HttpClientResolver()
    await resolver.resolve_client(_CHAT_ID, phone="+573001234567")

    assert captured["body"]["phone"] == "+573001234567"


# ---------------------------------------------------------------------------
# (6) Headers: Authorization presente; X-Agency-Id ausente
# ---------------------------------------------------------------------------

async def test_headers_include_caller_agency_id(monkeypatch):
    """Authorization + X-Agency-Id (identidad del caller, env AGENCY_ID)."""
    _set_valid_env(monkeypatch)
    monkeypatch.setenv("AGENCY_ID", "8768a84f-a76a-4de6-8e9e-1a11fcbb4e59")
    captured = {}

    async def mock_post(self, url, *, json=None, headers=None, **kw):
        captured["headers"] = headers or {}
        return _make_clients_response()

    monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)

    resolver = HttpClientResolver()
    await resolver.resolve_client(_CHAT_ID)

    assert "Authorization" in captured["headers"]
    assert captured["headers"]["X-Agency-Id"] == "8768a84f-a76a-4de6-8e9e-1a11fcbb4e59"


# ---------------------------------------------------------------------------
# (7) chat_id no-numérico → ValueError estricto, no llega al backend
# ---------------------------------------------------------------------------

async def test_non_numeric_chat_id_raises_value_error(monkeypatch):
    """chat_id no-numérico levanta ValueError (int() estricto). No contacta al backend."""
    _set_valid_env(monkeypatch)
    post_called = []

    async def mock_post(self, url, *, json=None, headers=None, **kw):
        post_called.append(True)
        return _make_clients_response()

    monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)

    resolver = HttpClientResolver()
    with pytest.raises(ValueError):
        await resolver.resolve_client("no-es-numero")

    assert not post_called, "No debe llamar al backend si chat_id no parsea a int"


# ---------------------------------------------------------------------------
# (8) Error HTTP (4xx/5xx) → propaga HTTPStatusError
# ---------------------------------------------------------------------------

async def test_http_error_propagates(monkeypatch):
    """Respuesta 4xx levanta httpx.HTTPStatusError (raise_for_status)."""
    _set_valid_env(monkeypatch)

    async def mock_post(self, url, *, json=None, headers=None, **kw):
        return _make_error_response(403)

    monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)

    resolver = HttpClientResolver()
    with pytest.raises(httpx.HTTPStatusError):
        await resolver.resolve_client(_CHAT_ID)


# ---------------------------------------------------------------------------
# (9) Factory: CLIENT_RESOLVER_MODE=http → HttpClientResolver
# ---------------------------------------------------------------------------

async def test_factory_http_mode_returns_http_resolver(monkeypatch):
    """get_client_resolver_provider() con CLIENT_RESOLVER_MODE=http devuelve HttpClientResolver."""
    _set_valid_env(monkeypatch)
    monkeypatch.setenv("CLIENT_RESOLVER_MODE", "http")

    provider = get_client_resolver_provider()
    assert isinstance(provider, HttpClientResolver)


# ---------------------------------------------------------------------------
# (10) Factory: CLIENT_RESOLVER_MODE=fake (default) → FakeClientResolver
# ---------------------------------------------------------------------------

async def test_factory_fake_mode_returns_fake_resolver(monkeypatch):
    """get_client_resolver_provider() por defecto devuelve FakeClientResolver."""
    monkeypatch.delenv("CLIENT_RESOLVER_MODE", raising=False)

    provider = get_client_resolver_provider()
    assert isinstance(provider, FakeClientResolver)
