"""Tests para book_appointment tool (HU-22 AC4)."""
import json
import pytest
from agent.tools_langchain import book_appointment
from agent.booking import HttpAppointmentBooking, get_appointment_booking_provider
from agent.fakes import FakeAppointmentBooking
from agent.ports import AppointmentBookingPort
from agent import agency_registry
from agent.booking_recovery import (
    UNAVAILABLE, TAKEN, OPEN_VISIT, CLOSED_LEAD, TOO_SOON, UNKNOWN,
    DETAIL_UNAVAILABLE, DETAIL_OPEN_VISIT, DETAIL_CLOSED_LEAD,
)


LEAD_ID = "lead-test-001"
SCHEDULED_AT = "2026-09-10T09:00:00+00:00"
DURATION_MIN = 60


# --- FakeAppointmentBooking ---

@pytest.mark.asyncio
async def test_fake_returns_appointment():
    provider = FakeAppointmentBooking()
    result = await provider.book(LEAD_ID, SCHEDULED_AT, DURATION_MIN)
    assert result["lead_id"] == LEAD_ID
    assert result["scheduled_at"] == SCHEDULED_AT
    assert result["duration_min"] == DURATION_MIN
    assert result["status"] == "PENDING_CONFIRMATION"
    assert result["agent_id"] == "agent-fake"
    assert result["id"].startswith("appt-")
    assert "created_at" in result and "updated_at" in result


# --- book_appointment tool (modo fake por defecto) ---

@pytest.mark.asyncio
async def test_tool_fake_mode_success(monkeypatch):
    monkeypatch.setenv("APPOINTMENT_BOOKING_MODE", "fake")
    result = await book_appointment.ainvoke(
        {"lead_id": LEAD_ID, "scheduled_at": SCHEDULED_AT, "duration_min": DURATION_MIN}
    )
    assert result["lead_id"] == LEAD_ID
    assert result["status"] == "PENDING_CONFIRMATION"
    assert result["error"] is None
    assert result["error_code"] is None


@pytest.mark.asyncio
async def test_tool_default_duration(monkeypatch):
    monkeypatch.setenv("APPOINTMENT_BOOKING_MODE", "fake")
    result = await book_appointment.ainvoke(
        {"lead_id": LEAD_ID, "scheduled_at": SCHEDULED_AT}
    )
    assert result["duration_min"] == 60
    assert result["error"] is None


# --- manejo de errores HTTP ---

@pytest.mark.asyncio
async def test_tool_409_conflict_no_body(monkeypatch):
    """409 sin body JSON → UNKNOWN → mensaje seguro (sin "check_agent_availability" hardcoded)."""
    import httpx

    class ConflictProvider(AppointmentBookingPort):
        async def book(self, lead_id, scheduled_at, duration_min):
            resp = httpx.Response(409, request=httpx.Request("POST", "http://x"))
            raise httpx.HTTPStatusError("conflict", request=resp.request, response=resp)

    monkeypatch.setattr("agent.booking.get_appointment_booking_provider", lambda: ConflictProvider())
    result = await book_appointment.ainvoke(
        {"lead_id": LEAD_ID, "scheduled_at": SCHEDULED_AT, "duration_min": DURATION_MIN}
    )
    assert result["error_code"] == 409
    assert result["error"] is not None
    # Sin detail reconocido → UNKNOWN → mensaje seguro genérico
    from agent.booking_recovery import UNKNOWN
    assert result["category"] == UNKNOWN


@pytest.mark.asyncio
async def test_tool_422_no_body(monkeypatch):
    """422 sin body JSON → UNKNOWN → mensaje seguro."""
    import httpx

    class PastDateProvider(AppointmentBookingPort):
        async def book(self, lead_id, scheduled_at, duration_min):
            resp = httpx.Response(422, request=httpx.Request("POST", "http://x"))
            raise httpx.HTTPStatusError("unprocessable", request=resp.request, response=resp)

    monkeypatch.setattr("agent.booking.get_appointment_booking_provider", lambda: PastDateProvider())
    result = await book_appointment.ainvoke(
        {"lead_id": LEAD_ID, "scheduled_at": SCHEDULED_AT, "duration_min": DURATION_MIN}
    )
    assert result["error_code"] == 422
    assert result["error"] is not None
    from agent.booking_recovery import UNKNOWN
    assert result["category"] == UNKNOWN


