"""REPL interactivo para el agente."""
import asyncio
import logging
import os
from pathlib import Path
from dotenv import load_dotenv

# apps/agent/.env — tres niveles arriba desde src/agent/
load_dotenv(Path(__file__).parent.parent.parent / ".env")

if os.getenv("AGENT_DEBUG", "").lower() in ("1", "true", "yes"):
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(message)s"))
    _steps_logger = logging.getLogger("agent.steps")
    _steps_logger.setLevel(logging.DEBUG)
    _steps_logger.addHandler(_handler)

from agent.core_langchain import get_agent


async def main():
    print("=" * 70)
    print("Asistente Inmobiliario Medellín — Modo Consola")
    print("=" * 70)
    print("\n¡Hola! Estoy aquí para ayudarte a encontrar propiedades y agendar visitas.")
    print("Escribe 'salir' para terminar.\n")

    agent = get_agent()
    chat_id = "console_user_001"
    channel = "console"

    while True:
        try:
            user_input = input("Tú: ").strip()
        except EOFError:
            break

        if not user_input:
            continue

        if user_input.lower() == "salir":
            print("¡Hasta luego!")
            break

        try:
            reply = await agent.handle_turn(chat_id, channel, user_input)
            print(f"\nAsistente: {reply.reply_text}\n")
        except Exception as e:
            print(f"\nError: {str(e)}\n")


if __name__ == "__main__":
    asyncio.run(main())
