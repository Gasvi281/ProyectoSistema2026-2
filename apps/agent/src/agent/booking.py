"""
booking.py
----------
Implementación de AppointmentBookingPort que llama al backend real para crear
una cita de visita (POST /leads/{lead_id}/appointments).

Mismo patrón que agent_slots.py: implementación HTTP real (HttpAppointmentBooking)
más factory get_appointment_booking_provider() seleccionada por APPOINTMENT_BOOKING_MODE.
"""

import os

import httpx

from agent.ports import AppointmentBookingPort
from agent.backend_auth import check_backend_config, get_auth_headers


class HttpAppointmentBooking(AppointmentBookingPort):
    """Llama a POST /leads/{lead_id}/appointments en el backend real."""

    def __init__(self):
        # Falla en construcción si falta BACKEND_URL o cualquier mecanismo de auth
        # (BACKEND_SERVICE_TOKEN para JWT o DEV_AGENT_ID para bypass de dev).
        check_backend_config()
        self.base_url = os.getenv("BACKEND_URL", "").rstrip("/")

    async def book(self, lead_id: str, scheduled_at: str, duration_min: int) -> dict:
        url = f"{self.base_url}/leads/{lead_id}/appointments"
        headers = {"Content-Type": "application/json", **get_auth_headers()}

        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                url,
                json={"scheduled_at": scheduled_at, "duration_min": duration_min},
                headers=headers,
            )
            resp.raise_for_status()
            return resp.json()


def get_appointment_booking_provider() -> AppointmentBookingPort:
    """
    Elige la implementación según APPOINTMENT_BOOKING_MODE:
    "fake" (por defecto) → FakeAppointmentBooking (sin HTTP, útil para dev y tests)
    "http"               → HttpAppointmentBooking (llama al backend real)
    """
    mode = os.getenv("APPOINTMENT_BOOKING_MODE", "fake").lower()

    if mode == "fake":
        from agent.fakes import FakeAppointmentBooking
        return FakeAppointmentBooking()
    elif mode == "http":
        return HttpAppointmentBooking()
    else:
        raise ValueError(f"APPOINTMENT_BOOKING_MODE inválido: {mode!r}")
