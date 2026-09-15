"""Tests for agent tools."""
import pytest
from agent.fakes import FakeCatalog, FakeAvailability, FakeBooking
from agent.types import SearchFilters
from datetime import datetime
from langchain_core.messages import AIMessage, ToolMessage
from agent.tools_langchain import request_visit

@pytest.mark.asyncio
async def test_search_returns_results():
    """Search returns matching properties."""
    catalog = FakeCatalog()
    filters = SearchFilters(location="Laureles")
    results = await catalog.search(filters)
    assert len(results) > 0
    assert results[0].name == "Apartamento Laureles"

@pytest.mark.asyncio
async def test_search_no_hallucination_on_empty_catalog():
    """No property names when catalog is empty (grounding test)."""
    catalog = FakeCatalog()
    catalog.properties = {}  # Empty catalog
    results = await catalog.search(SearchFilters(location="Laureles"))
    assert len(results) == 0

@pytest.mark.asyncio
async def test_property_qa_retrieves_facts():
    """Property Q&A returns accurate facts."""
    catalog = FakeCatalog()
    prop = await catalog.get_property("prop_001")
    assert prop is not None
    assert prop.price == 250_000_000

@pytest.mark.asyncio
async def test_availability_lists_slots():
    """Availability lists real slots."""
    availability = FakeAvailability()
    start = datetime(2026, 8, 20)
    end = datetime(2026, 8, 27)
    slots = await availability.list_slots("prop_001", start, end)
    assert len(slots) > 0

@pytest.mark.asyncio
async def test_booking_creates_appointment():
    """Booking creates appointment in pending_confirmation status."""
    booking = FakeBooking()
    appointment = await booking.create_appointment("prop_001", "client_001", "slot_001")
    assert appointment.status == "pending_confirmation"
    assert appointment.property_id == "prop_001"

@pytest.mark.asyncio
async def test_booking_confirmation():
    """Appointment moves to confirmed status."""
    booking = FakeBooking()
    appointment = await booking.create_appointment("prop_001", "client_001", "slot_001")
    confirmed = await booking.confirm_appointment(appointment.id)
    assert confirmed.status == "confirmed"


# ---------------------------------------------------------------------------
# request_visit — honesty tests (Task A fix)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_request_visit_fake_mode_does_not_claim_human_notified(monkeypatch):
    """En modo fake, request_visit NO debe afirmar que se notificó a un agente real."""
    monkeypatch.delenv("NOTIFICATIONS_MODE", raising=False)  # asegura modo fake
    result = await request_visit.ainvoke({
        "client_id": "client_test",
        "property_description": "Apartamento en Laureles",
        "preferred_datetime": "mañana en la tarde",
    })
    # El mensaje honesto debe mencionar "prueba" o "entorno" — nunca debe decir
    # "envié" ni "agente inmobiliario" como si el aviso real se hubiera mandado.
    result_lower = result.lower()
    assert "prueba" in result_lower or "entorno" in result_lower, (
        f"En modo fake el mensaje debe aclarar que es un entorno de prueba. Got: {result!r}"
    )
    assert "envié tu solicitud de visita al agente inmobiliario" not in result_lower, (
        f"En modo fake no debe afirmar que se notificó a un agente real. Got: {result!r}"
    )


# ---------------------------------------------------------------------------
# Capa C — ToolNode con handle_tool_errors no envenena el estado
# ---------------------------------------------------------------------------

def test_tool_error_handler_formats_message():
    """_tool_error_to_message convierte una excepción en texto orientativo para el LLM.

    Verifica la Capa C de Task C: el handler usado en ToolNode(handle_tool_errors=...)
    produce un mensaje que incluye el texto del error y la instrucción de informar
    al usuario. Es una función pura — testeable sin LangGraph ni LLM.
    """
    from agent.core_langchain import _tool_error_to_message

    exc = RuntimeError("fallo simulado de red")
    msg = _tool_error_to_message(exc)

    assert "fallo simulado de red" in msg
    assert "error técnico" in msg
    assert "Informa al usuario" in msg


def test_get_executor_uses_tool_node(monkeypatch):
    """_get_executor() construye el grafo con un ToolNode (no pasa la lista raw).

    Verifica que la Capa C está realmente cableada: ToolNode se importa y se pasa
    a create_react_agent. Mockea create_react_agent para capturar el arg 'tools'
    y verificar que es una instancia de ToolNode, sin LLM ni MemorySaver real.
    """
    from langgraph.prebuilt import ToolNode
    from agent.core_langchain import ConversationalAgent

    monkeypatch.setenv("AGENT_LLM_MODE", "fake")

    captured = {}

    def fake_create_react_agent(llm, tools, **kwargs):
        captured["tools_arg"] = tools

        class _FakeGraph:
            async def ainvoke(self, *a, **kw):
                return {"messages": [type("M", (), {"content": "ok"})()]}

        return _FakeGraph()

    # La importación es local dentro de _get_executor(); parchear en el módulo origen.
    monkeypatch.setattr(
        "langgraph.prebuilt.create_react_agent",
        fake_create_react_agent,
    )

    agent = ConversationalAgent()
    # Forzar reset del executor cacheado
    agent._executor = None
    agent._get_executor()

    assert "tools_arg" in captured, "_get_executor() no llamó a create_react_agent"
    assert isinstance(captured["tools_arg"], ToolNode), (
        f"Se esperaba ToolNode como arg 'tools', se obtuvo {type(captured['tools_arg'])}"
    )


@pytest.mark.asyncio
async def test_request_visit_email_mode_confirms_send(monkeypatch):
    """En modo email con envío exitoso, el mensaje confirma que se notificó al agente."""
    monkeypatch.setenv("NOTIFICATIONS_MODE", "email")

    # Parcheamos send_manual_visit_request para que no haga red real.
    import agent.notifications as notif_mod
    async def _fake_send(appointment_id, client_id, description, dt):
        return True
    monkeypatch.setattr(notif_mod, "send_manual_visit_request", _fake_send)

    result = await request_visit.ainvoke({
        "client_id": "client_test",
        "property_description": "Casa en Envigado",
        "preferred_datetime": "este viernes",
    })
    assert "envié tu solicitud" in result.lower() or "agente inmobiliario" in result.lower(), (
        f"En modo email exitoso debe confirmar el envío. Got: {result!r}"
    )
