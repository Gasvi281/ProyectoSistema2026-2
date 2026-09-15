"""Tests para core_langchain — blindaje de resolve_client en handle_turn."""

import pytest
from unittest.mock import AsyncMock

from agent.core_langchain import ConversationalAgent


@pytest.mark.asyncio
async def test_handle_turn_resolver_failure_returns_friendly_message(monkeypatch):
    """Cuando resolve_client lanza (ej. ReadTimeout de cold-start),
    handle_turn devuelve un mensaje amable en español — nunca 'Error:'.

    Cubre el hueco fuera del ToolNode: resolve_client corre en cada turno
    antes de que el LLM vea el mensaje y no está cubierto por la safety net
    de ToolNode(handle_tool_errors=...) de Bug 2 / Capa C.
    """
    monkeypatch.setenv("AGENT_LLM_MODE", "gemini")

    agent = ConversationalAgent.__new__(ConversationalAgent)
    # _get_executor() devuelve self._executor si no es None — ponemos un objeto
    # opaco para que no intente construir el grafo real (sin LLM ni MemorySaver).
    agent._executor = object()
    # Resolver que siempre falla (simula ReadTimeout u otro error de red)
    agent.client_resolver = AsyncMock()
    agent.client_resolver.resolve_client.side_effect = Exception("simulated ReadTimeout")

    reply = await agent.handle_turn("123456", "telegram", "hola")

    assert "Error:" not in reply.reply_text, (
        f"Se esperaba mensaje amable, se obtuvo: {reply.reply_text!r}"
    )
    assert len(reply.reply_text) > 0, "El reply_text no puede estar vacío"
    # El mensaje debe orientar al usuario a reintentar
    assert "intenta" in reply.reply_text.lower() or "servidor" in reply.reply_text.lower(), (
        f"El mensaje debería orientar a reintentar: {reply.reply_text!r}"
    )
