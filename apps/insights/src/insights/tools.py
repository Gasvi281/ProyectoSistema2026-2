"""Tools del agente de insights. Solo lectura; el token se toma del contextvar."""
import json

import httpx
from langchain_core.tools import tool

from insights.backend import backend_get
from insights.context import sources

NO_DATA = "no data"


def _nulls_to_no_data(value):
    if value is None:
        return NO_DATA
    if isinstance(value, dict):
        return {k: _nulls_to_no_data(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_nulls_to_no_data(v) for v in value]
    return value


@tool
async def get_north_star() -> str:
    """Get the agency's North Star funnel metrics over its full history (no date filter):
    lead count, median first-response hours, % of leads with follow-up, lead-to-visit
    conversion %, % lost within 48h, and stage-to-stage conversion."""
    path = "/analytics/north-star"
    try:
        resp = await backend_get(path)
    except httpx.RequestError:
        return "The backend is unavailable right now. Tell the user to try again later."

    # Se mapea solo por status HTTP, nunca por `code`/`detail` del backend.
    status = resp.status_code
    if status == 401:
        return "The user's session is invalid or expired. Tell them to sign in again."
    if status == 403:
        return "The user is not allowed to see this data."
    if status == 404:
        return "This metric is not available in the backend."
    if status != 200:
        return "The backend is unavailable right now. Tell the user to try again later."

    # Solo tras un 200 se registra la fuente.
    sources.get().append({"tool": "get_north_star", "endpoint": f"GET {path}", "params": {}})
    data = _nulls_to_no_data(resp.json())
    data["period"] = "full history (no date filter)"
    return json.dumps(data, ensure_ascii=False)


TOOLS = [get_north_star]
