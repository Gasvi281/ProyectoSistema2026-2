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


class HttpAppointmentBooking(AppointmentBookingPort):
    """Llama a POST /leads/{lead_id}/appointments en el backend real."""

    def __init__(self):
        self.base_url = os.getenv("BACKEND_URL", "").rstrip("/")
        # Auth pendiente: JWT de servicio. Si no está seteado no se envía header.
        self.service_token = os.getenv("BACKEND_SERVICE_TOKEN")

    async def book(self, lead_id: str, scheduled_at: str, duration_min: int) -> dict:
        url = f"{self.base_url}/leads/{lead_id}/appointments"
        headers = {"Content-Type": "application/json"}
        if self.service_token:
            headers["Authorization"] = f"Bearer {self.service_token}"

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
