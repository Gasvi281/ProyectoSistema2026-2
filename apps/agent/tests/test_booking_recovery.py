"""Tests para booking_recovery — clasificador de errores y selección de slots."""
import pytest
from agent.booking_recovery import (
    classify_appointment_error,
    nearest_slots,
    format_alternatives,
    alternatives_window,
    UNAVAILABLE, TAKEN, OPEN_VISIT, CLOSED_LEAD, TOO_SOON, UNKNOWN,
    DETAIL_UNAVAILABLE, DETAIL_TAKEN, DETAIL_OPEN_VISIT,
    DETAIL_CLOSED_LEAD, DETAIL_TOO_SOON, DETAIL_PAST,
    _RULES,
    BOGOTA_TZ,
)
from datetime import datetime, timezone, timedelta


# ---------------------------------------------------------------------------
# Tabla de clasificación (item #1): tabledriven sobre las constantes
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("status,substring,expected_category", [
    (409, DETAIL_UNAVAILABLE, UNAVAILABLE),
    (409, DETAIL_TAKEN,       TAKEN),
    (409, DETAIL_OPEN_VISIT,  OPEN_VISIT),
    (409, DETAIL_CLOSED_LEAD, CLOSED_LEAD),
    (422, DETAIL_TOO_SOON,    TOO_SOON),
    (422, DETAIL_PAST,        TOO_SOON),
])
def test_classify_known_errors(status, substring, expected_category):
    """Cada par (status, substring-constant) mapea a la categoría esperada."""
    assert classify_appointment_error(status, substring) == expected_category


@pytest.mark.parametrize("status,detail", [
    (409, "algún otro error no reconocido"),
    (422, "otro error 422 desconocido"),
    (500, "internal server error"),
])
def test_classify_unknown_fallback(status, detail):
    """Cualquier combinación no reconocida → UNKNOWN."""
    assert classify_appointment_error(status, detail) == UNKNOWN


def test_classify_case_insensitive():
    """La comparación de substring es case-insensitive."""
    upper = DETAIL_UNAVAILABLE.upper()
    assert classify_appointment_error(409, upper) == UNAVAILABLE


def test_classify_empty_detail():
    assert classify_appointment_error(409, "") == UNKNOWN
    assert classify_appointment_error(409, None) == UNKNOWN


# ---------------------------------------------------------------------------
# Unicidad: cada substring mapea a exactamente una categoría (item #10)
# ---------------------------------------------------------------------------

def test_each_substring_maps_to_exactly_one_category():
    """Ningún substring constante activa más de una regla."""
    constants = [
        (DETAIL_UNAVAILABLE, 409),
        (DETAIL_TAKEN,       409),
        (DETAIL_OPEN_VISIT,  409),
        (DETAIL_CLOSED_LEAD, 409),
        (DETAIL_TOO_SOON,    422),
        (DETAIL_PAST,        422),
    ]
    for substring, status in constants:
        matches = [
            cat
            for rule_status, rule_sub, cat in _RULES
            if rule_status == status and rule_sub.lower() in substring.lower()
        ]
        assert len(matches) == 1, (
            f"substring {substring!r} (status={status}) debería coincidir con "
            f"exactamente 1 regla, pero coincide con {matches}"
        )


# ---------------------------------------------------------------------------
# nearest_slots — selección y ranking
# ---------------------------------------------------------------------------

# Slots fijos de referencia en UTC.
# Bogotá = UTC-5; "2026-09-10T09:00Z" → "2026-09-10 04:00 Bogotá"
_REQUESTED = "2026-09-10T09:00:00+00:00"  # 04:00 Bogotá día 10

_SLOTS = [
    "2026-09-10T11:00:00+00:00",  # 06:00 Bogotá día 10 — mismo día, 2 h después
    "2026-09-10T08:00:00+00:00",  # 03:00 Bogotá día 10 — mismo día, 1 h antes
    "2026-09-10T14:00:00+00:00",  # 09:00 Bogotá día 10 — mismo día, 5 h después
    "2026-09-11T13:00:00+00:00",  # 08:00 Bogotá día 11 — día siguiente
    "2026-09-11T14:00:00+00:00",  # 09:00 Bogotá día 11 — día siguiente
]


def test_nearest_slots_limit():
    """Retorna a lo sumo `limit` slots."""
    result = nearest_slots(_SLOTS, _REQUESTED, limit=3)
    assert len(result) <= 3


def test_nearest_slots_same_day_preferred():
    """Slots del mismo día Bogotá aparecen antes que los del día siguiente."""
    result = nearest_slots(_SLOTS, _REQUESTED, limit=5)
    same_day = {"2026-09-10T11:00:00+00:00", "2026-09-10T08:00:00+00:00", "2026-09-10T14:00:00+00:00"}
    next_day = {"2026-09-11T13:00:00+00:00", "2026-09-11T14:00:00+00:00"}
    last_same_day_idx = max(i for i, s in enumerate(result) if s in same_day)
    first_next_day_idx = min(i for i, s in enumerate(result) if s in next_day)
    assert last_same_day_idx < first_next_day_idx, (
        "Algún slot del día siguiente aparece antes que el último del mismo día"
    )


