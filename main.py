"""
main.py
-------
Punto de entrada de la aplicación. Define el servidor FastAPI y el
endpoint del webhook (donde Telegram nos manda los mensajes entrantes).

Conecta los otros dos módulos:
  - ai_service.ask_ai()          -> genera la respuesta con Gemini
  - telegram_service.send_message() -> entrega esa respuesta al usuario

config.py se importa indirectamente a través de esos dos módulos.
"""

import os
import sys

# Hace importable el paquete agent desde apps/agent/src sin tocar run.ps1
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "apps", "agent", "src"))

from fastapi import FastAPI, Request, Header, HTTPException, BackgroundTasks

from config import TELEGRAM_WEBHOOK_SECRET
from ai_service import ask_ai  # conservado intacto; ya no se usa en el flujo normal
from telegram_service import send_message
from agent.core_langchain import handle_turn
import chat_history

app = FastAPI()


@app.get("/")
async def health_check():
    """Endpoint simple para confirmar que el servidor está vivo."""
    return {"status": "ok", "service": "Proptech Telegram Webhook"}


@app.post("/webhook/telegram")
async def telegram_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    x_telegram_bot_api_secret_token: str | None = Header(default=None),
):
    """
    Telegram hace POST aquí cada vez que llega un mensaje nuevo al bot.
    """
    # 1. Verificar que la petición viene realmente de Telegram
    if TELEGRAM_WEBHOOK_SECRET and x_telegram_bot_api_secret_token != TELEGRAM_WEBHOOK_SECRET:
        raise HTTPException(status_code=401, detail="Secreto inválido")

    update = await request.json()
    message = update.get("message")

    if not message or "text" not in message:
        # Ignoramos stickers, fotos, etc. por ahora; igual respondemos 200
        # para que Telegram no piense que falló y reintente.
        return {"ok": True}

    chat_id = message["chat"]["id"]
    user_text = message["text"]
    user_name = message.get("from", {}).get("first_name", "usuario")

    print(f"[{user_name}] ({chat_id}): {user_text}")

    # 2. Procesamos en segundo plano y respondemos 200 de inmediato.
    #    Así Telegram no reintenta el envío mientras la IA "piensa".
    background_tasks.add_task(handle_message, chat_id, user_text)

    return {"ok": True}


async def handle_message(chat_id: int, user_text: str) -> None:
    """Genera la respuesta de la IA (con contexto del historial) y la envía."""
    if user_text == "/start":
        reply = "¡Hola! Soy el agente de IA del marketplace inmobiliario 🏠. Cuéntame qué estás buscando."
        chat_history.clear_history(chat_id)  # empezamos limpio en cada /start

    elif user_text == "/reset":
        chat_history.clear_history(chat_id)
        reply = "Listo, borré el historial de nuestra conversación. ¿En qué te ayudo?"

    else:
        history = chat_history.get_history(chat_id)
        try:
            agent_reply = await handle_turn(
                client_id=str(chat_id),
                channel="telegram",
                message=user_text,
            )
            reply = agent_reply.reply_text
        except Exception as e:
            print(f"[main] Error llamando al agente: {e}")
            reply = "Estamos teniendo un problema, intenta de nuevo en un momento."

        # Guardamos ambos turnos para que el próximo mensaje tenga contexto
        chat_history.add_message(chat_id, "user", user_text)
        chat_history.add_message(chat_id, "model", reply)

    await send_message(chat_id, reply)