@pytest.mark.asyncio
async def test_tool_generic_error(monkeypatch):
    class FailingProvider(AppointmentBookingPort):
        async def book(self, lead_id, scheduled_at, duration_min):
            raise RuntimeError("connection refused")

    monkeypatch.setattr("agent.booking.get_appointment_booking_provider", lambda: FailingProvider())
    result = await book_appointment.ainvoke(
        {"lead_id": LEAD_ID, "scheduled_at": SCHEDULED_AT, "duration_min": DURATION_MIN}
    )
    assert result["error"] is not None
    assert result["error_code"] is None
    assert "connection refused" in result["error"]


# --- HttpAppointmentBooking parseo de respuesta (unit, sin HTTP real) ---

@pytest.mark.asyncio
async def test_http_provider_post_body_and_response(monkeypatch):
    import httpx

    captured = {}
    backend_response = {
        "id": "uuid-abc",
        "lead_id": LEAD_ID,
        "agent_id": "agent-real-001",
        "scheduled_at": SCHEDULED_AT,
        "duration_min": DURATION_MIN,
        "status": "PENDING_CONFIRMATION",
        "created_at": "2026-09-07T12:00:00+00:00",
        "updated_at": "2026-09-07T12:00:00+00:00",
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
    # El adapter requiere que el lead_id esté en el registry (Alt 3).
    agency_registry.register(lead_id=LEAD_ID, agency_id="agency-test-x")

    provider = HttpAppointmentBooking()
    result = await provider.book(LEAD_ID, SCHEDULED_AT, DURATION_MIN)

    assert captured["url"] == f"http://localhost:8000/leads/{LEAD_ID}/appointments"
    assert captured["json"] == {"scheduled_at": SCHEDULED_AT, "duration_min": DURATION_MIN}
    assert captured["headers"]["Authorization"] == "Bearer test-token"
    assert result["id"] == "uuid-abc"
    assert result["agent_id"] == "agent-real-001"
    assert result["status"] == "PENDING_CONFIRMATION"


def test_http_provider_raises_if_no_auth(monkeypatch):
    """HttpAppointmentBooking falla en construcción si ningún mecanismo de auth está configurado.
    El envío silencioso sin autenticar quedó eliminado — esto reemplaza
    test_http_provider_no_auth_header_when_token_absent."""
    monkeypatch.setenv("BACKEND_URL", "http://localhost:8000")
    monkeypatch.delenv("BACKEND_SERVICE_TOKEN", raising=False)
    monkeypatch.delenv("DEV_AGENT_ID", raising=False)
    with pytest.raises(ValueError, match="BACKEND_SERVICE_TOKEN"):
        HttpAppointmentBooking()


@pytest.mark.asyncio
async def test_http_provider_sends_dev_agent_id_header(monkeypatch):
    """HttpAppointmentBooking envía X-Dev-Agent-Id cuando solo DEV_AGENT_ID está configurado."""
    import httpx

    captured_headers = {}

    async def mock_post(self, url, json=None, headers=None):
        captured_headers.update(headers or {})

        class FakeResp:
            status_code = 201
            def raise_for_status(self): pass
            def json(self): return {"id": "x", "lead_id": LEAD_ID, "agent_id": "a",
                                    "scheduled_at": SCHEDULED_AT, "duration_min": 60,
                                    "status": "PENDING_CONFIRMATION",
                                    "created_at": "2026-09-07T12:00:00+00:00",
                                    "updated_at": "2026-09-07T12:00:00+00:00"}
        return FakeResp()

    monkeypatch.setenv("BACKEND_URL", "http://localhost:8000")
    monkeypatch.delenv("BACKEND_SERVICE_TOKEN", raising=False)
    monkeypatch.setenv("DEV_AGENT_ID", "dev-agent-123")
    monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)
    # El adapter requiere que el lead_id esté en el registry (Alt 3).
    agency_registry.register(lead_id=LEAD_ID, agency_id="agency-test-x")

    provider = HttpAppointmentBooking()
    await provider.book(LEAD_ID, SCHEDULED_AT, DURATION_MIN)

    assert captured_headers.get("X-Dev-Agent-Id") == "dev-agent-123"
    assert "Authorization" not in captured_headers


