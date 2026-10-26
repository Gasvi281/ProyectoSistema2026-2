"""Tools del agente de insights. Solo lectura; el token se toma del contextvar."""
import json
import re
import unicodedata
import uuid
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from zoneinfo import ZoneInfo

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


_OPEN_STAGES = ("INTERESTED", "VISIT_SCHEDULED", "VISITED", "NEGOTIATING")
_ROW_CAP = 10
_BOARD_LIMIT = 200
# created_from/created_to del backend son días en la zona de la agencia.
_AGENCY_TZ = ZoneInfo("America/Bogota")


def _format_cop(price) -> str:
    """"1372892.26" -> "$1.372.892" (pesos enteros, punto de miles)."""
    try:
        pesos = Decimal(str(price)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError):
        return NO_DATA
    return "$" + f"{pesos:,}".replace(",", ".")


def _created_on(created_at: str) -> str:
    moment = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    return moment.astimezone(_AGENCY_TZ).date().isoformat()


@tool
async def list_leads(
    agent_id: str | None = None,
    stage: str | None = None,
    created_from: str | None = None,
    created_to: str | None = None,
) -> str:
    """List the agency's OPEN leads (WON and LOST excluded): client name, neighborhood,
    operation type, asking price, stage and creation date, oldest created first. Use it
    for questions about current/open leads of the agency or of one agent. Optional
    filters: agent_id (UUID from list_agents), stage (INTERESTED, VISIT_SCHEDULED,
    VISITED or NEGOTIATING), created_from and created_to (YYYY-MM-DD, inclusive).
    Returns at most 10 rows, plus total_count and by_stage counts over all open leads
    that matched."""
    # Validación local: con entrada inválida no se hace ninguna request.
    if agent_id is not None:
        try:
            uuid.UUID(agent_id)
        except ValueError:
            return "Invalid agent_id: it must be a UUID returned by list_agents."
    for name, value in (("created_from", created_from), ("created_to", created_to)):
        if value is not None and not _valid_date(value):
            return f"Invalid {name}: use the format YYYY-MM-DD."
    if stage is not None and stage.upper() not in _OPEN_STAGES:
        return "Invalid stage: only open stages are listed (" + ", ".join(_OPEN_STAGES) + ")."

    params = {"active": True, "limit": _BOARD_LIMIT, "offset": 0}
    params.update(
        (k, v)
        for k, v in {
            "agent_id": agent_id,
            "stage": stage.upper() if stage else None,
            "created_from": created_from,
            "created_to": created_to,
        }.items()
        if v is not None
    )
    cards, error = await _fetch(
        "list_leads",
        "/leads",
        params,
        overrides={422: "Invalid date range: created_from is after created_to."},
    )
    if error:
        return error

    names = None
    if agent_id is None:
        # Sin active=True: los leads de agentes desactivados también llevan nombre.
        agents, agents_error = await _fetch(
            "list_leads", "/agents", {"include_bots": False, "limit": 200}
        )
        names = {} if agents_error else {a["id"]: a["full_name"] for a in agents}

    # Conteos y orden se calculan en código sobre todos los leads, antes del tope.
    # Siempre las cuatro etapas abiertas, con 0 donde no hubo leads.
    by_stage = {s: sum(1 for c in cards if c["current_stage"] == s) for s in _OPEN_STAGES}
    ordered = sorted(cards, key=lambda c: c["created_at"])[:_ROW_CAP]
    rows = []
    for c in ordered:
        row = {
            "client_name": c.get("client_name"),
            "neighborhood": c.get("neighborhood"),
            "operation_type": c.get("operation_type"),
            "asking_price": _format_cop(c.get("asking_price")),
            "stage": c["current_stage"],
            "created_on": _created_on(c["created_at"]),
        }
        if names is not None:
            row["agent_name"] = names.get(c["agent_id"])
        rows.append(row)

    if created_from or created_to:
        period = (
            f"open leads created {created_from or '(no start)'} to {created_to or '(no end)'}"
        )
    else:
        period = "all open leads"
    data = {
        "period": period,
        "order": "oldest created first",
        "total_count": len(cards),
        "shown_count": len(rows),
        "by_stage": by_stage,
        "leads": rows,
    }
    if len(cards) == _BOARD_LIMIT:
        data["total_is_lower_bound"] = True
    return json.dumps(_normalize(data), ensure_ascii=False)


_MAX_DAYS = 730


