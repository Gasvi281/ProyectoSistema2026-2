"""
client_resolver.py
------------------
Implementación de ClientResolverPort que resuelve chat_id → client_id de backend.

Mismo patrón que agent_slots.py/booking.py: implementación HTTP (HttpClientResolver,
aún stub) más factory get_client_resolver_provider() seleccionada por
CLIENT_RESOLVER_MODE.

ESTADO: el backend no expone /clients (confirmado — no hay endpoint). El stub lanza
NotImplementedError con mensaje descriptivo. Implementar cuando Backend Lead añada
soporte al endpoint.
"""

import os

from agent.ports import ClientResolverPort


class HttpClientResolver(ClientResolverPort):
    """Stub — no implementado: el backend no expone /clients todavía."""

    async def resolve_client(
        self, chat_id: str, phone: str | None = None, full_name: str | None = None
    ) -> str:
        raise NotImplementedError(
            "HttpClientResolver no está disponible: el backend no expone /clients "
            "(3.2 pendiente de Backend Lead). Usa CLIENT_RESOLVER_MODE=fake."
        )


def get_client_resolver_provider() -> ClientResolverPort:
    """
    Elige la implementación según CLIENT_RESOLVER_MODE:
    "fake" (por defecto) → FakeClientResolver (sin HTTP, estable en memoria)
    "http"               → HttpClientResolver (stub — lanza NotImplementedError)
    """
    mode = os.getenv("CLIENT_RESOLVER_MODE", "fake").lower()

    if mode == "fake":
        from agent.fakes import FakeClientResolver
        return FakeClientResolver()
    elif mode == "http":
        return HttpClientResolver()
    else:
        raise ValueError(f"CLIENT_RESOLVER_MODE inválido: {mode!r}")
