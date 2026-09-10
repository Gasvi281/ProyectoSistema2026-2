"""
leads.py
--------
Implementación de LeadPort que llama al backend real para crear/obtener un lead
(POST /leads), siguiendo el mismo patrón que booking.py.

El backend hace dedup server-side por (client_id, listing_id) vía upsert — el bot
solo llama al endpoint, sin pre-check ni lógica de dedup propia.
"""

import os

import httpx

from agent.ports import LeadPort
from agent.backend_auth import check_backend_config, get_auth_headers


class HttpLead(LeadPort):
    """Llama a POST /leads en el backend real."""

    def __init__(self):
        # Falla en construcción si falta BACKEND_URL o cualquier mecanismo de auth,
        # mismo comportamiento que HttpAppointmentBooking/HttpAgentSlots.
        check_backend_config()
        self.base_url = os.getenv("BACKEND_URL", "").rstrip("/")

    async def create_or_get_lead(
        self, client_id: str, listing_id: str, source_channel: str = "IN_APP"
    ) -> dict:
        url = f"{self.base_url}/leads"
        headers = {"Content-Type": "application/json", **get_auth_headers()}
        body = {
            "client_id": client_id,
            "listing_id": listing_id,
            "source_channel": source_channel,
        }
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, json=body, headers=headers)
            resp.raise_for_status()
            return resp.json()


def get_lead_provider() -> LeadPort:
    """
    Elige la implementación según LEAD_MODE:
    "fake" (por defecto) → FakeLead (sin HTTP, emula upsert en memoria)
    "http"               → HttpLead (llama al backend real)
    """
    mode = os.getenv("LEAD_MODE", "fake").lower()

    if mode == "fake":
        from agent.fakes import FakeLead
        return FakeLead()
    elif mode == "http":
        return HttpLead()
    else:
        raise ValueError(f"LEAD_MODE inválido: {mode!r}")
