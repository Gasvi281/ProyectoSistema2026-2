"""
backend_auth.py
---------------
Ayudante compartido de autenticación para todos los clientes HTTP que llaman
al backend de Homelitics.

El backend acepta dos mecanismos de auth (confirmado por auditoría):
  - JWT de Supabase:  Authorization: Bearer <token>  (BACKEND_SERVICE_TOKEN)
  - Bypass de dev:    X-Dev-Agent-Id: <id>            (DEV_AGENT_ID)

Si ninguno está configurado, check_backend_config() falla en construcción del
cliente HTTP, antes de que se haga ninguna petición — en vez del envío silencioso
sin autenticación que existía antes.
"""

import os


def get_auth_headers() -> dict:
    """
    Retorna los encabezados de autenticación para llamadas al backend.

    Precedencia: BACKEND_SERVICE_TOKEN (Bearer) → DEV_AGENT_ID (X-Dev-Agent-Id).
    Lanza ValueError si ninguno está configurado — esto no debería ocurrir si
    se llamó a check_backend_config() en __init__.
    """
    token = os.getenv("BACKEND_SERVICE_TOKEN")
    dev_agent_id = os.getenv("DEV_AGENT_ID")

    if token:
        return {"Authorization": f"Bearer {token}"}
    if dev_agent_id:
        return {"X-Dev-Agent-Id": dev_agent_id}
    raise ValueError(
        "Se requiere al menos un mecanismo de autenticación para el backend: "
        "BACKEND_SERVICE_TOKEN (JWT de Supabase) o DEV_AGENT_ID (bypass de dev). "
        "Ninguno está configurado."
    )


def check_backend_config() -> None:
    """
    Valida que BACKEND_URL y al menos un mecanismo de auth estén configurados.
    Llámala desde __init__ de cada cliente HTTP.

    Lanza ValueError con un mensaje descriptivo si falta algo.
    """
    faltantes = []

    if not os.getenv("BACKEND_URL"):
        faltantes.append("BACKEND_URL")

    token = os.getenv("BACKEND_SERVICE_TOKEN")
    dev_agent_id = os.getenv("DEV_AGENT_ID")
    if not token and not dev_agent_id:
        faltantes.append("BACKEND_SERVICE_TOKEN o DEV_AGENT_ID")

    if faltantes:
        raise ValueError(
            f"Faltan variables de entorno para conectar al backend: "
            f"{', '.join(faltantes)}"
        )
