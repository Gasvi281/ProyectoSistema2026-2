"""API de insights (HU-18): solo lectura, para TEAM_ADMIN."""
import logging
import uuid
from contextlib import asynccontextmanager

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from langchain_core.exceptions import ModelError
from pydantic import BaseModel

from insights import config
from insights.agent import run_turn
from insights.context import auth_header, sources
from insights.gate import require_team_admin
from shared.observability import flush_traces, trace_span


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    # Vaciar trazas pendientes de Langfuse al apagar (no por request: un flush
    # por request bloquearía la respuesta). No-op si el tracing está deshabilitado.
    flush_traces()


logger = logging.getLogger("uvicorn.error")

app = FastAPI(title="Homelitics Insights", lifespan=lifespan)


@app.middleware("http")
async def trace_chat(request: Request, call_next):
    # Un trace por chat: el span raíz envuelve el gate y el run de LangGraph.
    # Match exacto: /health, /docs y los preflight OPTIONS no abren span.
    if request.method == "POST" and request.url.path == "/insights/chat":
        with trace_span("insights.chat"):
            return await call_next(request)
    return await call_next(request)
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
    try:
        reply = await run_turn(req.message, conversation_id)
    except (ModelError, httpx.TimeoutException) as e:
        # Fallo del proveedor LLM (429/503/504, timeout...): 502 como el gate.
        logger.warning("LLM failure: %s", type(e).__name__)
        raise HTTPException(status_code=502, detail="Backend unavailable")
    return ChatResponse(reply=reply, conversation_id=conversation_id, sources=sources.get())