# --- factory ---

def test_factory_fake_mode(monkeypatch):
    monkeypatch.setenv("APPOINTMENT_BOOKING_MODE", "fake")
    provider = get_appointment_booking_provider()
    assert isinstance(provider, FakeAppointmentBooking)


def test_factory_http_mode(monkeypatch):
    monkeypatch.setenv("APPOINTMENT_BOOKING_MODE", "http")
    monkeypatch.setenv("BACKEND_URL", "http://localhost:8000")
    monkeypatch.setenv("DEV_AGENT_ID", "dev-agent-test")
    provider = get_appointment_booking_provider()
    assert isinstance(provider, HttpAppointmentBooking)


def test_factory_invalid_mode(monkeypatch):
    monkeypatch.setenv("APPOINTMENT_BOOKING_MODE", "invalid")
    with pytest.raises(ValueError, match="APPOINTMENT_BOOKING_MODE inválido"):
        get_appointment_booking_provider()


# ---------------------------------------------------------------------------
# Integración: clasificación + alternativas (fakes, HU-22 AC3)
# ---------------------------------------------------------------------------

def _make_409_provider(detail_substring: str):
    """Helper: proveedor que lanza httpx.HTTPStatusError 409 con detail dado."""
    import httpx

    class Provider(AppointmentBookingPort):
        async def book(self, lead_id, scheduled_at, duration_min):
            resp = httpx.Response(
                409,
                content=json.dumps({"detail": detail_substring}).encode(),
                headers={"Content-Type": "application/json"},
                request=httpx.Request("POST", "http://x"),
            )
            raise httpx.HTTPStatusError("conflict", request=resp.request, response=resp)

    return Provider()


def _make_422_provider(detail_substring: str):
    import httpx

    class Provider(AppointmentBookingPort):
        async def book(self, lead_id, scheduled_at, duration_min):
            resp = httpx.Response(
                422,
                content=json.dumps({"detail": detail_substring}).encode(),
                headers={"Content-Type": "application/json"},
                request=httpx.Request("POST", "http://x"),
            )
            raise httpx.HTTPStatusError("unprocessable", request=resp.request, response=resp)

    return Provider()


AGENT_ID = "agent-fake"
# Slot del mismo día UTC/Bogotá que SCHEDULED_AT (2026-09-10T09:00Z = 04:00 Bogotá día 10)
ALT_SLOT = "2026-09-10T11:00:00+00:00"  # 06:00 Bogotá día 10


@pytest.mark.asyncio
async def test_unavailable_returns_alternatives(monkeypatch):
    """`unavailable` (409 + DETAIL_UNAVAILABLE) → category + alternatives list."""
    from agent.fakes import FakeAgentSlots
    monkeypatch.setattr(
        "agent.booking.get_appointment_booking_provider",
        lambda: _make_409_provider(DETAIL_UNAVAILABLE),
    )
    # FakeAgentSlots devuelve slots fijos; AGENT_SLOTS_MODE=fake es el default.
    monkeypatch.setenv("AGENT_SLOTS_MODE", "fake")

    result = await book_appointment.ainvoke(
        {"lead_id": LEAD_ID, "scheduled_at": SCHEDULED_AT,
         "duration_min": DURATION_MIN, "agent_id": AGENT_ID}
    )
    assert result["error_code"] == 409
    assert result["category"] == UNAVAILABLE
    assert isinstance(result["alternatives"], list)
    assert len(result["alternatives"]) > 0
    alt = result["alternatives"][0]
    assert "scheduled_at" in alt
    assert "display" in alt
    assert "Bogotá" in alt["display"]


