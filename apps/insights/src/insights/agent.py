"""Agente tool-calling de insights (LangGraph ReAct, mismo patrón que el bot)."""
from pathlib import Path

from langgraph.checkpoint.memory import MemorySaver
from langgraph.prebuilt import ToolNode, create_react_agent

from insights import config
from insights.fake_llm import FakeInsightsLLM
from insights.tools import TOOLS
from shared.llm import get_langchain_llm
from shared.observability import get_langfuse_callbacks

_PROMPT_PATH = Path(__file__).parent.parent.parent / "prompts" / "system.md"

_graph = None


def _tool_error_to_message(e: Exception) -> str:
    return (
        f"The tool failed with a technical error: {e}. "
        "Tell the user there was a problem and they can try again."
    )


def get_graph():
    global _graph
    if _graph is None:
        mode = config.llm_mode()
        llm = FakeInsightsLLM() if mode == "fake" else get_langchain_llm(mode=mode)
        _graph = create_react_agent(
            llm,
            ToolNode(TOOLS, handle_tool_errors=_tool_error_to_message),
            prompt=_PROMPT_PATH.read_text(encoding="utf-8"),
            checkpointer=MemorySaver(),
        )
    return _graph


def _text(content) -> str:
    if isinstance(content, list):
        return " ".join(b.get("text", "") for b in content if isinstance(b, dict))
    return str(content)


async def run_turn(message: str, conversation_id: str) -> str:
    from langchain_core.messages import HumanMessage

    run_config = {"configurable": {"thread_id": conversation_id}}
    callbacks = get_langfuse_callbacks()
    if callbacks:
        run_config["callbacks"] = callbacks
    result = await get_graph().ainvoke(
        {"messages": [HumanMessage(content=message)]}, config=run_config
    )
    return _text(result["messages"][-1].content)
