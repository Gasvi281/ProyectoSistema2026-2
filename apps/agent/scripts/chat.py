import asyncio
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

from agent.core_langchain import get_agent


async def main():
    agent = get_agent()
    print("Escribe 'salir' para terminar.\n")
    while True:
        msg = input("Tú: ").strip()
        if msg.lower() in {"salir", "exit", "quit"}:
            break
        if not msg:
            continue
        try:
            reply = await agent.handle_turn(msg)
            print(f"\nAgente: {reply}\n")
        except Exception as e:
            print(f"\n[ERROR] {type(e).__name__}: {e}\n")


asyncio.run(main())