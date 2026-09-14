"""
client_resolver.py
------------------
Implementación de ClientResolverPort que resuelve chat_id → client_id de backend
mediante POST /clients (create-or-get idempotente por telegram_user_id).

Mismo patrón que agent_slots.py / booking.py / leads.py:
- __init__ llama a check_backend_config() y lee BACKEND_URL.
- Una instancia de httpx.AsyncClient por llamada (context manager).
- Auth via get_auth_headers(None): solo Authorization, sin X-Agency-Id
  (el endpoint /clients es global, no perteneciente a ninguna agencia).
- raise_for_status() delega el manejo de errores al caller.

Contrato del backend (confirmado commit ba2def5, main, desplegado):
  REQUEST  → { full_name, phone?, email?, telegram_user_id? }
  RESPONSE → { id: <uuid>, created_at: <datetime> }
  200 = ya existía (dedup por telegram_user_id) · 201 = cliente nuevo
  Ambos son éxito; raise_for_status() no levanta en 2xx.

Selección de implementación vía CLIENT_RESOLVER_MODE:
  "fake" (por defecto) → FakeClientResolver (sin HTTP, estable en memoria)
  "http"               → HttpClientResolver (llamada real al backend)
"""

import os

import httpx

from agent.ports import ClientResolverPort
from agent.backend_auth import check_backend_config, get_auth_headers


class HttpClientResolver(ClientResolverPort):
    """Resuelve chat_id → client_id vía POST /clients del backend real.

    Requiere que la service account tenga el scope clients:create en Supabase.
    Si el scope no está asignado, POST /clients responderá 401/403 y
    raise_for_status() propagará httpx.HTTPStatusError al caller.
    """

    def __init__(self):
        check_backend_config()
        self.base_url = os.getenv("BACKEND_URL", "").rstrip("/")

    async def resolve_client(
        self, chat_id: str, phone: str | None = None, full_name: str | None = None
    ) -> str:
        # DEUDA TÉCNICA INTENCIONAL: el backend exige full_name (requerido, no-null)
        # pero el bot aún no captura el nombre real del usuario de Telegram.
        # Se usa un placeholder provisional para evitar un 422. La captura real
        # del nombre (from.first_name del webhook → resolve_client) es una historia
        # aparte, fuera del scope de esta implementación.
        full_name = full_name or f"Telegram user {chat_id}"

        url = f"{self.base_url}/clients"
        # get_auth_headers(None): sin X-Agency-Id — /clients es global (no per-agencia).
        headers = {"Content-Type": "application/json", **(await get_auth_headers(None))}
        body = {
            "full_name": full_name,
            "phone": phone,
            "email": None,
            # Estricto: int(chat_id) puede levantar ValueError y DEBE propagar.
            # Un null silencioso rompería el dedup del backend (crea cliente nuevo
            # cada vez). Hoy el único canal es Telegram, así que un chat_id
            # no-numérico indica un bug aguas arriba, no un caso a tolerar acá.
            "telegram_user_id": int(chat_id),
        }
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, json=body, headers=headers)
            resp.raise_for_status()  # 200 y 201 no lanzan → ambos son éxito (dedup)
            return resp.json()["id"]


def get_client_resolver_provider() -> ClientResolverPort:
    """
    Elige la implementación según CLIENT_RESOLVER_MODE:
    "fake" (por defecto) → FakeClientResolver (sin HTTP, estable en memoria)
    "http"               → HttpClientResolver (llama al backend real)
    """
    mode = os.getenv("CLIENT_RESOLVER_MODE", "fake").lower()

    if mode == "fake":
        from agent.fakes import FakeClientResolver
        return FakeClientResolver()
    elif mode == "http":
        return HttpClientResolver()
    else:
        raise ValueError(f"CLIENT_RESOLVER_MODE inválido: {mode!r}")
