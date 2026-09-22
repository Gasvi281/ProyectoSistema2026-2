"""
booking_recovery.py
-------------------
Clasificación de errores de agendamiento y selección de slots alternativos.

Uso principal: `book_appointment` en tools_langchain.py llama a
`classify_appointment_error` cuando el backend devuelve un error, y a
`nearest_slots` / `format_alternatives` para construir la lista de horarios
que se propone al cliente.

Todos los helpers son puros (sin I/O, sin estado) y se pueden testear en
aislamiento sin levantar el backend ni las dependencias del agente.
"""

import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Zona horaria local de negocio
# ---------------------------------------------------------------------------

BOGOTA_TZ = ZoneInfo("America/Bogota")   # UTC-5, sin DST

# ---------------------------------------------------------------------------
# Categorías de error
# ---------------------------------------------------------------------------

UNAVAILABLE  = "unavailable"    # fuera de la disponibilidad publicada del agente
TAKEN        = "taken"          # ya existe una cita en ese bloque
OPEN_VISIT   = "open_visit"     # visita abierta (cualquier otro slot tendrá mismo 409)
CLOSED_LEAD  = "closed_lead"    # lead cerrado — no proponer alternativas
TOO_SOON     = "too_soon"       # violación de antelación mínima / fecha en el pasado
UNKNOWN      = "unknown"        # cualquier otro error — mensaje seguro, sin causa inventada

# ---------------------------------------------------------------------------
# Substrings del campo `detail` de la HTTPException del backend
# (POST /leads/{lead_id}/appointments)
#
# MUST-FILL: reemplazar cada TODO con el substring verificado de appointment.py
# antes de hacer merge. Pegar el texto exacto (case-insensitive en el matcher).
# ---------------------------------------------------------------------------

DETAIL_UNAVAILABLE = "published availability"              # appointment.py:164-168; test_visit_rules.py:108 — TODO(migrate-to-code): OUTSIDE_PUBLISHED_SLOTS
DETAIL_TAKEN       = "overlapping that slot"              # appointment.py:122-127 — TODO(migrate-to-code): AGENT_OVERLAP
DETAIL_OPEN_VISIT  = "open visit"                         # appointment.py:285-290 — TODO(migrate-to-code): LEAD_HAS_OPEN_VISIT
DETAIL_CLOSED_LEAD = "closed lead"                        # appointment.py:262-265 — TODO(migrate-to-code): LEAD_CLOSED
DETAIL_TOO_SOON    = "ahead"                              # appointment.py:137-146; test_visit_rules.py:104-105 — TODO(migrate-to-code): NOTICE_TOO_SHORT
DETAIL_PAST        = "scheduled_at must be in the future" # appointment.py:266-269 — TODO(migrate-to-code): PAST_SLOT

# Tabla de clasificación: (status, substring) → categoría.
# El orden importa: se evalúa de arriba hacia abajo y se retorna el primer match.
_RULES: list[tuple[int, str, str]] = [
    (409, DETAIL_UNAVAILABLE, UNAVAILABLE),
    (409, DETAIL_TAKEN,       TAKEN),
    (409, DETAIL_OPEN_VISIT,  OPEN_VISIT),
    (409, DETAIL_CLOSED_LEAD, CLOSED_LEAD),
    (422, DETAIL_TOO_SOON,    TOO_SOON),
    (422, DETAIL_PAST,        TOO_SOON),
]


# ---------------------------------------------------------------------------
# Clasificador
# ---------------------------------------------------------------------------

def classify_appointment_error(status: int, detail: str) -> str:
    """Clasifica un error de POST /leads/{id}/appointments por (status, detail).

    Realiza comparación de substring case-insensitive. Cualquier combinación
    no reconocida → UNKNOWN.

    Args:
        status: código HTTP (ej. 409, 422).
        detail: valor del campo ``detail`` del cuerpo de la HTTPException.

    Returns:
        Una de las constantes de categoría definidas en este módulo.
    """
    detail_lower = (detail or "").lower()
    for rule_status, rule_substring, category in _RULES:
        if status == rule_status and rule_substring.lower() in detail_lower:
            return category
    if status not in (409, 422):
        logger.warning(
            "classify_appointment_error: código HTTP inesperado %d | detail: %r",
            status, detail,
        )
    return UNKNOWN