@tool
async def get_lost_reasons(days: int = _MAX_DAYS) -> str:
    """Get why leads were lost: lost leads grouped by recorded reason (reason, leads, pct),
    most common first. The window counts back from TODAY by loss date: days=30 for "last
    month", 90 for "last quarter", 730 (default, the maximum) for everything on record.
    The seeded data ends on 2026-08-31, so short windows can come back empty."""
    # Validación local: con entrada inválida no se hace ninguna request.
    if isinstance(days, bool) or not isinstance(days, int) or not 1 <= days <= _MAX_DAYS:
        return f"Invalid days: it must be an integer between 1 and {_MAX_DAYS}."

    data, error = await _fetch(
        "get_lost_reasons",
        "/analytics/lost-reasons",
        {"days": days},
        overrides={422: f"Invalid days: it must be an integer between 1 and {_MAX_DAYS}."},
    )
    if error:
        return error

    if days == _MAX_DAYS:
        period = f"all lost leads on record (last {_MAX_DAYS} days)"
    else:
        period = f"leads lost in the last {days} days, counted back from today"
    return json.dumps(
        {
            "period": period,
            "order": "most lost leads first",
            "total_lost_with_reason": sum(r["leads"] for r in data),
            "reasons": data,
        },
        ensure_ascii=False,
    )


_PERF_LIMIT = 500
_SORT_FIELDS = ("views", "leads", "visits", "won")
_PERF_PERIOD = "all time (no date filter), all listings including paused and closed"


def _pct(n: int, of: int) -> float | None:
    """% de `n` sobre `of` a 2 decimales, half-up como el backend; None si `of` es 0."""
    if not of:
        return None
    return float((Decimal(100 * n) / of).quantize(Decimal("0.01"), ROUND_HALF_UP))


def _fold(text: str) -> str:
    """Minúsculas y sin tildes, para comparar nombres de barrio."""
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c)).casefold()


def _rates(views: int, leads: int, visits: int, won: int) -> dict:
    return {
        "views": views,
        "leads": leads,
        "visits": visits,
        "won": won,
        "visit_pct": _pct(visits, leads),
        "won_pct": _pct(won, leads),
    }


async def _listing_performance(tool_name: str) -> tuple[list | None, str | None]:
    """Una sola request a listing-performance (sin offset: el orden del backend no es estable)."""
    return await _fetch(
        tool_name, "/analytics/listing-performance", {"limit": _PERF_LIMIT}
    )


@tool
async def get_listing_performance(
    operation_type: str | None = None,
    neighborhood: str | None = None,
    sort_by: str = "views",
) -> str:
    """Get per-listing demand figures: views, leads, visits (leads that reached a visit)
    and won (leads won), with visit_pct and won_pct of leads computed for you. Covers
    all time and ALL listings, including paused and closed ones. Optional filters:
    operation_type (SALE or RENT) and neighborhood (name, any case or accents). sort_by
    is views (default), leads, visits or won; highest first. Returns at most 10 listings
    plus totals over every listing that matched."""
    # Validación local: con entrada inválida no se hace ninguna request.
    if operation_type is not None and operation_type.upper() not in ("SALE", "RENT"):
        return "Invalid operation_type: it must be SALE or RENT."
    if neighborhood is not None and not neighborhood.strip():
        return "Invalid neighborhood: it must be a non-empty name."
    if sort_by.lower() not in _SORT_FIELDS:
        return "Invalid sort_by: it must be one of " + ", ".join(_SORT_FIELDS) + "."
    sort_by = sort_by.lower()

    raw, error = await _listing_performance("get_listing_performance")
    if error:
        return error

    rows = raw
    if operation_type:
        rows = [r for r in rows if r["operation_type"] == operation_type.upper()]
    if neighborhood:
        wanted = _fold(neighborhood.strip())
        rows = [r for r in rows if _fold(r["neighborhood"]) == wanted]

    # Orden, tope y totales se calculan en código, sobre todos los inmuebles filtrados.
    ordered = sorted(rows, key=lambda r: (-r[sort_by], r["listing_id"]))[:_ROW_CAP]
    data = {
        "period": _PERF_PERIOD,
        "order": f"most {sort_by} first",
        "total_count": len(rows),
        "shown_count": len(ordered),
        "totals": _rates(*(sum(r[f] for r in rows) for f in _SORT_FIELDS)),
        "listings": [
            {
                "neighborhood": r["neighborhood"],
                "city": r["city"],
                "property_type": r["property_type"],
                "operation_type": r["operation_type"],
                "asking_price": _format_cop(r["asking_price"]),
                **_rates(*(r[f] for f in _SORT_FIELDS)),
            }
            for r in ordered
        ],
    }
    if len(raw) == _PERF_LIMIT:
        data["total_is_lower_bound"] = True
    return json.dumps(_normalize(data), ensure_ascii=False)


TOOLS = [
    get_north_star,
    list_agents,
    get_agent_response_times,
    get_funnel,
    list_leads,
    get_lost_reasons,
    get_listing_performance,
]
