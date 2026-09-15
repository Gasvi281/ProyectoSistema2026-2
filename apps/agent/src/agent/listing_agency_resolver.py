"""
listing_agency_resolver.py
--------------------------
Factory que selecciona la implementación de ListingAgencyResolverPort.
Mismo patrón que client_resolver.py: modo "fake" (por defecto) o "http".

Semántica del modo "http" (HttpListingAgencyResolver):
  El backend NO expone agency_id en el body de GET /listings/{id}
  (verificado en probe de 4 variantes contra el backend desplegado,
  2026-09-14). El endpoint sí exige X-Agency-Id del caller; una agencia
  sin fila AI_AGENT recibe 403.
  Por tanto el resolver actúa como existence-check:
    - 200     → el listing existe y es accesible bajo la agencia del bot
               → devuelve caller_agency_id (env AGENCY_ID)
    - 404/422 → listing inexistente, inaccesible, o listing_id no es un UUID
               válido → UnknownListingError (fail-loud).
               Nota sobre 422: GET /listings/{id} no tiene body ni query params;
               el único motivo de 422 es que el path param no pase la validación
               de UUID de FastAPI. Funcionalmente equivale a "no existe" — no
               puede enmascarar otro tipo de error de validación.
    - resto   → raise_for_status() → HTTPStatusError (auth/config/infra, no
               enmascarar como "no encontré el listing")
  El agency_id del caller (env AGENCY_ID) y el del listing coinciden
  necesariamente para este bot — verificado, no asumido (el bot tiene
  exactamente una fila AI_AGENT).
"""

import os

import httpx

from agent.ports import ListingAgencyResolverPort
from agent.backend_auth import check_backend_config, get_auth_headers


class HttpListingAgencyResolver(ListingAgencyResolverPort):
    """Valida que listing_id sea accesible bajo la agencia del bot vía GET /listings/{id}.

    Requiere que AGENCY_ID esté seteado (identidad del caller ante el backend).
    Lanza UnknownListingError en 404. Propaga HTTPStatusError en cualquier otro
    error HTTP (nunca lo transforma en UnknownListingError).
    """

    def __init__(self):
        check_backend_config()
        # Fail-loud: AGENCY_ID identifica al caller ante el backend.
        # Si falta, GET /listings devolvería 400 confuso a mitad de conversación.
        # Preferimos fallar al construir el resolver (una vez), no por request.
        self.caller_agency_id = os.getenv("AGENCY_ID")
        if not self.caller_agency_id:
            raise ValueError(
                "AGENCY_ID no está seteado — requerido para identificar al caller "
                "ante el backend (X-Agency-Id en GET /listings/{id})."
            )
        self.base_url = os.getenv("BACKEND_URL", "").rstrip("/")

    async def resolve(self, listing_id: str) -> str:
        from agent.fakes import UnknownListingError

        url = f"{self.base_url}/listings/{listing_id}"
        headers = await get_auth_headers(self.caller_agency_id)
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, headers=headers)

        if resp.status_code in (404, 422):
            raise UnknownListingError(
                f"listing_id {listing_id!r} no existe, es inaccesible bajo la agencia "
                f"{self.caller_agency_id!r}, o no es un UUID válido"
            )
        resp.raise_for_status()  # 400/403/5xx → HTTPStatusError (fail-loud)
        # El backend no expone agency_id del listing — ver docstring del módulo.
        return self.caller_agency_id


def get_listing_agency_resolver_provider() -> ListingAgencyResolverPort:
    """
    Elige la implementación según LISTING_AGENCY_RESOLVER_MODE:
    "fake" (por defecto) → FakeListingAgencyResolver vacío (sin mappings aún)
    "http"               → HttpListingAgencyResolver (GET /listings/{id} como
                           existence-check; devuelve caller AGENCY_ID)
    """
    mode = os.getenv("LISTING_AGENCY_RESOLVER_MODE", "fake").lower()

    if mode == "fake":
        from agent.fakes import FakeListingAgencyResolver
        return FakeListingAgencyResolver()
    elif mode == "http":
        return HttpListingAgencyResolver()
    else:
        raise ValueError(f"LISTING_AGENCY_RESOLVER_MODE inválido: {mode!r}")
