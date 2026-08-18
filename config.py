"""
config.py
---------
Lee las variables de entorno (desde el archivo .env) y las deja
disponibles como constantes de Python para que el resto de archivos
las importen sin tener que leer el .env cada uno por su cuenta.

Todos los demás archivos (main.py, telegram_service.py, ai_service.py)
importan de aquí en vez de usar os.environ directamente.
"""

import os
from dotenv import load_dotenv

# Carga el contenido de .env al entorno del proceso (solo aplica en local;
# en un hosting real, las variables se configuran en el panel del proveedor).
load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_WEBHOOK_SECRET = os.getenv("TELEGRAM_WEBHOOK_SECRET")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

TELEGRAM_API_URL = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"

# Validación temprana: si falta algo esencial, preferimos que el server
# truene apenas arranca (mensaje claro) y no en medio de una petición.
if not TELEGRAM_BOT_TOKEN:
    raise RuntimeError("Falta TELEGRAM_BOT_TOKEN en el archivo .env")
if not GEMINI_API_KEY:
    raise RuntimeError("Falta GEMINI_API_KEY en el archivo .env")
