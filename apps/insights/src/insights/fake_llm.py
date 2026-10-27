"""LLM falso para insights: soporta bind_tools (el FakeLLM del bot no)."""
import json

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult


class FakeInsightsLLM(BaseChatModel):
    """Sin script: llama get_north_star una vez por turno y responde con lo que devolvió.

    Con script: lista de pasos, cada uno {"name", "args"} (tool call) o un str
    (respuesta final). El script se reproduce desde el inicio en cada turno.
    Un str se rellena con str.format_map sobre {nombre_tool: resultado_json}, p. ej.
    "{get_agent_response_times[agents][0][agent_name]}".
    """

    script: list | None = None

    @property
    def _llm_type(self) -> str:
        return "fake-insights"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        # Mensajes del turno actual: los posteriores al último HumanMessage.
        last_human = max(i for i, m in enumerate(messages) if isinstance(m, HumanMessage))
        turn = messages[last_human + 1 :]

        if self.script is not None:
            msg = self._scripted(turn)
        else:
            tool_results = [m for m in turn if isinstance(m, ToolMessage)]
            if not tool_results:
                msg = self._tool_call_message("get_north_star", {}, 0)
            else:
                msg = AIMessage(content=self._answer(str(tool_results[-1].content)))
        return ChatResult(generations=[ChatGeneration(message=msg)])

    @staticmethod
    def _tool_call_message(name: str, args: dict, step: int) -> AIMessage:
        return AIMessage(
            content="", tool_calls=[{"name": name, "args": args, "id": f"call_{step}_{name}"}]
        )

    def _scripted(self, turn: list) -> AIMessage:
        # El paso actual = cuántos AIMessage ya produjo el modelo en este turno.
        step = sum(isinstance(m, AIMessage) for m in turn)
        if step >= len(self.script):
            raise ValueError(f"FakeInsightsLLM: script agotado en el paso {step}")
        item = self.script[step]
        if isinstance(item, dict):
            return self._tool_call_message(item["name"], item.get("args", {}), step)

        results = {}
        for m in turn:
            if isinstance(m, ToolMessage):
                try:
                    results[m.name] = json.loads(str(m.content))
                except ValueError:
                    results[m.name] = str(m.content)
        return AIMessage(content=item.format_map(results))

    @staticmethod
    def _answer(tool_content: str) -> str:
        try:
            data = json.loads(tool_content)
        except ValueError:
            return tool_content  # mensaje de error de la tool, tal cual
        lines = [f"North-star metrics ({data.get('period')}):"]
        lines += [f"- {k}: {v}" for k, v in data.items() if k not in ("period", "stage_conversion")]
        return "\n".join(lines)
