"""
backend_auth.py
---------------
Ayudante compartido de autenticación para todos los clientes HTTP que llaman
al backend de Homelitics.

El backend acepta tres mecanismos de auth, por precedencia:
  1. JWT de Supabase (vivo)  : BOT_EMAIL + BOT_PASSWORD  →  Bearer <token rotante>
  2. JWT de Supabase (estático): BACKEND_SERVICE_TOKEN    →  Bearer <token fijo>
  3. Bypass de dev           : DEV_AGENT_ID               →  X-Dev-Agent-Id: <id>

Reglas de activación en get_auth_headers():
  - Si BOT_EMAIL y BOT_PASSWORD están AMBOS presentes → modo 1 (live JWT).
  - Si solo uno de los dos está presente             → ValueError (fail-loud; no
    fall-through silencioso a otro modo).
  - Si ninguno está presente y BACKEND_SERVICE_TOKEN está → modo 2.
  - Si ninguno está presente y DEV_AGENT_ID está         → modo 3.
  - Si ninguno está configurado                          → ValueError.

Si ninguno está configurado, check_backend_config() falla en construcción del
cliente HTTP, antes de que se haga ninguna petición.
"""

import os
from agent.jwt_provider import SupabaseJwtProvider

# ---------------------------------------------------------------------------
# Singleton perezoso del proveedor JWT
# Patrón: variable de módulo inicializada a None, creada al primer uso.
# Análogo al _registry de agency_registry.py (estado de módulo + funciones
# de módulo), pero para una instancia de clase.
# _reset_provider_for_tests() permite aislar tests que necesiten un provider
# limpio, igual que agency_registry.clear().
# ---------------------------------------------------------------------------

_provider: SupabaseJwtProvider | None = None


def _get_provider() -> SupabaseJwtProvider:
    """Retorna el SupabaseJwtProvider de proceso, creándolo si aún no existe."""
    global _provider
    if _provider is None:
        _provider = SupabaseJwtProvider()
    return _provider


def _reset_provider_for_tests() -> None:
    """
    Descarta el singleton para que el siguiente _get_provider() cree uno nuevo.
    Úsalo en fixtures/tests que necesiten inyectar un provider falso o limpiar
    el estado entre casos.
    """
    global _provider
    _provider = None


# ---------------------------------------------------------------------------
# Función principal de autenticación
# ---------------------------------------------------------------------------

async def get_auth_headers(agency_id: str | None = None) -> dict:
    """
    Retorna los encabezados de autenticación para llamadas al backend.

    Precedencia: BOT_EMAIL+BOT_PASSWORD (live JWT) → BACKEND_SERVICE_TOKEN
    (Bearer estático) → DEV_AGENT_ID (X-Dev-Agent-Id).

    Regla fail-loud: si exactamente uno de BOT_EMAIL / BOT_PASSWORD está
    configurado (probable error de tipeo en el nombre de la variable), lanza
    ValueError nombrando la que falta — no cae silenciosamente al siguiente
    modo de autenticación.

    Lanza ValueError si ningún mecanismo está configurado — esto no debería
    ocurrir si se llamó a check_backend_config() en __init__.

    Si se pasa agency_id, agrega el encabezado X-Agency-Id que el backend
    requiere para scoping de tenant.
    """
    bot_email = os.getenv("BOT_EMAIL")
    bot_password = os.getenv("BOT_PASSWORD")
    token = os.getenv("BACKEND_SERVICE_TOKEN")
    dev_agent_id = os.getenv("DEV_AGENT_ID")

    # Fail-loud: exactamente uno de los dos vars de Supabase configurado → error.
    # No permitimos que un BOT_EMAIL sin BOT_PASSWORD (o viceversa) caiga
    # silenciosamente a BACKEND_SERVICE_TOKEN o DEV_AGENT_ID.
    if bool(bot_email) != bool(bot_password):
        missing = "BOT_PASSWORD" if bot_email else "BOT_EMAIL"
        raise ValueError(
            f"Configuración de autenticación Supabase incompleta: falta {missing}. "
            "Define BOT_EMAIL y BOT_PASSWORD juntos, o ninguno de los dos."
        )

    if bot_email and bot_password:
        # Modo 1: live JWT — get_token() renueva el token si está por expirar.
        jwt = await _get_provider().get_token()
        headers: dict = {"Authorization": f"Bearer {jwt}"}
    elif token:
        # Modo 2: JWT estático pegado en variable de entorno.
        headers = {"Authorization": f"Bearer {token}"}
    elif dev_agent_id:
        # Modo 3: bypass de dev — NO envía Authorization.
        headers = {"X-Dev-Agent-Id": dev_agent_id}
    else:
        raise ValueError(
            "Se requiere al menos un mecanismo de autenticación para el backend: "
            "BOT_EMAIL+BOT_PASSWORD (JWT vivo), BACKEND_SERVICE_TOKEN (JWT estático) "
            "o DEV_AGENT_ID (bypass de dev). Ninguno está configurado."
        )

    if agency_id:
        headers["X-Agency-Id"] = agency_id

    return headers


# ---------------------------------------------------------------------------
# Validación de configuración (usada en __init__ de los adaptadores HTTP)
# ---------------------------------------------------------------------------

def check_backend_config() -> None:
    """
    Valida que BACKEND_URL y al menos un mecanismo de auth estén configurados.
    Llámala desde __init__ de cada cliente HTTP.

    Mecanismos válidos (basta uno):
      - BOT_EMAIL y BOT_PASSWORD (ambos juntos)
      - BACKEND_SERVICE_TOKEN
      - DEV_AGENT_ID

    Lanza ValueError con un mensaje descriptivo si falta algo.
    """
    faltantes = []

    if not os.getenv("BACKEND_URL"):
        faltantes.append("BACKEND_URL")

    bot_email = os.getenv("BOT_EMAIL")
    bot_password = os.getenv("BOT_PASSWORD")
    token = os.getenv("BACKEND_SERVICE_TOKEN")
    dev_agent_id = os.getenv("DEV_AGENT_ID")

    tiene_auth = bool((bot_email and bot_password) or token or dev_agent_id)
    if not tiene_auth:
        faltantes.append(
            "BOT_EMAIL+BOT_PASSWORD (JWT vivo), BACKEND_SERVICE_TOKEN (JWT estático) "
            "o DEV_AGENT_ID (bypass de dev)"
        )

    if faltantes:
        raise ValueError(
            f"Faltan variables de entorno para conectar al backend: "
            f"{', '.join(faltantes)}"
        )
