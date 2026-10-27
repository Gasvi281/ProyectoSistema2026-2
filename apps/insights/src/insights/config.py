"""Configuración del servicio de insights. Carga apps/insights/.env."""
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent.parent / ".env")


def backend_url() -> str:
    return os.getenv("BACKEND_URL", "https://homelitics-api.onrender.com").rstrip("/")


def llm_mode() -> str:
    return os.getenv("INSIGHTS_LLM_MODE", "fake").lower()


def llm_max_retries() -> int:
    # Intentos totales de la librería de Gemini: 1 = sin reintentos (0 no es válido).
    return max(1, int(os.getenv("INSIGHTS_LLM_MAX_RETRIES", "1")))


def llm_timeout() -> float:
    # Segundos por intento.
    return float(os.getenv("INSIGHTS_LLM_TIMEOUT", "60"))


def cors_origins() -> list[str]:
    raw = os.getenv("INSIGHTS_CORS_ORIGINS", "")
    return [o.strip() for o in raw.split(",") if o.strip()]
