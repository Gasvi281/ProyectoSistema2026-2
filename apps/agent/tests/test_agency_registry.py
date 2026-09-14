"""
test_agency_registry.py
------------------------
Pruebas del registry en memoria y de que los adaptadores HTTP lo usan
correctamente:
  (a) lead para listing→agency X → slots y book llevan X-Agency-Id: X
  (b) un segundo lead para agency Y queda aislado del primero
  (c) slots/book con un id no registrado lanza UnregisteredEntityError
      antes de cualquier llamada HTTP
"""
import os
import pytest

from agent import agency_registry
from agent.agency_registry import UnregisteredEntityError
from agent.backend_auth import get_auth_headers, _reset_provider_for_tests
import agent.backend_auth as backend_auth_module

# Agency IDs de prueba (no tienen que ser los de seed — solo distintos entre sí)
AGENCY_X = "8768a84f-a76a-4de6-8e9e-1a11fcbb4e59"  # Cruz-Oviedo Realty
AGENCY_Y = "bdd640fb-0667-4ad1-9c80-317fa3b1799d"  # González… Realty

LISTING_X = "listing-aaa"
LEAD_X    = "lead-aaa"
AGENT_X   = "agent-aaa"

LISTING_Y = "listing-bbb"
LEAD_Y    = "lead-bbb"
AGENT_Y   = "agent-bbb"


@pytest.fixture(autouse=True)
def clean_registry():
    """Aísla cada test vaciando el registry antes de que corra."""
    agency_registry.clear()
    yield
    agency_registry.clear()


# ---------------------------------------------------------------------------
# Pruebas del registry puro
# ---------------------------------------------------------------------------

def test_register_and_lookup_by_lead_id():
    agency_registry.register(listing_id=LISTING_X, lead_id=LEAD_X, agent_id=AGENT_X, agency_id=AGENCY_X)
    assert agency_registry.lookup(LEAD_X) == AGENCY_X


def test_register_and_lookup_by_agent_id():
    agency_registry.register(listing_id=LISTING_X, lead_id=LEAD_X, agent_id=AGENT_X, agency_id=AGENCY_X)
    assert agency_registry.lookup(AGENT_X) == AGENCY_X


def test_register_and_lookup_by_listing_id():
    agency_registry.register(listing_id=LISTING_X, agency_id=AGENCY_X)
    assert agency_registry.lookup(LISTING_X) == AGENCY_X


def test_unregistered_id_raises():
    with pytest.raises(UnregisteredEntityError):
        agency_registry.lookup("id-que-nunca-se-registró")


# ---------------------------------------------------------------------------
# (a) Registro correcto → get_auth_headers emite X-Agency-Id
# ---------------------------------------------------------------------------

async def test_get_auth_headers_includes_agency_id(monkeypatch):
    monkeypatch.setenv("BACKEND_SERVICE_TOKEN", "tok-test")
    monkeypatch.delenv("BOT_EMAIL", raising=False)
    monkeypatch.delenv("BOT_PASSWORD", raising=False)
    headers = await get_auth_headers(agency_id=AGENCY_X)
    assert headers["X-Agency-Id"] == AGENCY_X
    assert headers["Authorization"] == "Bearer tok-test"


async def test_get_auth_headers_without_agency_id_omits_header(monkeypatch):
    monkeypatch.setenv("BACKEND_SERVICE_TOKEN", "tok-test")
    monkeypatch.delenv("BOT_EMAIL", raising=False)
    monkeypatch.delenv("BOT_PASSWORD", raising=False)
    headers = await get_auth_headers()
    assert "X-Agency-Id" not in headers


# ---------------------------------------------------------------------------
# (b) Dos agencias en la misma sesión quedan aisladas
# ---------------------------------------------------------------------------

def test_two_agencies_isolated():
    agency_registry.register(lead_id=LEAD_X, agent_id=AGENT_X, agency_id=AGENCY_X)
    agency_registry.register(lead_id=LEAD_Y, agent_id=AGENT_Y, agency_id=AGENCY_Y)

    assert agency_registry.lookup(LEAD_X) == AGENCY_X
    assert agency_registry.lookup(AGENT_X) == AGENCY_X
    assert agency_registry.lookup(LEAD_Y) == AGENCY_Y
    assert agency_registry.lookup(AGENT_Y) == AGENCY_Y
    # Comprobar que no hay contaminación cruzada
    assert agency_registry.lookup(LEAD_X) != agency_registry.lookup(LEAD_Y)


