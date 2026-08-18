"""Core agent orchestration."""
import os
import uuid
from datetime import datetime
from agent.types import AgentReply, ClientInteraction
from agent.llm import get_llm_provider
from agent.fakes import FakeCatalog, FakeAvailability, FakeBooking, FakeNotifications, FakeConversationStore

class ConversationalAgent:
    def __init__(self):
        self.catalog = FakeCatalog()
        self.availability = FakeAvailability()
        self.booking = FakeBooking()
        self.notifications = FakeNotifications()
        self.conversation_store = FakeConversationStore()
        self.llm = get_llm_provider()
        self.system_prompt = self._load_system_prompt()
        self.conversation_history = {}
    
    def _load_system_prompt(self) -> str:
        prompt_path = os.path.join(os.path.dirname(__file__), "..", "..", "prompts", "system.md")
        if os.path.exists(prompt_path):
            with open(prompt_path, "r", encoding="utf-8") as f:
                return f.read()
        return "You are a helpful real estate assistant for a Medellín property marketplace."
    
    async def handle_turn(self, client_id: str, channel: str, message: str) -> AgentReply:
        if client_id not in self.conversation_history:
            self.conversation_history[client_id] = []
        
        self.conversation_history[client_id].append({"role": "user", "content": message})
        
        messages = [{"role": "system", "content": self.system_prompt}]
        messages.extend(self.conversation_history[client_id])
        
        try:
            reply_text = await self.llm.invoke(messages)
        except Exception as e:
            reply_text = f"Sorry, I encountered an error: {str(e)}"
        
        self.conversation_history[client_id].append({"role": "assistant", "content": reply_text})
        
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
        except:
            pass
        
        return AgentReply(
            reply_text=reply_text,
            metadata={"client_id": client_id, "channel": channel, "timestamp": interaction.timestamp.isoformat()},
        )

_agent = None

def get_agent() -> ConversationalAgent:
    global _agent
    if _agent is None:
        _agent = ConversationalAgent()
    return _agent

async def handle_turn(client_id: str, channel: str, message: str) -> AgentReply:
    """Public entry point for the integration seam."""
    agent = get_agent()
    return await agent.handle_turn(client_id, channel, message)
