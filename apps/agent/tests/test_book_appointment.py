"""Tests para book_appointment tool (HU-22 AC4)."""
import pytest
from agent.tools_langchain import book_appointment
from agent.booking import HttpAppointmentBooking, get_appointment_booking_provider
from agent.fakes import FakeAppointmentBooking
from agent.ports import AppointmentBookingPort


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
async def test_tool_409_conflict(monkeypatch):
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
    assert "check_agent_availability" in result["error"]


@pytest.mark.asyncio
async def test_tool_422_past_date(monkeypatch):
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
    assert "pasado" in result["error"]


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

    provider = HttpAppointmentBooking()
    result = await provider.book(LEAD_ID, SCHEDULED_AT, DURATION_MIN)

    assert captured["url"] == f"http://localhost:8000/leads/{LEAD_ID}/appointments"
    assert captured["json"] == {"scheduled_at": SCHEDULED_AT, "duration_min": DURATION_MIN}
    assert captured["headers"]["Authorization"] == "Bearer test-token"
    assert result["id"] == "uuid-abc"
    assert result["agent_id"] == "agent-real-001"
    assert result["status"] == "PENDING_CONFIRMATION"


@pytest.mark.asyncio
async def test_http_provider_no_auth_header_when_token_absent(monkeypatch):
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
    monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)

    provider = HttpAppointmentBooking()
    await provider.book(LEAD_ID, SCHEDULED_AT, DURATION_MIN)

    assert "Authorization" not in captured_headers


# --- factory ---

def test_factory_fake_mode(monkeypatch):
    monkeypatch.setenv("APPOINTMENT_BOOKING_MODE", "fake")
    provider = get_appointment_booking_provider()
    assert isinstance(provider, FakeAppointmentBooking)


def test_factory_http_mode(monkeypatch):
    monkeypatch.setenv("APPOINTMENT_BOOKING_MODE", "http")
    provider = get_appointment_booking_provider()
    assert isinstance(provider, HttpAppointmentBooking)


def test_factory_invalid_mode(monkeypatch):
    monkeypatch.setenv("APPOINTMENT_BOOKING_MODE", "invalid")
    with pytest.raises(ValueError, match="APPOINTMENT_BOOKING_MODE inválido"):
        get_appointment_booking_provider()