# ---------------------------------------------------------------------------
# (c) Adaptadores HTTP lanzan UnregisteredEntityError antes del HTTP call
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_http_agent_slots_raises_before_http_on_unregistered(monkeypatch):
    """
    HttpAgentSlots.list_agent_slots debe lanzar UnregisteredEntityError
    (registry miss) antes de intentar cualquier llamada HTTP — validado sin
    necesidad de mockear httpx porque el fallo ocurre antes.
    """
    monkeypatch.setenv("BACKEND_URL", "https://example.com")
    monkeypatch.setenv("BACKEND_SERVICE_TOKEN", "tok-test")

    from agent.agent_slots import HttpAgentSlots

    adapter = HttpAgentSlots()
    # registry vacío — agent_id nunca registrado
    with pytest.raises(UnregisteredEntityError):
        await adapter.list_agent_slots(
            "agent-desconocido", "2026-09-10T00:00:00+00:00", "2026-09-17T23:59:59+00:00"
        )


@pytest.mark.asyncio
async def test_http_appointment_booking_raises_before_http_on_unregistered(monkeypatch):
    """
    HttpAppointmentBooking.book debe lanzar UnregisteredEntityError
    antes de intentar cualquier llamada HTTP.
    """
    monkeypatch.setenv("BACKEND_URL", "https://example.com")
    monkeypatch.setenv("BACKEND_SERVICE_TOKEN", "tok-test")

    from agent.booking import HttpAppointmentBooking

    adapter = HttpAppointmentBooking()
    with pytest.raises(UnregisteredEntityError):
        await adapter.book("lead-desconocido", "2026-09-10T09:00:00+00:00", 60)


# ---------------------------------------------------------------------------
# Integración: registry → headers correcto en adaptadores (con registry seeded)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_http_agent_slots_lookup_produces_correct_agency_header(monkeypatch):
    """
    Cuando agent_id está registrado, HttpAgentSlots debe incluir X-Agency-Id
    correcto en la llamada. Usamos respawn_httpx para capturar la request sin
    llegar al backend real.
    """
    monkeypatch.setenv("BACKEND_URL", "https://fake-backend.example")
    monkeypatch.setenv("BACKEND_SERVICE_TOKEN", "tok-test")

    agency_registry.register(agent_id=AGENT_X, agency_id=AGENCY_X)

    captured_headers: dict = {}

    import httpx

    class _FakeResponse:
        status_code = 200
        def raise_for_status(self): pass
        def json(self): return {"agent_id": AGENT_X, "slot_minutes": 30, "slots": []}

    class _FakeClient:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): pass
        async def get(self, url, *, params=None, headers=None):
            captured_headers.update(headers or {})
            return _FakeResponse()

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: _FakeClient())

    from agent.agent_slots import HttpAgentSlots
    adapter = HttpAgentSlots()
    await adapter.list_agent_slots(AGENT_X, "2026-09-10T00:00:00+00:00", "2026-09-17T23:59:59+00:00")

    assert captured_headers.get("X-Agency-Id") == AGENCY_X


@pytest.mark.asyncio
async def test_http_appointment_booking_lookup_produces_correct_agency_header(monkeypatch):
    """
    Cuando lead_id está registrado, HttpAppointmentBooking.book debe incluir
    X-Agency-Id correcto en la llamada.
    """
    monkeypatch.setenv("BACKEND_URL", "https://fake-backend.example")
    monkeypatch.setenv("BACKEND_SERVICE_TOKEN", "tok-test")

    agency_registry.register(lead_id=LEAD_X, agency_id=AGENCY_X)

    captured_headers: dict = {}

    import httpx

    class _FakeResponse:
        status_code = 201
        def raise_for_status(self): pass
        def json(self): return {"id": "appt-1", "status": "PENDING_CONFIRMATION"}

    class _FakeClient:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): pass
        async def post(self, url, *, json=None, headers=None):
            captured_headers.update(headers or {})
            return _FakeResponse()

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: _FakeClient())

    from agent.booking import HttpAppointmentBooking
    adapter = HttpAppointmentBooking()
    await adapter.book(LEAD_X, "2026-09-10T09:00:00+00:00", 60)

    assert captured_headers.get("X-Agency-Id") == AGENCY_X


# ---------------------------------------------------------------------------
# Precedencia de autenticación en get_auth_headers() (tarea de wiring)
# ---------------------------------------------------------------------------
# Todos los tests usan _reset_provider_for_tests() para descartar cualquier
# singleton vivo entre casos, y un fake provider para no llamar a Supabase.
# No llevan @pytest.mark.asyncio — asyncio_mode = "auto" en pyproject.toml.

