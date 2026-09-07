"""Tests para check_agent_availability tool (HU-22 AC1)."""
import pytest
from datetime import datetime, timedelta, timezone
from agent.tools_langchain import check_agent_availability
from agent.agent_slots import _iso_add_minutes, HttpAgentSlots
from agent.fakes import FakeAgentSlots
from agent.ports import AgentSlotsPort


DATE_FROM = "2026-09-10T00:00:00+00:00"
DATE_TO = "2026-09-17T23:59:59+00:00"
AGENT_ID = "agent-test-001"


# --- _iso_add_minutes helper ---

def test_iso_add_minutes_z_suffix():
    result = _iso_add_minutes("2026-09-10T14:00:00Z", 30)
    expected_dt = datetime(2026, 9, 10, 14, 30, tzinfo=timezone.utc)
    assert datetime.fromisoformat(result) == expected_dt


def test_iso_add_minutes_plus_offset():
    result = _iso_add_minutes("2026-09-10T09:00:00+00:00", 30)
    expected_dt = datetime(2026, 9, 10, 9, 30, tzinfo=timezone.utc)
    assert datetime.fromisoformat(result) == expected_dt


# --- FakeAgentSlots ---

@pytest.mark.asyncio
async def test_fake_returns_slots():
    provider = FakeAgentSlots()
    result = await provider.list_agent_slots(AGENT_ID, DATE_FROM, DATE_TO)
    assert result["agent_id"] == AGENT_ID
    assert result["slot_minutes"] == FakeAgentSlots.SLOT_MINUTES
    assert len(result["slots"]) > 0
    first = result["slots"][0]
    assert "start" in first and "end" in first
    start_dt = datetime.fromisoformat(first["start"])
    end_dt = datetime.fromisoformat(first["end"])
    assert end_dt - start_dt == timedelta(minutes=FakeAgentSlots.SLOT_MINUTES)


# --- check_agent_availability tool (via fake mode, default AGENT_SLOTS_MODE) ---

@pytest.mark.asyncio
async def test_tool_returns_slots_fake_mode(monkeypatch):
    monkeypatch.setenv("AGENT_SLOTS_MODE", "fake")
    result = await check_agent_availability.ainvoke(
        {"agent_id": AGENT_ID, "date_from": DATE_FROM, "date_to": DATE_TO}
    )
    assert result["agent_id"] == AGENT_ID
    assert isinstance(result["slots"], list)
    assert len(result["slots"]) > 0
    assert result["error"] is None
    for slot in result["slots"]:
        assert "start" in slot and "end" in slot


@pytest.mark.asyncio
async def test_tool_empty_slots(monkeypatch):
    class EmptyFake(AgentSlotsPort):
        async def list_agent_slots(self, agent_id, date_from, date_to):
            return {"agent_id": agent_id, "slot_minutes": 30, "slots": []}

    monkeypatch.setattr("agent.agent_slots.get_agent_slots_provider", lambda: EmptyFake())
    result = await check_agent_availability.ainvoke(
        {"agent_id": AGENT_ID, "date_from": DATE_FROM, "date_to": DATE_TO}
    )
    assert result["slots"] == []
    assert result["error"] is None


@pytest.mark.asyncio
async def test_tool_backend_error(monkeypatch):
    class FailingFake(AgentSlotsPort):
        async def list_agent_slots(self, agent_id, date_from, date_to):
            raise RuntimeError("connection refused")

    monkeypatch.setattr("agent.agent_slots.get_agent_slots_provider", lambda: FailingFake())
    result = await check_agent_availability.ainvoke(
        {"agent_id": AGENT_ID, "date_from": DATE_FROM, "date_to": DATE_TO}
    )
    assert result["slots"] == []
    assert result["error"] is not None
    assert "connection refused" in result["error"]


# --- HttpAgentSlots response parsing (unit, no HTTP) ---

@pytest.mark.asyncio
async def test_http_provider_parses_response(monkeypatch):
    """Verifica que HttpAgentSlots deserializa correctamente el JSON del backend."""
    import httpx

    backend_payload = {
        "agent_id": AGENT_ID,
        "slot_minutes": 30,
        "slots": ["2026-09-10T14:00:00Z", "2026-09-10T14:30:00Z"],
    }

    async def mock_get(self, url, params=None, headers=None):
        class FakeResp:
            def raise_for_status(self): pass
            def json(self): return backend_payload
        return FakeResp()

    monkeypatch.setenv("BACKEND_URL", "http://localhost:8000")
    monkeypatch.setattr(httpx.AsyncClient, "get", mock_get)

    provider = HttpAgentSlots()
    result = await provider.list_agent_slots(AGENT_ID, DATE_FROM, DATE_TO)

    assert result["agent_id"] == AGENT_ID
    assert result["slot_minutes"] == 30
    assert len(result["slots"]) == 2
    assert result["slots"][0]["start"] == "2026-09-10T14:00:00Z"
    expected_end = _iso_add_minutes("2026-09-10T14:00:00Z", 30)
    assert result["slots"][0]["end"] == expected_end
