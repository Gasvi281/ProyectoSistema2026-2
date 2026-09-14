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
from agent.backend_auth import get_auth_headers

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

def test_get_auth_headers_includes_agency_id(monkeypatch):
    monkeypatch.setenv("BACKEND_SERVICE_TOKEN", "tok-test")
    headers = get_auth_headers(agency_id=AGENCY_X)
    assert headers["X-Agency-Id"] == AGENCY_X
    assert headers["Authorization"] == "Bearer tok-test"


def test_get_auth_headers_without_agency_id_omits_header(monkeypatch):
    monkeypatch.setenv("BACKEND_SERVICE_TOKEN", "tok-test")
    headers = get_auth_headers()
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
