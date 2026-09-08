"""
notifications.py
-----------------
Implementación de NotificationsPort que envía un correo real al agente
inmobiliario humano cuando se agenda una cita, usando SMTP.

Usa aiosmtplib (versión asíncrona de smtplib) para no bloquear el event
loop del servidor mientras se conecta al servidor de correo y envía el
mensaje — igual que el resto del proyecto usa httpx en vez de requests.

Convive con FakeNotifications (agent/fakes/__init__.py): cuál de las dos
se usa se decide por variable de entorno, mismo patrón que AGENT_LLM_MODE
en llm.py.
"""

import os
from email.message import EmailMessage

import aiosmtplib

from agent.ports import NotificationsPort
from agent.fakes import FakeCatalog, FakeAvailability


class EmailNotifications(NotificationsPort):
    """Notifica al agente inmobiliario por correo cuando se agenda una cita."""

    def __init__(self):
        self.smtp_host = os.getenv("SMTP_HOST")
        self.smtp_port = int(os.getenv("SMTP_PORT", "587"))
        self.smtp_user = os.getenv("SMTP_USER")
        self.smtp_password = os.getenv("SMTP_PASSWORD")
        self.smtp_from = os.getenv("SMTP_FROM", self.smtp_user)
        self.smtp_use_tls = os.getenv("SMTP_USE_TLS", "true").lower() == "true"
        self.agent_email = os.getenv("AGENT_NOTIFICATION_EMAIL")

        missing = [
            name
            for name, value in [
                ("SMTP_HOST", self.smtp_host),
                ("SMTP_USER", self.smtp_user),
                ("SMTP_PASSWORD", self.smtp_password),
                ("AGENT_NOTIFICATION_EMAIL", self.agent_email),
            ]
            if not value
        ]
        if missing:
            raise ValueError(
                f"Faltan variables de entorno para el correo: {', '.join(missing)}"
            )

    async def notify_agent_appointment(
        self, appointment_id: str, property_id: str, client_id: str
    ) -> bool:
        # Se arma el contenido del correo con datos reales de la propiedad
        # y del horario, no solo los IDs crudos — así el agente humano no
        # tiene que ir a buscar el resto del contexto a mano.
        catalog = FakeCatalog()
        availability = FakeAvailability()

        prop = await catalog.get_property(property_id)
        prop_desc = (
            f"{prop.name} ({prop.location}) — ${prop.price:,} COP"
            if prop
            else property_id
        )

        # Buscamos el slot agendado para mostrar la fecha/hora en el correo
        slot = next(
            (
                s
                for s in availability.slots.values()
                if s.property_id == property_id
            ),
            None,
        )
        when_desc = slot.start_time.strftime("%a %d %b, %H:%M") if slot else "N/A"

        message = EmailMessage()
        message["From"] = self.smtp_from
        message["To"] = self.agent_email
        message["Subject"] = f"Nueva cita agendada — {prop_desc}"
        message.set_content(
            "Se agendó una nueva visita a través del asistente de IA.\n\n"
            f"Propiedad: {prop_desc}\n"
            f"Horario: {when_desc}\n"
            f"ID de la cita: {appointment_id}\n"
            f"Cliente (chat_id): {client_id}\n\n"
            "Ingresa al panel para confirmar la cita."
        )

        try:
            await aiosmtplib.send(
                message,
                hostname=self.smtp_host,
                port=self.smtp_port,
                username=self.smtp_user,
                password=self.smtp_password,
                start_tls=self.smtp_use_tls,
            )
            return True
        except Exception as e:
            print(f"[notifications] Error enviando correo: {e}")
            return False

    async def notify_manual_visit_request(
        self,
        appointment_id: str,
        client_id: str,
        property_description: str,
        preferred_datetime: str,
    ) -> bool:
        """
        Igual que notify_agent_appointment, pero pensada para mientras el
        catálogo/disponibilidad reales no están conectados: arma el correo
        directo con lo que el cliente escribió en el chat, sin buscar nada
        en FakeCatalog/FakeAvailability (no depende de que exista un
        property_id o slot_id válido).
        """
        message = EmailMessage()
        message["From"] = self.smtp_from
        message["To"] = self.agent_email
        message["Subject"] = f"Nueva solicitud de visita — {property_description[:60]}"
        message.set_content(
            "Un cliente solicitó una visita a través del asistente de IA.\n\n"
            f"Inmueble (descrito por el cliente): {property_description}\n"
            f"Horario preferido: {preferred_datetime}\n"
            f"ID de referencia: {appointment_id}\n"
            f"Cliente (chat_id): {client_id}\n\n"
            "Esta solicitud todavía no está validada contra el catálogo real "
            "(en desarrollo) — contacta al cliente para confirmar disponibilidad."
        )

        try:
            await aiosmtplib.send(
                message,
                hostname=self.smtp_host,
                port=self.smtp_port,
                username=self.smtp_user,
                password=self.smtp_password,
                start_tls=self.smtp_use_tls,
            )
            return True
        except Exception as e:
            print(f"[notifications] Error enviando correo (solicitud manual): {e}")
            return False


def get_notifications_provider() -> NotificationsPort:
    """
    Elige la implementación de notificaciones según NOTIFICATIONS_MODE:
    "fake" (por defecto, no manda correos reales — útil para pruebas
    automatizadas y para no spamear mientras desarrollan) o "email"
    (manda correos reales por SMTP).
    """
    mode = os.getenv("NOTIFICATIONS_MODE", "fake").lower()

    if mode == "fake":
        from agent.fakes import FakeNotifications

        return FakeNotifications()
    elif mode == "email":
        return EmailNotifications()
    else:
        raise ValueError(f"NOTIFICATIONS_MODE inválido: {mode}")


async def send_manual_visit_request(
    appointment_id: str,
    client_id: str,
    property_description: str,
    preferred_datetime: str,
) -> bool:
    """
    Punto de entrada usado por la herramienta request_visit del agente.
    No pasa por get_notifications_provider()/FakeNotifications a propósito
    — así no hace falta tocar agent/fakes/__init__.py para esta función
    temporal. En modo "fake" solo imprime y simula éxito; en modo "email"
    manda el correo real usando EmailNotifications.
    """
    mode = os.getenv("NOTIFICATIONS_MODE", "fake").lower()

    if mode != "email":
        print(
            f"[notifications] (modo fake) Solicitud de visita simulada — "
            f"inmueble: {property_description!r}, horario: {preferred_datetime!r}, "
            f"cliente: {client_id}"
        )
        return True

    notifications = EmailNotifications()
    return await notifications.notify_manual_visit_request(
        appointment_id, client_id, property_description, preferred_datetime
    )
