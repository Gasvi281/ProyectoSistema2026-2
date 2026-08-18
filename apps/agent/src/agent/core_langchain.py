"""Core agent usando LangGraph ReAct con tools."""
import os
import uuid
from datetime import datetime
from typing import Optional

from langchain_core.messages import HumanMessage, AIMessage

from agent.types import AgentReply, ClientInteraction
from agent.llm import get_langchain_llm
from agent.tools_langchain import get_tools
from agent.fakes import FakeConversationStore


class ConversationalAgent:
    """Agente ReAct usando LangGraph (LangChain 1.x)."""

    def __init__(self):
        self.llm = get_langchain_llm()
        self.tools = get_tools()
        self.conversation_store = FakeConversationStore()
        self.system_prompt = self._load_system_prompt()
        self._executor = None

    def _load_system_prompt(self) -> str:
        prompt_path = os.path.join(os.path.dirname(__file__), "..", "..", "prompts", "system.md")
        if os.path.exists(prompt_path):
            with open(prompt_path, "r", encoding="utf-8") as f:
                return f.read()
        return "Eres un asistente inmobiliario para Medellín. Ayuda a encontrar propiedades y agendar visitas."

    def _get_executor(self):
        """Crea el grafo LangGraph la primera vez (modo gemini)."""
        if self._executor is None:
            from langgraph.prebuilt import create_react_agent
            from langgraph.checkpoint.memory import MemorySaver

            self._executor = create_react_agent(
                self.llm,
                self.tools,
                prompt=self.system_prompt,
                checkpointer=MemorySaver(),
            )
        return self._executor

    @staticmethod
    def _extract_text(content) -> str:
        """Gemini 3.x devuelve content como lista de bloques."""
        if isinstance(content, list):
            return " ".join(b.get("text", "") for b in content if isinstance(b, dict))
        return str(content)

    async def handle_turn(self, client_id: str, channel: str, message: str) -> AgentReply:
        mode = os.getenv("AGENT_LLM_MODE", "fake").lower()

        try:
            if mode == "gemini":
                executor = self._get_executor()
                # thread_id mantiene el historial por cliente dentro del MemorySaver
                config = {"configurable": {"thread_id": client_id}}
                result = await executor.ainvoke(
                    {"messages": [HumanMessage(content=message)]},
                    config=config,
                )
                reply_text = self._extract_text(result["messages"][-1].content)
            else:
                # Modo fake: sin LangGraph (FakeLLM no soporta bind_tools)
                reply_text = self.llm._call(message)
        except Exception as e:
            reply_text = f"Error: {str(e)}"

        interaction = ClientInteraction(
            id=str(uuid.uuid4()),
            client_id=client_id,
            channel=channel,
            channel_user_id=client_id,
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
                "client_id": client_id,
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


async def handle_turn(client_id: str, channel: str, message: str) -> AgentReply:
    """Punto de entrada público — agnóstico al canal."""
    agent = get_agent()
    return await agent.handle_turn(client_id, channel, message)
