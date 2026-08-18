"""
ai_service.py
--------------
Toda la lógica para hablar con el modelo de IA (Gemini). Está aislado
del resto del proyecto a propósito: main.py solo conoce la función
ask_ai(texto) -> respuesta. Cuando reemplacen esto por el agente de
tu compañero, solo tocan este archivo; telegram_service.py y main.py
no cambian.
"""

import httpx
from config import GEMINI_API_KEY

GEMINI_MODEL = "gemini-3.5-flash"
GEMINI_URL = (
    f"https://generativelanguage.googleapis.com/v1beta/models/"
    f"{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"
)

SYSTEM_INSTRUCTION = (
    "Eres un asistente inmobiliario. Responde de forma breve, útil y "
    "amable en español, ayudando a personas que buscan comprar o "
    "arrendar propiedades."
)


async def ask_ai(user_text: str, history: list[dict] | None = None) -> str:
    """
    Manda el texto del usuario a Gemini junto con el historial de la
    conversación (si existe), y devuelve la respuesta en texto plano.

    history es una lista de mensajes previos con forma
    [{"role": "user"|"model", "text": "..."}], en orden cronológico.
    Se manda vacía o None si es el primer mensaje del chat.
    """
    contents = _build_contents(history or [], user_text)

    payload = {
        "system_instruction": {"parts": [{"text": SYSTEM_INSTRUCTION}]},
        "contents": contents,
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(GEMINI_URL, json=payload)

    if response.status_code != 200:
        print(f"[ai_service] Error llamando a Gemini: {response.text}")
        return "Lo siento, tuve un problema procesando tu mensaje. Intenta de nuevo en un momento."

    data = response.json()
    try:
        return data["candidates"][0]["content"]["parts"][0]["text"].strip()
    except (KeyError, IndexError):
        print(f"[ai_service] Respuesta inesperada de Gemini: {data}")
        return "No pude generar una respuesta en este momento."


def _build_contents(history: list[dict], user_text: str) -> list[dict]:
    """
    Convierte el historial guardado (formato interno de chat_history.py) al
    formato que espera la API de Gemini: una lista de turnos alternando
    "user" y "model", terminando con el mensaje nuevo del usuario.
    """
    contents = [
        {"role": msg["role"], "parts": [{"text": msg["text"]}]} for msg in history
    ]
    contents.append({"role": "user", "parts": [{"text": user_text}]})
    return contents