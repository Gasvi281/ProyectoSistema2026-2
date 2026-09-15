"""Core agent usando LangGraph ReAct con tools."""
import os
import json
import logging
import uuid
from datetime import datetime
from typing import Optional

from langchain_core.messages import HumanMessage, AIMessage, ToolMessage

from agent.types import AgentReply, ClientInteraction
from agent.llm import get_langchain_llm
from agent.tools_langchain import get_tools
from agent.fakes import FakeConversationStore
from agent.client_resolver import get_client_resolver_provider

logger = logging.getLogger("agent.steps")


def _log_steps(messages: list) -> None:
    """Imprime cada paso intermedio del ciclo ReAct cuando AGENT_DEBUG=true.

    Muestra AIMessage con tool_calls (decisión de invocar una herramienta),
    ToolMessage (resultado devuelto por la herramienta) y AIMessage sin
    tool_calls que no sea el último mensaje (razonamientos intermedios).
    El primer HumanMessage y la respuesta final se omiten — ya los ve el caller.
    """
    if os.getenv("AGENT_DEBUG", "").lower() not in ("1", "true", "yes"):
        return

    # Saltamos el primer HumanMessage y el último AIMessage (respuesta final).
    steps = messages[1:-1]
    if not steps:
        return

    sep = "─" * 60
    logger.debug("\n%s  AGENT STEPS  %s", sep, sep)

    for i, msg in enumerate(steps, start=1):
        kind = type(msg).__name__

        if isinstance(msg, AIMessage) and msg.tool_calls:
            for tc in msg.tool_calls:
                try:
                    args_str = json.dumps(tc.get("args", {}), ensure_ascii=False, indent=2)
                except Exception:
                    args_str = str(tc.get("args", {}))
                logger.debug(
                    "[paso %d] TOOL CALL → %s\n%s", i, tc.get("name", "?"), args_str
                )

        elif isinstance(msg, ToolMessage):
            content = msg.content
            if isinstance(content, (dict, list)):
                try:
                    content = json.dumps(content, ensure_ascii=False, indent=2)
                except Exception:
                    content = str(content)
            logger.debug("[paso %d] TOOL RESULT (%s)\n%s", i, msg.name, content)

        elif isinstance(msg, AIMessage):
            text = _extract_text_static(msg.content)
            if text.strip():
                logger.debug("[paso %d] RAZONAMIENTO INTERMEDIO\n%s", i, text)

    logger.debug("%s  FIN STEPS  %s\n", sep, sep)


def _extract_text_static(content) -> str:
    if isinstance(content, list):
        return " ".join(b.get("text", "") for b in content if isinstance(b, dict))
    return str(content)


def _tool_error_to_message(e: Exception) -> str:
    """Convierte una excepción escapada de un tool en un mensaje de texto para el LLM.

    Usado como handler en ToolNode para garantizar que ninguna excepción
    inesperada de un tool deje el thread de MemorySaver en estado inconsistente
    (AIMessage con tool_calls sin ToolMessage que lo resuelva).
    """
    return (
        f"La herramienta falló con un error técnico: {e}. "
        "Informa al usuario que hubo un problema y que puede intentar de nuevo."
    )


class ConversationalAgent:
    """Agente ReAct usando LangGraph (LangChain 1.x)."""

    def __init__(self):
        self.llm = get_langchain_llm()
        self.tools = get_tools()
        self.conversation_store = FakeConversationStore()
        self.system_prompt = self._load_system_prompt()
        self._executor = None
        # Una sola instancia por singleton de agente: la memoización interna del
        # resolver persiste entre turnos del mismo proceso.
        self.client_resolver = get_client_resolver_provider()

    def _load_system_prompt(self) -> str:
        prompt_path = os.path.join(os.path.dirname(__file__), "..", "..", "prompts", "system.md")
        if os.path.exists(prompt_path):
            with open(prompt_path, "r", encoding="utf-8") as f:
                return f.read()
        return "Eres un asistente inmobiliario para Medellín. Ayuda a encontrar propiedades y agendar visitas."

    def _get_executor(self):
        """Crea el grafo LangGraph la primera vez (modo gemini).

        Usamos un ToolNode explícito con handle_tool_errors para garantizar que
        ningún tool que lance una excepción inesperada deje el thread_id de
        MemorySaver en estado inconsistente (AIMessage con tool_calls sin
        ToolMessage de respuesta). Con este handler cualquier excepción no
        capturada dentro de un tool se convierte en un ToolMessage de error, el
        LLM recibe ese mensaje y puede responder al usuario con gracia.
        """
        if self._executor is None:
            from langgraph.prebuilt import create_react_agent, ToolNode
            from langgraph.checkpoint.memory import MemorySaver

            tool_node = ToolNode(self.tools, handle_tool_errors=_tool_error_to_message)
            self._executor = create_react_agent(
                self.llm,
                tool_node,
                prompt=self.system_prompt,
                checkpointer=MemorySaver(),
            )
        return self._executor

    async def handle_turn(self, chat_id: str, channel: str, message: str) -> AgentReply:
        mode = os.getenv("AGENT_LLM_MODE", "fake").lower()

        try:
            if mode == "gemini":
                executor = self._get_executor()
                # thread_id por usuario de canal (chat_id crudo): mantiene el
                # historial separado por persona en el MemorySaver.
                config = {"configurable": {"thread_id": chat_id}}
                # Resolver el client_id real de backend (distinto del chat_id)
                # para que tools como create_or_get_lead reciban el id correcto.
                # FakeClientResolver es determinista y nunca lanza; HttpClientResolver
                # puede fallar por cold-start (ReadTimeout) — en ese caso devolvemos
                # un mensaje amable en vez de propagar al catch-all de "Error: ".
                try:
                    client_id = await self.client_resolver.resolve_client(chat_id)
                except Exception:
                    reply_text = (
                        "Hubo un problema conectando con el servidor, "
                        "intenta de nuevo en un momento."
                    )
                    return AgentReply(
                        reply_text=reply_text,
                        metadata={
                            "chat_id": chat_id,
                            "channel": channel,
                            "timestamp": datetime.now().isoformat(),
                        },
                    )
                contextual_message = (
                    f"[client_id de esta conversación: {client_id}] {message}"
                )
                result = await executor.ainvoke(
                    {"messages": [HumanMessage(content=contextual_message)]},
                    config=config,
                )
                _log_steps(result["messages"])
                reply_text = _extract_text_static(result["messages"][-1].content)
            else:
                # Modo fake: sin LangGraph (FakeLLM no soporta bind_tools).
                # No se resuelve client_id — no hay tools que lo consuman aquí.
                reply_text = self.llm._call(message)
        except Exception as e:
            reply_text = f"Error: {str(e)}"

        interaction = ClientInteraction(
            id=str(uuid.uuid4()),
            client_id=chat_id,
            channel=channel,
            channel_user_id=chat_id,
            message=message,
            reply=reply_text,
            timestamp=datetime.now(),
        )

        try:
            await self.conversation_store.save_interaction(interaction)
        except Exception:
            pass

        return AgentReply(
            reply_text=reply_text,
            metadata={
                "chat_id": chat_id,
                "channel": channel,
                "timestamp": interaction.timestamp.isoformat(),
            },
        )


_agent: Optional[ConversationalAgent] = None


def get_agent() -> ConversationalAgent:
    global _agent
    if _agent is None:
        _agent = ConversationalAgent()
    return _agent


async def handle_turn(chat_id: str, channel: str, message: str) -> AgentReply:
    """Punto de entrada público — agnóstico al canal."""
    agent = get_agent()
    return await agent.handle_turn(chat_id, channel, message)
