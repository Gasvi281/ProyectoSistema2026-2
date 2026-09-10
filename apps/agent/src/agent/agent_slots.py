"""
agent_slots.py
--------------
Implementación de AgentSlotsPort que llama al backend real para obtener
los slots disponibles de un agente inmobiliario.

Mismo patrón que notifications.py: implementación HTTP real (HttpAgentSlots)
más factory get_agent_slots_provider() seleccionada por AGENT_SLOTS_MODE.
"""

import os
from datetime import datetime, timedelta, timezone

import httpx

from agent.ports import AgentSlotsPort
from agent.backend_auth import check_backend_config, get_auth_headers


def _iso_add_minutes(start_iso: str, minutes: int) -> str:
    # Python 3.10 fromisoformat no acepta 'Z' como sufijo de zona horaria.
    normalized = start_iso.replace("Z", "+00:00")
    dt = datetime.fromisoformat(normalized)
    return (dt + timedelta(minutes=minutes)).isoformat()


class HttpAgentSlots(AgentSlotsPort):
    """Consulta GET /agents/{agent_id}/slots en el backend real."""

    def __init__(self):
        # Falla en construcción si falta BACKEND_URL o cualquier mecanismo de auth
        # (BACKEND_SERVICE_TOKEN para JWT o DEV_AGENT_ID para bypass de dev).
        # Así no se hacen peticiones sin autenticar de forma silenciosa.
        check_backend_config()
        self.base_url = os.getenv("BACKEND_URL", "").rstrip("/")

    async def list_agent_slots(self, agent_id: str, date_from: str, date_to: str) -> dict:
        url = f"{self.base_url}/agents/{agent_id}/slots"
        headers = get_auth_headers()

        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                url,
                params={"from": date_from, "to": date_to},
                headers=headers,
            )
            resp.raise_for_status()
            data = resp.json()

        slot_minutes = data.get("slot_minutes", 30)
        raw_slots = data.get("slots", [])
        slots = [
            {"start": s, "end": _iso_add_minutes(s, slot_minutes)}
            for s in raw_slots
        ]
        return {
            "agent_id": data.get("agent_id", agent_id),
            "slot_minutes": slot_minutes,
            "slots": slots,
        }


def get_agent_slots_provider() -> AgentSlotsPort:
    """
    Elige la implementación según AGENT_SLOTS_MODE:
    "fake" (por defecto) → FakeAgentSlots (sin HTTP, útil para pruebas y dev)
    "http"               → HttpAgentSlots (llama al backend real)
    """
    mode = os.getenv("AGENT_SLOTS_MODE", "fake").lower()

    if mode == "fake":
        from agent.fakes import FakeAgentSlots
        return FakeAgentSlots()
    elif mode == "http":
        return HttpAgentSlots()
    else:
        raise ValueError(f"AGENT_SLOTS_MODE inválido: {mode!r}")
