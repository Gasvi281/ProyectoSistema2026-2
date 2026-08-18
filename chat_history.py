"""
chat_history.py
----------------
Guarda el historial de conversación de cada chat de Telegram, para que el
modelo de IA tenga contexto de los mensajes anteriores (sin esto, cada
mensaje se trataba como si fuera la primera vez que el usuario escribe).

Se guarda en un diccionario en memoria, indexado por chat_id. Esto es
suficiente para las pruebas del sprint, pero hay que tener claro su límite:
se pierde todo si reinicias uvicorn (o si el proceso se cae). Para producción
real, esto se reemplazaría por una base de datos (Redis para algo rápido,
o Postgres si ya quieren guardarlo permanentemente junto a los leads).
"""

from collections import defaultdict

# Cuántos mensajes (usuario + modelo, contados por separado) se guardan
# como máximo por chat. Evita que la memoria crezca sin límite en una
# conversación muy larga, y evita mandarle demasiado contexto al modelo
# en cada llamada (más contexto = más lento y más caro).
MAX_HISTORY_MESSAGES = 20

_histories: dict[int, list[dict]] = defaultdict(list)


def get_history(chat_id: int) -> list[dict]:
    """Devuelve el historial de un chat. Lista vacía si es la primera vez."""
    return _histories[chat_id]


def add_message(chat_id: int, role: str, text: str) -> None:
    """
    Agrega un mensaje al historial de un chat.
    role debe ser "user" (mensaje del usuario) o "model" (respuesta de la IA).
    """
    history = _histories[chat_id]
    history.append({"role": role, "text": text})

    # Si se pasa del límite, recorta los mensajes más viejos
    if len(history) > MAX_HISTORY_MESSAGES:
        del history[: len(history) - MAX_HISTORY_MESSAGES]


def clear_history(chat_id: int) -> None:
    """Borra el historial de un chat (usado por /start y /reset)."""
    _histories[chat_id] = []
