"""
test_wiring.py
--------------
Verifica que handle_turn inyecta al LLM el client_id RESUELTO (no el chat_id crudo)
y que el thread_id del MemorySaver sigue siendo el chat_id (historial por canal).

Diseño: mockea _get_executor() para devolver un ejecutor falso que capture los args,
evitando dependencia de LangGraph ni Gemini real.
"""
import pytest
from agent.core_langchain import get_agent
from agent.fakes import SEED_CLIENT_ID


CHAT_ID = "telegram_12345"


class _CapturedCall:
    def __init__(self):
        self.messages = None
        self.config = None

    async def ainvoke(self, inputs, config=None):
        self.messages = inputs.get("messages", [])
        self.config = config
        # Respuesta mínima compatible con _extract_text
        return {"messages": [type("M", (), {"content": "ok"})()]}


@pytest.mark.asyncio
async def test_gemini_branch_injects_resolved_client_id(monkeypatch):
    """
    En modo gemini, el contextual_message debe contener el client_id resuelto
    (SEED_CLIENT_ID de FakeClientResolver), NO el chat_id crudo.
    """
    monkeypatch.setenv("AGENT_LLM_MODE", "gemini")
    monkeypatch.setenv("CLIENT_RESOLVER_MODE", "fake")

    agent = get_agent()
    captured = _CapturedCall()
    monkeypatch.setattr(agent, "_get_executor", lambda: captured)
    # Forzar que _executor se recalcule en el branch gemini
    agent._executor = None

    await agent.handle_turn(CHAT_ID, "test", "hola")

    assert captured.messages, "El ejecutor no recibió mensajes"
    content = captured.messages[0].content

    # El prefijo debe contener el client_id RESUELTO, no el chat_id crudo
    assert SEED_CLIENT_ID in content, (
        f"Se esperaba SEED_CLIENT_ID={SEED_CLIENT_ID!r} en el mensaje, "
        f"pero el contenido fue: {content!r}"
    )
    assert CHAT_ID not in content, (
        f"El chat_id crudo {CHAT_ID!r} no debería estar en el mensaje — "
        f"se filtró sin resolución"
    )


@pytest.mark.asyncio
async def test_gemini_branch_thread_id_is_chat_id(monkeypatch):
    """
    El thread_id del MemorySaver debe ser el chat_id crudo, no el client_id resuelto.
    Garantiza que distintos usuarios de Telegram tienen historiales separados.
    """
    monkeypatch.setenv("AGENT_LLM_MODE", "gemini")
    monkeypatch.setenv("CLIENT_RESOLVER_MODE", "fake")

    agent = get_agent()
    captured = _CapturedCall()
    monkeypatch.setattr(agent, "_get_executor", lambda: captured)
    agent._executor = None

    await agent.handle_turn(CHAT_ID, "test", "hola")

    thread_id = captured.config["configurable"]["thread_id"]
    assert thread_id == CHAT_ID, (
        f"thread_id debe ser el chat_id crudo {CHAT_ID!r}, "
        f"pero fue {thread_id!r}"
    )
    assert thread_id != SEED_CLIENT_ID, (
        "thread_id NO debe ser el client_id resuelto (colapsaría todos los hilos)"
    )


@pytest.mark.asyncio
async def test_resolve_client_called_with_chat_id(monkeypatch):
    """resolve_client se invoca con el chat_id, no con el client_id resuelto."""
    monkeypatch.setenv("AGENT_LLM_MODE", "gemini")
    monkeypatch.setenv("CLIENT_RESOLVER_MODE", "fake")

    agent = get_agent()
    captured_resolve_args = []
    original_resolve = agent.client_resolver.resolve_client

    async def spy_resolve(chat_id, **kwargs):
        captured_resolve_args.append(chat_id)
        return await original_resolve(chat_id, **kwargs)

    agent.client_resolver.resolve_client = spy_resolve

    fake_exec = _CapturedCall()
    monkeypatch.setattr(agent, "_get_executor", lambda: fake_exec)
    agent._executor = None

    await agent.handle_turn(CHAT_ID, "test", "hola")

    assert CHAT_ID in captured_resolve_args, (
        f"resolve_client debía llamarse con {CHAT_ID!r}, "
        f"pero se llamó con: {captured_resolve_args}"
    )