@pytest.mark.asyncio
async def test_open_visit_no_alternatives(monkeypatch):
    """`open_visit` → no alternatives, clear message."""
    monkeypatch.setattr(
        "agent.booking.get_appointment_booking_provider",
        lambda: _make_409_provider(DETAIL_OPEN_VISIT),
    )
    result = await book_appointment.ainvoke(
        {"lead_id": LEAD_ID, "scheduled_at": SCHEDULED_AT,
         "duration_min": DURATION_MIN, "agent_id": AGENT_ID}
    )
    assert result["error_code"] == 409
    assert result["category"] == OPEN_VISIT
    assert result["alternatives"] == []
    assert result["error"] is not None


@pytest.mark.asyncio
async def test_closed_lead_no_alternatives(monkeypatch):
    """`closed_lead` → no alternatives, clear message."""
    monkeypatch.setattr(
        "agent.booking.get_appointment_booking_provider",
        lambda: _make_409_provider(DETAIL_CLOSED_LEAD),
    )
    result = await book_appointment.ainvoke(
        {"lead_id": LEAD_ID, "scheduled_at": SCHEDULED_AT,
         "duration_min": DURATION_MIN, "agent_id": AGENT_ID}
    )
    assert result["error_code"] == 409
    assert result["category"] == CLOSED_LEAD
    assert result["alternatives"] == []


@pytest.mark.asyncio
async def test_missing_agent_id_returns_safe_message(monkeypatch):
    """Cuando agent_id no se proporciona, retorna mensaje seguro sin alternativas y no lanza."""
    monkeypatch.setattr(
        "agent.booking.get_appointment_booking_provider",
        lambda: _make_409_provider(DETAIL_UNAVAILABLE),
    )
    result = await book_appointment.ainvoke(
        {"lead_id": LEAD_ID, "scheduled_at": SCHEDULED_AT, "duration_min": DURATION_MIN}
        # agent_id ausente
    )
    assert result["error_code"] == 409
    assert result["category"] == UNAVAILABLE
    assert result["alternatives"] == []
    assert result["error"] is not None


@pytest.mark.asyncio
async def test_slots_fetch_failure_returns_safe_message(monkeypatch):
    """Si la consulta de slots falla, retorna mensaje seguro y no lanza."""
    from agent.ports import AgentSlotsPort

    class FailingSlots(AgentSlotsPort):
        async def list_agent_slots(self, agent_id, date_from, date_to):
            raise RuntimeError("network error")

    monkeypatch.setattr(
        "agent.booking.get_appointment_booking_provider",
        lambda: _make_409_provider(DETAIL_UNAVAILABLE),
    )
    monkeypatch.setattr(
        "agent.agent_slots.get_agent_slots_provider",
        lambda: FailingSlots(),
    )

    result = await book_appointment.ainvoke(
        {"lead_id": LEAD_ID, "scheduled_at": SCHEDULED_AT,
         "duration_min": DURATION_MIN, "agent_id": AGENT_ID}
    )
    assert result["error"] is not None
    assert result["alternatives"] == []
    # El tool NO debe lanzar


@pytest.mark.asyncio
async def test_unknown_error_logged_and_safe_message(monkeypatch, caplog):
    """`unknown` → safe message + warning logged."""
    import logging, httpx

    class UnknownProvider(AppointmentBookingPort):
        async def book(self, lead_id, scheduled_at, duration_min):
            resp = httpx.Response(
                409,
                content=json.dumps({"detail": "completely unrecognized error"}).encode(),
                headers={"Content-Type": "application/json"},
                request=httpx.Request("POST", "http://x"),
            )
            raise httpx.HTTPStatusError("unknown", request=resp.request, response=resp)

    monkeypatch.setattr(
        "agent.booking.get_appointment_booking_provider",
        lambda: UnknownProvider(),
    )
    with caplog.at_level(logging.WARNING, logger="agent.tools_langchain"):
        result = await book_appointment.ainvoke(
            {"lead_id": LEAD_ID, "scheduled_at": SCHEDULED_AT,
             "duration_min": DURATION_MIN, "agent_id": AGENT_ID}
        )
    assert result["category"] == UNKNOWN
    assert result["alternatives"] == []
    assert result["error"] is not None
    assert any("no reconocido" in r.message or "status" in r.message.lower()
               for r in caplog.records), "Se esperaba un warning para UNKNOWN"
