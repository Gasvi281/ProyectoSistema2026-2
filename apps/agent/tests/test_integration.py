"""End-to-end integration tests."""
import pytest
from agent.core_langchain import get_agent

@pytest.mark.asyncio
async def test_handle_turn_basic():
    """Basic conversation through handle_turn()."""
    agent = get_agent()
    reply = await agent.handle_turn("test_001", "console", "I'm looking for a 2-bedroom apartment in Laureles")
    assert reply.reply_text is not None
    assert len(reply.reply_text) > 0

@pytest.mark.asyncio
async def test_handle_turn_history_per_client():
    """Each client maintains separate history."""
    agent = get_agent()
    await agent.handle_turn("client_A", "console", "Message A")
    await agent.handle_turn("client_B", "console", "Message B")
    
    history_a = agent.conversation_history.get("client_A", [])
    history_b = agent.conversation_history.get("client_B", [])
    assert history_a != history_b

@pytest.mark.asyncio
async def test_agent_reply_structure():
    """AgentReply has expected structure."""
    agent = get_agent()
    reply = await agent.handle_turn("test_002", "console", "Hi")
    assert hasattr(reply, "reply_text")
    assert hasattr(reply, "matched_properties")
    assert hasattr(reply, "proposed_appointment")
    assert hasattr(reply, "metadata")
