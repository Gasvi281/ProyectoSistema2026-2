"""LLM falso para insights: soporta bind_tools (el FakeLLM del bot no)."""
import json

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult


class FakeInsightsLLM(BaseChatModel):
    """Llama get_north_star una vez por turno y responde con lo que devolvió."""

    @property
    def _llm_type(self) -> str:
        return "fake-insights"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        # Mensajes del turno actual: los posteriores al último HumanMessage.
        last_human = max(i for i, m in enumerate(messages) if isinstance(m, HumanMessage))
        tool_results = [m for m in messages[last_human + 1 :] if isinstance(m, ToolMessage)]

        if not tool_results:
            msg = AIMessage(
                content="",
                tool_calls=[{"name": "get_north_star", "args": {}, "id": "call_north_star"}],
            )
        else:
            msg = AIMessage(content=self._answer(str(tool_results[-1].content)))
        return ChatResult(generations=[ChatGeneration(message=msg)])

    @staticmethod
    def _answer(tool_content: str) -> str:
        try:
            data = json.loads(tool_content)
        except ValueError:
            return tool_content  # mensaje de error de la tool, tal cual
        lines = [f"North-star metrics ({data.get('period')}):"]
        lines += [f"- {k}: {v}" for k, v in data.items() if k not in ("period", "stage_conversion")]
        return "\n".join(lines)
