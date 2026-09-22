"""
test_scheduling_flow_integration.py
-----------------------------------
Test de integración de la cadena de agendamiento a través de las tools reales:

    resolve_client → create_or_get_lead → check_agent_availability → book_appointment

Verifica dos cosas:
  (1) El handoff de datos: el output de cada paso alimenta el input del siguiente
      (client_id → lead; agent_id derivado → availability; lead_id + slot → booking).
  (2) Que el orden se hace cumplir: en modo http, saltarse create_or_get_lead hace
      que check_agent_availability falle con UnregisteredEntityError ANTES de tocar HTTP.

Sin red real: modo fake para el happy path; httpx mockeado para el caso de orden.
Estilo async: @pytest.mark.asyncio, igual que los tests de tools vecinos
(test_create_or_get_lead.py, test_book_appointment.py, test_agent_availability.py).
"""
import httpx
import pytest

from agent import agency_registry
from agent.tools_langchain import (
    create_or_get_lead,
    check_agent_availability,
    book_appointment,
)
from agent.client_resolver import get_client_resolver_provider
from agent.fakes import SEED_CLIENT_ID, SEED_LISTING_ID, SEED_AGENT_ID


CHAT_ID = "telegram_98765"

_DATE_FROM = "2026-09-10T00:00:00+00:00"
_DATE_TO = "2026-09-17T23:59:59+00:00"


@pytest.fixture(autouse=True)
def clean_registry():
    """Aísla cada test: la tool create_or_get_lead escribe en el registry global."""
    agency_registry.clear()
    yield
    agency_registry.clear()


# ---------------------------------------------------------------------------
# (1) Handoff de la cadena completa en modo fake
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_full_scheduling_chain_handoff(monkeypatch):
    """El output de cada paso alimenta el input del siguiente, en orden estricto."""
    for var in (
        "LEAD_MODE",
        "AGENT_SLOTS_MODE",
        "APPOINTMENT_BOOKING_MODE",
        "CLIENT_RESOLVER_MODE",
        "LISTING_AGENCY_RESOLVER_MODE",
    ):
        monkeypatch.setenv(var, "fake")

    # Paso 0 — resolve_client: chat_id → client_id de backend
    resolver = get_client_resolver_provider()
    client_id = await resolver.resolve_client(CHAT_ID)
    assert client_id == SEED_CLIENT_ID

    # Paso 1 — create_or_get_lead(client_id, listing_id) consume el client_id del paso 0
    lead = await create_or_get_lead.ainvoke(
        {"client_id": client_id, "listing_id": SEED_LISTING_ID}
    )
    assert lead["error"] is None, f"lead falló: {lead.get('error')}"
    assert lead["client_id"] == client_id           # handoff 0 → 1
    lead_id = lead["id"]
    agent_id = lead["agent_id"]
    assert agent_id == SEED_AGENT_ID

    # Paso 2 — check_agent_availability(agent_id) consume el agent_id derivado del lead
    avail = await check_agent_availability.ainvoke(
        {"agent_id": agent_id, "date_from": _DATE_FROM, "date_to": _DATE_TO}
    )
    assert avail["error"] is None
    assert avail["agent_id"] == agent_id            # handoff 1 → 2
    assert avail["slots"], "el fake debe devolver slots"
    slot_start = avail["slots"][0]["start"]

    # Paso 3 — book_appointment(lead_id, slot) consume el lead_id (paso 1) y el slot (paso 2)
    appt = await book_appointment.ainvoke(
        {"lead_id": lead_id, "scheduled_at": slot_start, "duration_min": 60}
    )
    assert appt["error"] is None
    assert appt["lead_id"] == lead_id               # handoff 1 → 3
    assert appt["scheduled_at"] == slot_start       # handoff 2 → 3
    assert appt["status"] == "PENDING_CONFIRMATION"


# ---------------------------------------------------------------------------
# (2) El orden se hace cumplir: sin lead previo, availability falla antes de HTTP
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_availability_before_lead_is_blocked(monkeypatch):
    """En modo http, check_agent_availability sin create_or_get_lead previo lanza
    UnregisteredEntityError ANTES de cualquier llamada HTTP (gate del agency_registry)."""
    monkeypatch.setenv("AGENT_SLOTS_MODE", "http")
    monkeypatch.setenv("BACKEND_URL", "https://fake-backend.test")
    monkeypatch.setenv("BACKEND_SERVICE_TOKEN", "tok-test")
    monkeypatch.delenv("BOT_EMAIL", raising=False)
    monkeypatch.delenv("BOT_PASSWORD", raising=False)
    # registry vacío por el fixture clean_registry → el agent_id nunca fue registrado

    called = []

    async def boom_get(self, *args, **kwargs):
        called.append(True)
        raise AssertionError("no debe llegar a HTTP sin create_or_get_lead previo")

    monkeypatch.setattr(httpx.AsyncClient, "get", boom_get)

    result = await check_agent_availability.ainvoke(
        {"agent_id": "agent-no-registrado", "date_from": _DATE_FROM, "date_to": _DATE_TO}
    )

    assert result["slots"] == []
    assert result["error"] is not None
    # El mensaje de UnregisteredEntityError menciona el paso que faltó
    assert "create_or_get_lead" in result["error"]
    assert not called, "no debió intentar HTTP antes del gate del registry"
