"""
agency_registry.py
------------------
Registro en memoria de la asociación entre entidades de backend
(listing_id, lead_id, agent_id) y el agency_id dueño del listing.

El registry persiste mientras el proceso corre.
DEUDA TÉCNICA: misma clase de riesgo que el historial de conversación en
memoria (FakeConversationStore) y el MemorySaver de LangGraph — se pierde
bajo deploy multi-worker. Revisitar si se adopta un store compartido para
esas estructuras.
"""

_registry: dict[str, str] = {}  # entity_id → agency_id


class UnregisteredEntityError(RuntimeError):
    """No hay agency_id registrado para este lead_id o agent_id.

    Indica que create_or_get_lead no se ejecutó antes de
    check_agent_availability o book_appointment. Verifica el orden del
    flujo de agendamiento (system.md § "Flujo de agendamiento con el
    backend real", pasos 1-2-4).
    """


def register(
    *,
    agency_id: str,
    listing_id: str | None = None,
    lead_id: str | None = None,
    agent_id: str | None = None,
) -> None:
    """Registra agency_id bajo uno o más ids de entidad (keyword-only)."""
    for entity_id in (listing_id, lead_id, agent_id):
        if entity_id is not None:
            _registry[entity_id] = agency_id


def lookup(entity_id: str) -> str:
    """Retorna el agency_id para este entity_id.

    Lanza UnregisteredEntityError si el entity_id no fue registrado —
    nunca retorna None ni un default silencioso.
    """
    try:
        return _registry[entity_id]
    except KeyError:
        raise UnregisteredEntityError(
            f"No hay agency_id registrado para el id {entity_id!r}. "
            "Asegúrate de que create_or_get_lead se haya ejecutado antes de "
            "check_agent_availability y book_appointment."
        )


def clear() -> None:
    """Vacía el registry. Úsalo en fixtures de tests para aislar casos."""
    _registry.clear()
