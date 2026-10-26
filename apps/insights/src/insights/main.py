"""API de insights (HU-18): solo lectura, para TEAM_ADMIN."""
import uuid

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from insights import config
from insights.agent import run_turn
from insights.context import auth_header, sources
from insights.gate import require_team_admin

app = FastAPI(title="Homelitics Insights")
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.cors_origins(),
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatRequest(BaseModel):
    message: str
    conversation_id: str | None = None


class Source(BaseModel):
    tool: str
    endpoint: str
    params: dict


class ChatResponse(BaseModel):
    reply: str
    conversation_id: str
    sources: list[Source]


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.post("/insights/chat", response_model=ChatResponse)
async def chat(req: ChatRequest, authorization: str = Depends(require_team_admin)):
    # Se fijan aquí (no en la dependency): los contextvars de una dependency
    # no llegan de forma fiable al endpoint.
    auth_header.set(authorization)
    sources.set([])
    conversation_id = req.conversation_id or str(uuid.uuid4())
    reply = await run_turn(req.message, conversation_id)
    return ChatResponse(reply=reply, conversation_id=conversation_id, sources=sources.get())
