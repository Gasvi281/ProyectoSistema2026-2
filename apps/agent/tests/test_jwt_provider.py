"""
test_jwt_provider.py
--------------------
Pruebas unitarias para SupabaseJwtProvider (jwt_provider.py, tarea 3.9).

Patrón de mocking: monkeypatch.setenv para configuración y
monkeypatch.setattr(httpx.AsyncClient, "post", mock_post) para las
llamadas HTTP — mismo estilo que test_create_or_get_lead.py y
test_book_appointment.py.

El reloj se controla con un callable falso inyectado en el constructor,
sin freezegun ni dependencias externas adicionales.
"""

from datetime import datetime, timedelta, timezone

import httpx
import pytest

from agent.jwt_provider import SupabaseJwtProvider, _REFRESH_SKEW_SECONDS

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_VALID_ENV = {
    "SUPABASE_URL": "https://fake.supabase.co",
    "SUPABASE_ANON_KEY": "anon-key-test",
    "BOT_EMAIL": "bot@example.com",
    "BOT_PASSWORD": "s3cr3t",
}

_EPOCH = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


def _set_valid_env(monkeypatch):
    """Fija las cuatro variables de entorno requeridas."""
    for k, v in _VALID_ENV.items():
        monkeypatch.setenv(k, v)


def _make_login_response(
    token: str = "tok-abc",
    expires_in: int = 3600,
    status: int = 200,
) -> httpx.Response:
    """Construye un httpx.Response falso que simula la respuesta de Supabase Auth."""
    request = httpx.Request("POST", "https://fake.supabase.co/auth/v1/token")
    if status == 200:
        import json
        content = json.dumps({"access_token": token, "expires_in": expires_in}).encode()
        return httpx.Response(status, content=content, request=request)
    else:
        return httpx.Response(status, content=b'{"error":"invalid_credentials"}', request=request)


# ---------------------------------------------------------------------------
# (1) Primera llamada hace login y retorna el access_token
# ---------------------------------------------------------------------------

async def test_first_get_token_logs_in(monkeypatch):
    """get_token() hace POST al endpoint de Supabase y retorna el access_token."""
    _set_valid_env(monkeypatch)

    llamadas = []

    async def mock_post(self, url, *, json=None, headers=None, params=None, **kw):
        llamadas.append({"url": url, "json": json, "headers": headers, "params": params})
        return _make_login_response(token="tok-primero", expires_in=3600)

    monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)

    provider = SupabaseJwtProvider(now=lambda: _EPOCH)
    token = await provider.get_token()

    assert token == "tok-primero"
    assert len(llamadas) == 1
    assert llamadas[0]["params"] == {"grant_type": "password"}
    assert llamadas[0]["headers"]["apikey"] == "anon-key-test"
    assert llamadas[0]["json"] == {
        "email": "bot@example.com",
        "password": "s3cr3t",
    }
    assert "supabase.co/auth/v1/token" in llamadas[0]["url"]


# ---------------------------------------------------------------------------
# (2) Segunda llamada dentro de la validez usa la caché — no re-autentica
# ---------------------------------------------------------------------------

async def test_cached_token_within_validity(monkeypatch):
    """Segunda llamada con reloj avanzado levemente no repite el POST."""
    _set_valid_env(monkeypatch)

    llamadas = []

    async def mock_post(self, url, **kw):
        llamadas.append(1)
        return _make_login_response(token="tok-cache", expires_in=3600)

    monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)

    # Reloj mutable: avanza solo 1 segundo entre llamadas
    tiempo = [_EPOCH]
    provider = SupabaseJwtProvider(now=lambda: tiempo[0])

    t1 = await provider.get_token()
    tiempo[0] = _EPOCH + timedelta(seconds=1)  # muy dentro de la validez
    t2 = await provider.get_token()

    assert t1 == t2 == "tok-cache"
    assert len(llamadas) == 1  # solo un POST, el segundo usó caché


# ---------------------------------------------------------------------------
# (3) Renovación proactiva: pasado el umbral se re-autentica
# ---------------------------------------------------------------------------

async def test_proactive_refresh_past_skew(monkeypatch):
    """Cuando el reloj supera expires_at - skew, la siguiente llamada renueva el token."""
    _set_valid_env(monkeypatch)

    respuestas = [
        _make_login_response(token="tok-inicial", expires_in=3600),
        _make_login_response(token="tok-renovado", expires_in=3600),
    ]
    llamadas = []

    async def mock_post(self, url, **kw):
        llamadas.append(1)
        return respuestas[len(llamadas) - 1]

    monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)

    tiempo = [_EPOCH]
    provider = SupabaseJwtProvider(now=lambda: tiempo[0])

    t1 = await provider.get_token()
    assert t1 == "tok-inicial"

    # Avanzar el reloj hasta justo dentro del umbral de renovación (expires_at - skew + 1s)
    tiempo[0] = _EPOCH + timedelta(seconds=3600 - _REFRESH_SKEW_SECONDS + 1)
    t2 = await provider.get_token()

    assert t2 == "tok-renovado"
    assert len(llamadas) == 2  # se hicieron dos POST


# ---------------------------------------------------------------------------
# (4) Variables de entorno faltantes → ValueError al primer uso
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("missing_var", [
    "SUPABASE_URL",
    "SUPABASE_ANON_KEY",
    "BOT_EMAIL",
    "BOT_PASSWORD",
])
async def test_missing_env_var_raises_value_error(monkeypatch, missing_var):
    """Falta cualquiera de las 4 variables → ValueError en get_token(), no en __init__."""
    _set_valid_env(monkeypatch)
    monkeypatch.delenv(missing_var)

    # El constructor no debe lanzar aunque falte la variable (validación perezosa)
    provider = SupabaseJwtProvider(now=lambda: _EPOCH)

    with pytest.raises(ValueError, match=missing_var):
        await provider.get_token()


# ---------------------------------------------------------------------------
# (5) Login fallido (400/401) → httpx.HTTPStatusError, no KeyError
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("status", [400, 401])
async def test_failed_login_raises_http_status_error(monkeypatch, status):
    """Un 400/401 de Supabase lanza HTTPStatusError, no un KeyError en access_token."""
    _set_valid_env(monkeypatch)

    async def mock_post(self, url, **kw):
        return _make_login_response(status=status)

    monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)

    provider = SupabaseJwtProvider(now=lambda: _EPOCH)

    with pytest.raises(httpx.HTTPStatusError):
        await provider.get_token()
