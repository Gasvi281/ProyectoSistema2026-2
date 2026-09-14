"""
listing_agency_resolver.py
--------------------------
Factory que selecciona la implementación de ListingAgencyResolverPort.
Mismo patrón que client_resolver.py: modo "fake" (por defecto) o "http"
(stub — no implementado aún; el backend no expone listing → agency_id).

El fake arranca sin mappings (FakeListingAgencyResolver({})). Mientras no
existan datos reales de listing_id → agency_id, todo intento de crear un
lead lanzará UnregisteredEntityError — eso es correcto y esperado, no un
bug a solucionar con seed data inventada.
Agregar mappings reales aquí cuando el catálogo del backend esté conectado.
"""

import os

from agent.ports import ListingAgencyResolverPort


def get_listing_agency_resolver_provider() -> ListingAgencyResolverPort:
    """
    Elige la implementación según LISTING_AGENCY_RESOLVER_MODE:
    "fake" (por defecto) → FakeListingAgencyResolver vacío (sin mappings aún)
    "http"               → NotImplementedError (pendiente de soporte en backend)
    """
    mode = os.getenv("LISTING_AGENCY_RESOLVER_MODE", "fake").lower()

    if mode == "fake":
        from agent.fakes import FakeListingAgencyResolver
        return FakeListingAgencyResolver()
    elif mode == "http":
        raise NotImplementedError(
            "HttpListingAgencyResolver no está disponible: el backend no expone "
            "agency_id en /listings todavía. Usa LISTING_AGENCY_RESOLVER_MODE=fake."
        )
    else:
        raise ValueError(f"LISTING_AGENCY_RESOLVER_MODE inválido: {mode!r}")