# ---------------------------------------------------------------------------
# Selección de slots alternativos
# ---------------------------------------------------------------------------

def _parse_utc(iso: str) -> datetime:
    """Parsea ISO 8601 (con posible sufijo 'Z') → datetime UTC aware."""
    return datetime.fromisoformat(iso.replace("Z", "+00:00"))


def nearest_slots(
    slot_starts_utc: list[str],
    requested_at_utc: str,
    limit: int = 3,
    later_only: bool = False,
) -> list[str]:
    """Devuelve hasta `limit` slots UTC más cercanos al horario pedido.

    Ranking:
    1. Slots del mismo día de calendario en Bogotá que `requested_at_utc`.
    2. Slots de los días siguientes (en orden cronológico).
    Dentro de cada grupo, orden por distancia absoluta al horario pedido.

    Args:
        slot_starts_utc:  lista de strings ISO 8601 (inicio de cada slot).
        requested_at_utc: horario solicitado (ISO 8601, puede llevar 'Z').
        limit:            máximo de slots a retornar (default 3).
        later_only:       si True, excluye slots <= requested_at (para too_soon).

    Returns:
        Lista de strings UTC ISO de los slots seleccionados (≤ limit).
    """
    requested_dt = _parse_utc(requested_at_utc)
    requested_bogota = requested_dt.astimezone(BOGOTA_TZ)
    requested_day   = requested_bogota.date()

    candidates: list[tuple[int, timedelta, str]] = []
    # group: 0 = mismo día en Bogotá, 1 = días siguientes
    for iso in slot_starts_utc:
        try:
            slot_dt = _parse_utc(iso)
        except (ValueError, TypeError):
            continue

        if later_only and slot_dt <= requested_dt:
            continue

        slot_bogota = slot_dt.astimezone(BOGOTA_TZ)
        slot_day    = slot_bogota.date()

        if slot_day == requested_day:
            group = 0
        elif slot_day > requested_day:
            group = 1
        else:
            # Día pasado en Bogotá — no proponer
            continue

        distance = abs(slot_dt - requested_dt)
        candidates.append((group, distance, iso))

    candidates.sort(key=lambda t: (t[0], t[1]))
    return [iso for _, _, iso in candidates[:limit]]


def format_alternatives(utc_iso_list: list[str]) -> list[dict]:
    """Convierte una lista de slots UTC en dicts con display en hora Bogotá.

    Args:
        utc_iso_list: strings ISO 8601 en UTC.

    Returns:
        [{"scheduled_at": <UTC ISO>, "display": <hora Bogotá, legible>}]
        La representación legible usa el formato "DD/MM/YYYY HH:MM (hora Bogotá)".
    """
    result = []
    for iso in utc_iso_list:
        try:
            dt_utc = _parse_utc(iso)
        except (ValueError, TypeError):
            continue
        dt_bogota = dt_utc.astimezone(BOGOTA_TZ)
        display = dt_bogota.strftime("%d/%m/%Y %H:%M") + " (hora Bogotá)"
        result.append({"scheduled_at": iso, "display": display})
    return result


# ---------------------------------------------------------------------------
# Ventana de búsqueda de alternativos
# ---------------------------------------------------------------------------

def alternatives_window(requested_at_utc: str, days: int = 7) -> tuple[str, str]:
    """Devuelve (date_from, date_to) en UTC ISO para la ventana de búsqueda.

    ``date_from`` = inicio del día Bogotá que contiene ``requested_at_utc``.
    ``date_to``   = ``date_from`` + ``days`` días.

    Args:
        requested_at_utc: horario solicitado (ISO 8601, puede llevar 'Z').
        days:             ancho de la ventana en días (default 7).

    Returns:
        Tupla (from_iso, to_iso) en UTC con offset explícito.
    """
    requested_dt   = _parse_utc(requested_at_utc)
    requested_local = requested_dt.astimezone(BOGOTA_TZ)

    # Inicio del día Bogotá → convertir a UTC
    day_start_local = requested_local.replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    day_start_utc = day_start_local.astimezone(timezone.utc)
    day_end_utc   = day_start_utc + timedelta(days=days)

    return day_start_utc.isoformat(), day_end_utc.isoformat()