class _FakeProvider:
    """Provider falso que devuelve un token fijo sin hacer ningún HTTP."""
    async def get_token(self) -> str:
        return "jwt-live-tok"


@pytest.fixture(autouse=False)
def reset_jwt_provider():
    """Descarta el singleton JWT antes y después de cada test de precedencia."""
    _reset_provider_for_tests()
    yield
    _reset_provider_for_tests()


async def test_jwt_preferred_over_static_token(monkeypatch, reset_jwt_provider):
    """BOT_EMAIL+BOT_PASSWORD configurados → live JWT; BACKEND_SERVICE_TOKEN ignorado."""
    monkeypatch.setenv("BOT_EMAIL", "bot@example.com")
    monkeypatch.setenv("BOT_PASSWORD", "s3cr3t")
    monkeypatch.setenv("BACKEND_SERVICE_TOKEN", "static-tok")
    backend_auth_module._provider = _FakeProvider()  # type: ignore[assignment]

    headers = await get_auth_headers()

    assert headers["Authorization"] == "Bearer jwt-live-tok"
    assert "X-Dev-Agent-Id" not in headers


async def test_jwt_beats_static_token_with_agency_id(monkeypatch, reset_jwt_provider):
    """Cuando ambos BOT_* y BACKEND_SERVICE_TOKEN están configurados, X-Agency-Id
    se emite correctamente usando el live JWT."""
    monkeypatch.setenv("BOT_EMAIL", "bot@example.com")
    monkeypatch.setenv("BOT_PASSWORD", "s3cr3t")
    monkeypatch.setenv("BACKEND_SERVICE_TOKEN", "static-tok")
    backend_auth_module._provider = _FakeProvider()  # type: ignore[assignment]

    headers = await get_auth_headers(agency_id=AGENCY_X)

    assert headers["Authorization"] == "Bearer jwt-live-tok"
    assert headers["X-Agency-Id"] == AGENCY_X


async def test_fallback_to_static_token(monkeypatch, reset_jwt_provider):
    """Sin BOT_*, con BACKEND_SERVICE_TOKEN → Authorization Bearer estático."""
    monkeypatch.delenv("BOT_EMAIL", raising=False)
    monkeypatch.delenv("BOT_PASSWORD", raising=False)
    monkeypatch.setenv("BACKEND_SERVICE_TOKEN", "static-only")

    headers = await get_auth_headers()

    assert headers["Authorization"] == "Bearer static-only"
    assert "X-Dev-Agent-Id" not in headers


async def test_fallback_to_dev_bypass(monkeypatch, reset_jwt_provider):
    """Sin BOT_* ni token estático, con DEV_AGENT_ID → X-Dev-Agent-Id; sin Authorization."""
    monkeypatch.delenv("BOT_EMAIL", raising=False)
    monkeypatch.delenv("BOT_PASSWORD", raising=False)
    monkeypatch.delenv("BACKEND_SERVICE_TOKEN", raising=False)
    monkeypatch.setenv("DEV_AGENT_ID", "dev-agent-xyz")

    headers = await get_auth_headers()

    assert headers.get("X-Dev-Agent-Id") == "dev-agent-xyz"
    assert "Authorization" not in headers


@pytest.mark.parametrize("present,missing", [
    ("BOT_EMAIL", "BOT_PASSWORD"),
    ("BOT_PASSWORD", "BOT_EMAIL"),
])
async def test_half_configured_bot_vars_raise(monkeypatch, reset_jwt_provider, present, missing):
    """Exactamente uno de BOT_EMAIL/BOT_PASSWORD configurado → ValueError fail-loud,
    aunque BACKEND_SERVICE_TOKEN también esté disponible (no hay fall-through)."""
    monkeypatch.setenv(present, "algún-valor")
    monkeypatch.delenv(missing, raising=False)
    monkeypatch.setenv("BACKEND_SERVICE_TOKEN", "static-tok")  # no debe usarse

    with pytest.raises(ValueError, match=missing):
        await get_auth_headers()


def test_check_backend_config_accepts_bot_email_password(monkeypatch):
    """check_backend_config no lanza si BACKEND_URL + BOT_EMAIL + BOT_PASSWORD están."""
    from agent.backend_auth import check_backend_config
    monkeypatch.setenv("BACKEND_URL", "https://homelitics.example.com")
    monkeypatch.setenv("BOT_EMAIL", "bot@example.com")
    monkeypatch.setenv("BOT_PASSWORD", "s3cr3t")
    monkeypatch.delenv("BACKEND_SERVICE_TOKEN", raising=False)
    monkeypatch.delenv("DEV_AGENT_ID", raising=False)

    check_backend_config()  # no debe lanzar
