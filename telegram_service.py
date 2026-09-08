"""
telegram_service.py
--------------------
Todo lo relacionado con LLAMAR a la API de Telegram (salida).
main.py usa send_message() para responderle al usuario después de
recibir su mensaje.

Nota: esto es distinto del webhook (que es Telegram llamándonos a NOSOTROS).
Este archivo es la dirección contraria: nosotros llamando a Telegram.
"""

import httpx
from config import TELEGRAM_API_URL


async def send_message(chat_id: int, text: str) -> None:
    """Envía un mensaje de texto a un chat de Telegram."""
    url = f"{TELEGRAM_API_URL}/sendMessage"
    payload = {"chat_id": chat_id, "text": text}

    async with httpx.AsyncClient() as client:
        response = await client.post(url, json=payload)

    if response.status_code != 200:
        print(f"[telegram_service] Error enviando mensaje: {response.text}")