def test_nearest_slots_ordered_by_proximity_within_day():
    """Dentro del mismo día Bogotá, ordenados por distancia al horario pedido."""
    result = nearest_slots(_SLOTS, _REQUESTED, limit=3)
    # 08:00 UTC = 1h antes (dist 1h), 11:00 UTC = 2h después (dist 2h)
    same_day_results = [s for s in result if s.startswith("2026-09-10")]
    assert same_day_results[0] == "2026-09-10T08:00:00+00:00"   # dist 1h
    assert same_day_results[1] == "2026-09-10T11:00:00+00:00"   # dist 2h


def test_nearest_slots_later_only():
    """`later_only=True` excluye slots anteriores al horario pedido."""
    result = nearest_slots(_SLOTS, _REQUESTED, limit=5, later_only=True)
    requested_dt = datetime.fromisoformat(_REQUESTED)
    for iso in result:
        slot_dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        assert slot_dt > requested_dt, f"Slot {iso} no es posterior al pedido"


def test_nearest_slots_empty_input():
    """Lista vacía de entrada → lista vacía de salida."""
    assert nearest_slots([], _REQUESTED) == []


def test_nearest_slots_skips_past_bogota_days():
    """Slots anteriores al día Bogotá del pedido no se proponen."""
    past_slot = "2026-09-09T10:00:00+00:00"  # día anterior en Bogotá
    result = nearest_slots([past_slot], _REQUESTED)
    assert result == []


# ---------------------------------------------------------------------------
# Conversión de zona horaria: caso crítico — medianoche Bogotá
# ---------------------------------------------------------------------------

def test_midnight_bogota_grouping():
    """Un slot a las 02:00 UTC = 21:00 Bogotá día anterior — agrupa con ese día.

    requested_at = 2026-09-10T02:00Z = 2026-09-09 21:00 Bogotá (día 9).
    Un slot a las 2026-09-10T01:00Z = 2026-09-09 20:00 Bogotá → mismo día que el pedido.
    Un slot a las 2026-09-10T05:30Z = 2026-09-10 00:30 Bogotá → día siguiente.
    """
    requested = "2026-09-10T02:00:00+00:00"   # 21:00 Bogotá día 9
    slot_same_day = "2026-09-10T01:00:00+00:00"  # 20:00 Bogotá día 9 — mismo día
    slot_next_day = "2026-09-10T05:30:00+00:00"  # 00:30 Bogotá día 10 — día siguiente

    result = nearest_slots([slot_same_day, slot_next_day], requested, limit=2)
    # El del mismo día Bogotá debe aparecer primero
    assert result[0] == slot_same_day


# ---------------------------------------------------------------------------
# format_alternatives
# ---------------------------------------------------------------------------

def test_format_alternatives_shape():
    """Retorna dicts con las claves scheduled_at y display."""
    slots = ["2026-09-10T14:00:00+00:00"]
    result = format_alternatives(slots)
    assert len(result) == 1
    assert "scheduled_at" in result[0]
    assert "display" in result[0]
    assert result[0]["scheduled_at"] == slots[0]


def test_format_alternatives_display_bogota():
    """El campo display refleja la hora Bogotá (UTC-5)."""
    # 14:00 UTC = 09:00 Bogotá
    slots = ["2026-09-10T14:00:00+00:00"]
    result = format_alternatives(slots)
    assert "09:00" in result[0]["display"]
    assert "Bogotá" in result[0]["display"]


def test_format_alternatives_empty():
    assert format_alternatives([]) == []


# ---------------------------------------------------------------------------
# alternatives_window
# ---------------------------------------------------------------------------

def test_alternatives_window_starts_at_bogota_day_start():
    """date_from debe ser el inicio del día Bogotá en UTC."""
    # 2026-09-10T09:00Z = 2026-09-10T04:00 Bogotá → inicio del día Bogotá = 2026-09-10T00:00 Bogotá = 2026-09-10T05:00Z
    date_from, date_to = alternatives_window("2026-09-10T09:00:00+00:00")
    from_dt = datetime.fromisoformat(date_from)
    bogota_from = from_dt.astimezone(BOGOTA_TZ)
    assert bogota_from.hour == 0 and bogota_from.minute == 0 and bogota_from.second == 0


def test_alternatives_window_span():
    """date_to está exactamente `days` días después de date_from."""
    date_from, date_to = alternatives_window("2026-09-10T09:00:00+00:00", days=7)
    from_dt = datetime.fromisoformat(date_from)
    to_dt   = datetime.fromisoformat(date_to)
    assert to_dt - from_dt == timedelta(days=7)


def test_alternatives_window_midnight_bogota():
    """Caso de borde: requested straddling medianoche Bogotá."""
    # 02:00 UTC = 21:00 Bogotá día 9 → inicio del día = 2026-09-09T00:00 Bogotá = 2026-09-09T05:00Z
    date_from, _ = alternatives_window("2026-09-10T02:00:00+00:00")
    from_dt = datetime.fromisoformat(date_from)
    bogota_from = from_dt.astimezone(BOGOTA_TZ)
    assert bogota_from.date().isoformat() == "2026-09-09"
