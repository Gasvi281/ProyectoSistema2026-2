"""Adaptador HTTP de búsqueda de propiedades + factory + guard de inicio.

Limitación conocida (alcance MVP): solo busca dentro de la agencia identificada
por AGENCY_ID (endpoint GET /listings del backend es intra-agencia). El backend
no tiene endpoint cross-agency; esa extensión requiere una historia de backend aparte.
"""
from __future__ import annotations

import logging
import os
from decimal import Decimal
from typing import Optional

import httpx

from agent.backend_auth import check_backend_config, get_auth_headers
from agent.fakes import _matches, _type_es
from agent.ports import ListingSearchPort
from agent.types import Property, SearchFilters

logger = logging.getLogger(__name__)


def _map_listing(row: dict) -> Property:
    """Convierte un dict ListingOut del backend a Property.

    Campos verificados contra homelitics-crm/app/schemas.py:279-293:
    id, property_id, agent_id, operation_type, asking_price, status,
    published_at, city, neighborhood, address, property_type, area_m2,
    bedrooms, bathrooms. No existe campo title/name — se compone.
    """
    pt = row.get("property_type") or ""
    nb = row.get("neighborhood") or ""
    city = row.get("city") or ""
    addr = row.get("address") or ""

    # Nombre compuesto: "Apartamento en Laureles" / "Casa en Medellín".
    # Fallback progresivo hasta tener algo legible.
    if nb or city:
        name = f"{_type_es(pt)} en {nb or city}"
    elif addr:
        name = addr
    else:
        name = _type_es(pt) or "Propiedad"

    location = nb or city or ""
    asking_price = row.get("asking_price") or 0
    area_m2 = row.get("area_m2")

    return Property(
        id=str(row["id"]),
        name=name,
        location=location,
        price=int(Decimal(str(asking_price))),
        area_sqm=int(Decimal(str(area_m2))) if area_m2 is not None else 0,
        bedrooms=row.get("bedrooms") or 0,
        bathrooms=row.get("bathrooms") or 0,
        property_type=pt,
        description=addr,
        operation_type=row.get("operation_type"),
    )


class HttpListingSearch(ListingSearchPort):
    """Catálogo real de la agencia del bot (GET /listings).

    - status=ACTIVE filtrado server-side.
    - operation_type filtrado server-side cuando está en los filtros.
    - price, bedrooms, neighborhood: filtro client-side con _matches.
    - Una sola petición limit=200 (máx del backend). Agencias con >200 propiedades
      activas solo ven las 200 más recientes — deuda técnica conocida.
    """

    def __init__(self) -> None:
        check_backend_config()
        self.caller_agency_id = os.getenv("AGENCY_ID")
        if not self.caller_agency_id:
            raise ValueError(
                "AGENCY_ID no está seteado — requerido para identificar al caller "
                "ante el backend (X-Agency-Id en GET /listings)."
            )
        self.base_url = os.getenv("BACKEND_URL", "").rstrip("/")

    async def search(self, filters: SearchFilters, limit: int = 5) -> list[Property]:
        params: dict = {"status": "ACTIVE", "limit": 200}
        if filters.operation_type:
            params["operation_type"] = filters.operation_type

        headers = await get_auth_headers(self.caller_agency_id)
        url = f"{self.base_url}/listings"

        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.get(url, params=params, headers=headers)
        resp.raise_for_status()

        rows: list[dict] = resp.json()
        props = [_map_listing(r) for r in rows]
        filtered = [p for p in props if _matches(p, filters)]
        return filtered[:limit]

    async def get_listing(self, listing_id: str) -> Optional[Property]:
        """Retorna el listing o None si no existe / está fuera de la agencia (404/422)."""
        headers = await get_auth_headers(self.caller_agency_id)
        url = f"{self.base_url}/listings/{listing_id}"

        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.get(url, headers=headers)

        if resp.status_code in (404, 422):
            return None
        resp.raise_for_status()
        return _map_listing(resp.json())


def get_listing_search_provider() -> ListingSearchPort:
    """Selecciona el proveedor según LISTING_SEARCH_MODE (default: fake)."""
    from agent.fakes import FakeListingSearch

    mode = os.getenv("LISTING_SEARCH_MODE", "fake").lower()
    if mode == "fake":
        return FakeListingSearch()
    if mode == "http":
        return HttpListingSearch()
    raise ValueError(
        f"LISTING_SEARCH_MODE inválido: {mode!r}. Valores admitidos: fake, http."
    )


def check_listing_search_modes() -> None:
    """Valida combinaciones de modos al arrancar la app (llamar desde lifespan).

    Rechaza dos combinaciones inválidas:
    1. LISTING_SEARCH_MODE=http sin AGENCY_ID → error de configuración temprano.
    2. LEAD_MODE=http + LISTING_SEARCH_MODE=fake → el catálogo fake devuelve IDs
       sintéticos (prop_001…) que no existen en el backend real; create_or_get_lead
       fallaría con UNKNOWN_LISTING en el primer turno. Misma clase de bug que el
       par LEAD_MODE=http + LISTING_AGENCY_RESOLVER_MODE=fake (commit 9562ab1).
    """
    search_mode = os.getenv("LISTING_SEARCH_MODE", "fake").lower()
    lead_mode = os.getenv("LEAD_MODE", "fake").lower()

    if search_mode == "http" and not os.getenv("AGENCY_ID"):
        raise ValueError(
            "Configuración inválida: LISTING_SEARCH_MODE=http requiere AGENCY_ID. "
            "Agrega AGENCY_ID al .env."
        )
    if lead_mode == "http" and search_mode == "fake":
        raise ValueError(
            "Configuración inválida: LEAD_MODE=http con LISTING_SEARCH_MODE=fake. "
            "El catálogo fake devuelve IDs sintéticos (prop_001…) que no existen en "
            "el backend — create_or_get_lead fallaría con UNKNOWN_LISTING. "
            "Usa LISTING_SEARCH_MODE=http o cambia LEAD_MODE=fake."
        )
