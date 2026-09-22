import asyncio
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

# Script de desarrollo: no hay staging; forzar todos los resolvers a fake
# para garantizar que ninguna ejecución escriba en el backend de producción.
# Se aplica DESPUÉS de load_dotenv y ANTES de get_agent() / ConversationalAgent().
for _var in (
    "CLIENT_RESOLVER_MODE",
    "LISTING_AGENCY_RESOLVER_MODE",
    "AGENT_SLOTS_MODE",
    "APPOINTMENT_BOOKING_MODE",
    "LEAD_MODE",
    "NOTIFICATIONS_MODE",
):
    os.environ[_var] = "fake"

from agent.core_langchain import get_agent


async def main():
    agent = get_agent()
    chat_id = "console_user_001"
    channel = "console"
    print("Escribe 'salir' para terminar.\n")
    while True:
        msg = input("Tú: ").strip()
        if msg.lower() in {"salir", "exit", "quit"}:
            break
        if not msg:
            continue
        try:
            reply = await agent.handle_turn(chat_id, channel, msg)
            print(f"\nAgente: {reply.reply_text}\n")
        except Exception as e:
            print(f"\n[ERROR] {type(e).__name__}: {e}\n")


asyncio.run(main())
