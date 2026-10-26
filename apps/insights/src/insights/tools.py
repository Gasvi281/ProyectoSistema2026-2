"""Tools del agente de insights. Solo lectura; el token se toma del contextvar."""
import json
import re
import uuid
from datetime import date

import httpx
from langchain_core.tools import tool

from insights.backend import backend_get
from insights.context import sources

NO_DATA = "no data"
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_UNAVAILABLE = "The backend is unavailable right now. Tell the user to try again later."


def _normalize(value):
    """null -> "no data" y floats a 2 decimales (el modelo cita las cifras tal cual)."""
    if value is None:
        return NO_DATA
    if isinstance(value, float):
        return round(value, 2)
    if isinstance(value, dict):
        return {k: _normalize(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_normalize(v) for v in value]
    return value


async def _fetch(
    tool_name: str, path: str, params: dict | None = None, overrides: dict | None = None
) -> tuple[dict | list | None, str | None]:
    """GET al backend. Devuelve (datos, None) o (None, mensaje para el modelo)."""
    try:
        resp = await backend_get(path, params)
    except httpx.RequestError:
        return None, _UNAVAILABLE

    # Se mapea solo por status HTTP, nunca por `code`/`detail` del backend.
    status = resp.status_code
    if overrides and status in overrides:
        return None, overrides[status]
    if status == 401:
        return None, "The user's session is invalid or expired. Tell them to sign in again."
    if status == 403:
        return None, "The user is not allowed to see this data."
    if status == 404:
        return None, "This metric is not available in the backend."
    if status != 200:
        return None, _UNAVAILABLE

    # Solo tras un 200 se registra la fuente (con los params exactos enviados).
    sources.get().append(
        {"tool": tool_name, "endpoint": f"GET {path}", "params": params or {}}
    )
    return _normalize(resp.json()), None


@tool
async def get_north_star() -> str:
    """Get the agency's North Star funnel metrics over its full history (no date filter):
    lead count, median first-response hours, % of leads with follow-up, lead-to-visit
    conversion %, % lost within 48h, and stage-to-stage conversion."""
    data, error = await _fetch("get_north_star", "/analytics/north-star")
    if error:
        return error
    data["period"] = "full history (no date filter)"
    return json.dumps(data, ensure_ascii=False)


@tool
async def list_agents() -> str:
    """List the agency's active human agents (id, full_name, role). Call this first
    whenever the user refers to an agent by name, to find that agent's id."""
    params = {"include_bots": False, "active": True, "limit": 200}
    data, error = await _fetch("list_agents", "/agents", params)
    if error:
        return error
    agents = [
        {"id": a["id"], "full_name": a["full_name"], "role": a["role"]} for a in data
    ]
    return json.dumps({"period": "current active roster", "agents": agents}, ensure_ascii=False)


@tool
async def get_agent_response_times() -> str:
    """Get, per agent, how long they take to first respond to leads (average and median
    hours, leads, never_answered), slowest first. Covers the full history (no date filter)."""
    data, error = await _fetch(
        "get_agent_response_times", "/analytics/agent-response-time"
    )
    if error:
        return error
    return json.dumps(
        {"period": "full history (no date filter)", "agents": data}, ensure_ascii=False
    )


def _valid_date(value: str) -> bool:
    if not _DATE_RE.match(value):
        return False
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


@tool
async def get_funnel(
    agent_id: str | None = None,
    created_from: str | None = None,
    created_to: str | None = None,
    operation_type: str | None = None,
) -> str:
    """Get the lead funnel (stages with leads_reached, pct_from_prev, pct_of_first, plus
    lost). All filters are optional: agent_id (UUID from list_agents), created_from and
    created_to (YYYY-MM-DD, inclusive, filter by lead creation date), operation_type
    (SALE or RENT). With no filters it covers all leads ever created."""
    # Validación local: con entrada inválida no se hace ninguna request.
    if agent_id is not None:
        try:
            uuid.UUID(agent_id)
        except ValueError:
            return "Invalid agent_id: it must be a UUID returned by list_agents."
    for name, value in (("created_from", created_from), ("created_to", created_to)):
        if value is not None and not _valid_date(value):
            return f"Invalid {name}: use the format YYYY-MM-DD."
    if operation_type is not None and operation_type.upper() not in ("SALE", "RENT"):
        return "Invalid operation_type: it must be SALE or RENT."

    params = {
        k: v
        for k, v in {
            "created_from": created_from,
            "created_to": created_to,
            "agent_id": agent_id,
            "operation_type": operation_type.upper() if operation_type else None,
        }.items()
        if v is not None
    }
    data, error = await _fetch(
        "get_funnel",
        "/analytics/funnel",
        params,
        overrides={422: "Invalid date range: created_from is after created_to."},
    )
    if error:
        return error

    if created_from or created_to:
        period = (
            f"leads created {created_from or '(no start)'} to {created_to or '(no end)'}"
        )
    else:
        period = "all leads ever created"
    data["period"] = period
    return json.dumps(data, ensure_ascii=False)


TOOLS = [get_north_star, list_agents, get_agent_response_times, get_funnel]
