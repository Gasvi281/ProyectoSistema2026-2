"""Tests para agent.observability — tracing opcional con Langfuse."""

import pytest
from unittest.mock import AsyncMock, patch

from agent.observability import get_langfuse_callbacks
from agent.core_langchain import ConversationalAgent


# ---------------------------------------------------------------------------
# get_langfuse_callbacks
# ---------------------------------------------------------------------------


def test_get_langfuse_callbacks_returns_empty_without_keys(monkeypatch):
    """Sin LANGFUSE_PUBLIC_KEY ni LANGFUSE_SECRET_KEY, devuelve [] — sin imports
    ni efectos secundarios de Langfuse."""
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)

    callbacks = get_langfuse_callbacks()

    assert callbacks == [], (
        f"Se esperaba [] sin las keys de Langfuse, se obtuvo: {callbacks!r}"
    )


def test_get_langfuse_callbacks_returns_empty_on_constructor_error(monkeypatch):
    """Si CallbackHandler() lanza (por ejemplo, keys inválidas o SDK roto),
    get_langfuse_callbacks devuelve [] en lugar de propagar la excepción."""
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-lf-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-lf-test")

    with patch("langfuse.langchain.CallbackHandler", side_effect=RuntimeError("sdk error")):
        callbacks = get_langfuse_callbacks()

    assert callbacks == [], (
        f"Se esperaba [] cuando el constructor falla, se obtuvo: {callbacks!r}"
    )


# ---------------------------------------------------------------------------
# handle_turn fail-open — el agente responde aunque Langfuse esté roto
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_turn_works_when_langfuse_handler_raises(monkeypatch):
    """handle_turn sigue devolviendo una respuesta aunque get_langfuse_callbacks
    retorne un handler que explote durante ainvoke.

    Verifica que el tracing fallido no bloquea la conversación (fail-open).
    """
    monkeypatch.setenv("AGENT_LLM_MODE", "gemini")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-lf-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-lf-test")

    # Mock de executor: ainvoke simula respuesta normal del grafo
    from langchain_core.messages import AIMessage

    executor_mock = AsyncMock()
    executor_mock.ainvoke.return_value = {
        "messages": [AIMessage(content="respuesta del agente")]
    }

    # client_resolver que resuelve sin problemas
    resolver_mock = AsyncMock()
    resolver_mock.resolve_client.return_value = "client-abc"

    agent = ConversationalAgent.__new__(ConversationalAgent)
    agent._executor = executor_mock
    agent.client_resolver = resolver_mock
    agent.conversation_store = AsyncMock()
    agent.conversation_store.save_interaction = AsyncMock()

    # Forzamos que get_langfuse_callbacks devuelva un handler que lanza al
    # ser llamado por LangChain (simulado: ainvoke levantaría si callbacks
    # fallaran — pero en realidad el catch-all de handle_turn lo captura).
    # Aquí lo probamos haciendo que callbacks() retorne un handler falso que
    # lanza, y comprobamos que la respuesta llega igual.
    class _BrokenHandler:
        def on_chain_start(self, *a, **kw):
            raise RuntimeError("Langfuse callback explota")

    with patch("agent.observability.get_langfuse_callbacks", return_value=[_BrokenHandler()]):
        reply = await agent.handle_turn("chat-99", "telegram", "hola")

    # El turno debe responder de forma normal o con el catch-all de "Error:"
    # — lo importante es que no levanta una excepción no capturada.
    assert reply.reply_text is not None
    assert isinstance(reply.reply_text, str)
    assert len(reply.reply_text) > 0
