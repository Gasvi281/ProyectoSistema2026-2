"""LangChain tools for property search, Q&A, availability, scheduling."""
import logging
import re
from typing import Optional
from pydantic import BaseModel, Field, field_validator
from langchain.tools import tool
from datetime import datetime

logger = logging.getLogger(__name__)

class SearchInput(BaseModel):
    location: Optional[str] = Field(None, description="Ciudad o barrio (ej. 'Laureles', 'Medellín')")
    min_price: Optional[int] = Field(None, description="Precio mínimo en COP")
    max_price: Optional[int] = Field(None, description="Precio máximo en COP")
    min_bedrooms: Optional[int] = Field(None, description="Número mínimo de habitaciones")
    max_bedrooms: Optional[int] = Field(None, description="Número máximo de habitaciones")
    property_type: Optional[str] = Field(None, description="Tipo de inmueble: APARTMENT, HOUSE, STUDIO, COUNTRY_HOUSE")
    operation_type: Optional[str] = Field(None, description="Operación: SALE (comprar/venta) o RENT (arrendar/arriendo)")

class PropertyQAInput(BaseModel):
    property_id: str = Field(..., description="Property ID")
    question: str = Field(..., description="Question about property")

class AvailabilityInput(BaseModel):
    property_id: str = Field(..., description="Property ID")
    start_date: str = Field(..., description="Start date YYYY-MM-DD")
    end_date: str = Field(..., description="End date YYYY-MM-DD")

class ScheduleInput(BaseModel):
    property_id: str = Field(..., description="Property ID")
    client_id: str = Field(..., description="Client ID")
    slot_id: str = Field(..., description="Slot ID")

class LikePropertyInput(BaseModel):
    client_id: str = Field(..., description="Client ID")
    property_id: str = Field(..., description="Property ID")

_UUID_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
    re.IGNORECASE,
)


class RequestVisitInput(BaseModel):
    client_id: str = Field(..., description="Client ID — usa el que aparece al inicio del mensaje del sistema, nunca lo inventes")
    property_description: str = Field(
        ...,
        description=(
            "Descripción del inmueble en las propias palabras del cliente "
            "(ubicación, tipo, lo que haya mencionado). "
            "NO incluyas un UUID aquí — si tienes un listing_id real, usa el flujo "
            "create_or_get_lead → check_agent_availability → book_appointment."
        ),
    )
    preferred_datetime: Optional[datetime] = Field(
        None,
        description=(
            "Fecha y hora preferida en formato ISO 8601 con zona horaria "
            "(ej. '2026-09-10T14:00:00-05:00'). "
            "Pasa None cuando el cliente sea flexible o diga 'lo antes posible' — "
            "NUNCA inventes una fecha ni uses texto libre."
        ),
    )

    @field_validator("property_description")
    @classmethod
    def no_uuid_in_description(cls, v: str) -> str:
        if _UUID_RE.search(v):
            raise ValueError(
                "property_description contiene un UUID. "
                "Si tienes un listing_id real, usa el flujo estructurado: "
                "create_or_get_lead(client_id, listing_id) → "
                "check_agent_availability → book_appointment. "
                "request_visit es solo para cuando NO tienes un listing_id."
            )
        return v

class AgentAvailabilityInput(BaseModel):
    agent_id: str = Field(..., description="ID del agente inmobiliario cuya disponibilidad se quiere consultar")
    date_from: str = Field(..., description="Inicio del rango a consultar — ISO 8601 con zona horaria, ej. '2026-09-10T00:00:00+00:00'")
    date_to: str = Field(..., description="Fin del rango a consultar — ISO 8601 con zona horaria, ej. '2026-09-17T23:59:59+00:00'")

class CreateLeadInput(BaseModel):
    client_id: str = Field(..., description="Client ID — usa el que aparece al inicio del mensaje del sistema, nunca lo inventes")
    listing_id: str = Field(..., description="ID del listing/propiedad del backend por el que el cliente muestra interés")

class BookAppointmentInput(BaseModel):
    lead_id: str = Field(..., description="ID del lead/cliente — usa el que aparece al inicio del mensaje del sistema, nunca lo inventes")
    scheduled_at: str = Field(..., description="Fecha/hora del slot elegido — ISO 8601 con zona horaria, ej. '2026-09-10T09:00:00+00:00'. Debe ser un slot real obtenido de check_agent_availability, nunca inventado")
    duration_min: int = Field(30, description="Duración de la visita en minutos (default 30, igual a slot_minutes del backend)")
    agent_id: Optional[str] = Field(None, description="ID del agente inmobiliario — obtenido de create_or_get_lead; requerido para proponer alternativas si el slot no está disponible")

@tool(args_schema=SearchInput)
async def search_properties(location=None, min_price=None, max_price=None, min_bedrooms=None, max_bedrooms=None, property_type=None, operation_type=None):
    """Busca propiedades en el catálogo usando lenguaje natural.

    Devuelve un dict con:
    - `results`: lista de propiedades con sus `id` internos (úsalos en create_or_get_lead).
    - `summary`: lista numerada legible para el cliente — SIN UUIDs.
    - `count`: 0 si no hay coincidencias — NUNCA inventes propiedades.

    Cuando el cliente elija una propiedad (por número o nombre), resuelve su `id`
    desde `results` y pásalo a create_or_get_lead. Nunca muestres ni inventes el `id`."""
    import httpx
    from agent.types import SearchFilters
    from agent.listing_search import get_listing_search_provider

    provider = get_listing_search_provider()
    filters = SearchFilters(
        location=location,
        min_price=min_price,
        max_price=max_price,
        min_bedrooms=min_bedrooms,
        max_bedrooms=max_bedrooms,
        property_type=property_type,
        operation_type=operation_type,
    )

    try:
        props = await provider.search(filters, limit=5)
    except httpx.HTTPStatusError as e:
        http_code = e.response.status_code
        if http_code in (400, 401, 403):
            return {
                "results": [], "count": 0, "summary": "",
                "error": f"Error de autenticación ({http_code}) al buscar propiedades.",
                "error_code": http_code, "code": "BACKEND_AUTH_ERROR",
            }
        return {
            "results": [], "count": 0, "summary": "",
            "error": f"Error del servidor ({http_code}) al buscar propiedades.",
            "error_code": http_code, "code": "BACKEND_UNAVAILABLE",
        }
    except httpx.TransportError as e:
        return {
            "results": [], "count": 0, "summary": "",
            "error": str(e), "error_code": None, "code": "BACKEND_UNAVAILABLE",
        }
    except Exception as e:
        return {
            "results": [], "count": 0, "summary": "",
            "error": str(e), "error_code": None,
        }

    if not props:
        return {"results": [], "count": 0, "summary": "", "error": None, "error_code": None}

    _op_es = {"SALE": "venta", "RENT": "arriendo"}
    results = []
    summary_lines = []
    for n, prop in enumerate(props, 1):
        op_label = _op_es.get(prop.operation_type or "", prop.operation_type or "")
        results.append({
            "n": n,
            "id": prop.id,
            "name": prop.name,
            "location": prop.location,
            "price": prop.price,
            "bedrooms": prop.bedrooms,
            "operation_type": prop.operation_type,
        })
        line = f"{n}. {prop.name} — {prop.location} — ${prop.price:,} COP — {prop.bedrooms} hab"
        if op_label:
            line += f" — {op_label}"
        summary_lines.append(line)

    return {
        "results": results,
        "count": len(results),
        "summary": "\n".join(summary_lines),
        "error": None,
        "error_code": None,
    }

@tool(args_schema=PropertyQAInput)
async def answer_property_question(property_id, question):
    """Responde preguntas sobre una propiedad del catálogo.

    Usa el `id` de los `results` de search_properties — nunca un UUID inventado.
    Solo cita datos del registro; admite cuando la información no está disponible.
    Retorna un dict con `answer` en éxito, o `code` en error."""
    import httpx
    from agent.listing_search import get_listing_search_provider

    provider = get_listing_search_provider()

    try:
        prop = await provider.get_listing(property_id)
    except httpx.HTTPStatusError as e:
        http_code = e.response.status_code
        if http_code in (400, 401, 403):
            return {"answer": None, "error": f"Error de autenticación ({http_code}).", "error_code": http_code, "code": "BACKEND_AUTH_ERROR"}
        return {"answer": None, "error": f"Error del servidor ({http_code}).", "error_code": http_code, "code": "BACKEND_UNAVAILABLE"}
    except httpx.TransportError as e:
        return {"answer": None, "error": str(e), "error_code": None, "code": "BACKEND_UNAVAILABLE"}
    except Exception as e:
        return {"answer": None, "error": str(e), "error_code": None}

    if prop is None:
        return {
            "answer": None,
            "error": f"La propiedad {property_id!r} no fue encontrada o no está disponible.",
            "error_code": None,
            "code": "UNKNOWN_LISTING",
        }

    q = question.lower()
    _op_es = {"SALE": "En venta", "RENT": "En arriendo"}
    if "precio" in q or "price" in q or "costo" in q or "valor" in q:
        answer = f"${prop.price:,} COP"
    elif "área" in q or "area" in q or "tamaño" in q or "size" in q or "metros" in q or "m2" in q:
        answer = f"{prop.area_sqm} m²"
    elif "hab" in q or "cuart" in q or "bed" in q or "dormit" in q:
        answer = f"{prop.bedrooms} habitaciones"
    elif "baño" in q or "bath" in q:
        answer = f"{prop.bathrooms} baños"
    elif "barrio" in q or "sector" in q or "ubicación" in q or "location" in q:
        answer = prop.location
    elif "tipo" in q or "type" in q:
        answer = prop.property_type
    elif "venta" in q or "arriendo" in q or "operación" in q or "rent" in q or "sale" in q:
        answer = _op_es.get(prop.operation_type or "", prop.operation_type or "No especificado")
    else:
        op = _op_es.get(prop.operation_type or "", "")
        answer = (
            f"{prop.name}: ${prop.price:,} COP | {prop.bedrooms} hab {prop.bathrooms} baños "
            f"{prop.area_sqm} m² | {prop.location}" + (f" | {op}" if op else "")
        )

    return {"answer": answer, "error": None, "error_code": None}

@tool(args_schema=AvailabilityInput)
def check_availability(property_id, start_date, end_date):
    """List available visit slots. Only genuine slots, no invention."""
    from agent.fakes import FakeAvailability
    try:
        start = datetime.fromisoformat(start_date)
        end = datetime.fromisoformat(end_date)
    except:
        return "Invalid date format, use YYYY-MM-DD."
    
    availability = FakeAvailability()
    slots = [s for s in availability.slots.values() if s.property_id == property_id and start <= s.start_time <= end]
    
    if not slots:
        return f"No slots available {start_date} to {end_date}. Try different dates."
    
    result = f"Available slots for {property_id}:\n"
    for slot in sorted(slots, key=lambda s: s.start_time)[:10]:
        result += f"- {slot.start_time.strftime('%a %b %d %H:%M')} (ID: {slot.slot_id})\n"
    return result

@tool(args_schema=ScheduleInput)
async def schedule_meeting(property_id, client_id, slot_id):
    """Schedule visit. Creates pending_confirmation appointment."""
    from agent.fakes import FakeAvailability, FakeBooking
    from agent.notifications import get_notifications_provider

    availability = FakeAvailability()
    booking = FakeBooking()

    slot = availability.slots.get(slot_id)
    if not slot or slot.property_id != property_id:
        return f"Slot {slot_id} invalid for this property."

    appt = await booking.create_appointment(property_id, client_id, slot_id, "Via assistant")
    time_str = slot.start_time.strftime("%a %b %d %H:%M")

    # Avisamos al agente humano por correo (o al fake, según NOTIFICATIONS_MODE).
    # Si el envío falla, no tumbamos la reserva — el cliente ya tiene su cita
    # guardada, solo se pierde el aviso automático y toca darse cuenta manualmente.
    try:
        notifications = get_notifications_provider()
        await notifications.notify_agent_appointment(appt.id, property_id, client_id)
    except Exception as e:
        print(f"[schedule_meeting] No se pudo notificar al agente: {e}")

    return f"Appointment scheduled for {time_str}. ID: {appt.id}. Status: pending_confirmation. Agent will confirm soon."

@tool(args_schema=LikePropertyInput)
async def save_liked_property(client_id, property_id):
    """Record client's interest in property."""
    from agent.fakes import FakeConversationStore
    store = FakeConversationStore()
    await store.record_liked_property(client_id, property_id)
    return f"Saved {property_id} to your preferences."

@tool(args_schema=RequestVisitInput)
async def request_visit(client_id, property_description, preferred_datetime):
    """Solicita una visita directamente al agente humano por correo, SIN consultar
    el catálogo ni la disponibilidad real. SOLO usar cuando NO se tiene un
    listing_id real (catálogo desconectado o propiedad no encontrada en búsqueda).
    Si ya tienes un listing_id, usa siempre el flujo completo:
    create_or_get_lead → check_agent_availability → book_appointment.
    NUNCA uses request_visit como fallback cuando esos tools fallen —
    si create_or_get_lead devuelve code='BACKEND_UNAVAILABLE' o
    code='BACKEND_AUTH_ERROR', informa al cliente del problema técnico y
    dile que un agente lo contactará pronto; no llames request_visit.
    No inventes client_id — usa el del contexto del sistema."""
    import os
    import uuid
    from agent.notifications import send_manual_visit_request

    appointment_id = f"manual-{uuid.uuid4().hex[:8]}"

    # preferred_datetime es Optional[datetime]; serializar a str para la notificación.
    dt_str = preferred_datetime.isoformat() if preferred_datetime is not None else "flexible/lo antes posible"

    try:
        ok = await send_manual_visit_request(
            appointment_id, client_id, property_description, dt_str
        )
    except Exception as e:
        print(f"[request_visit] No se pudo notificar al agente: {e}")
        return "Tuve un problema enviando tu solicitud, intenta de nuevo en un momento."

    if not ok:
        return "No pude enviar la solicitud en este momento, pero tu interés quedó registrado. Intenta de nuevo más tarde."

    # El aviso real solo sale cuando NOTIFICATIONS_MODE=email. En modo fake,
    # send_manual_visit_request solo imprime en consola — no llega nada a ningún
    # agente humano. Usamos el mismo criterio que esa función para decidir
    # qué mensaje es honesto devolver.
    if os.getenv("NOTIFICATIONS_MODE", "fake").lower() == "email":
        return (
            f"Listo, envié tu solicitud de visita al agente inmobiliario. "
            f"Te contactará pronto para confirmar disponibilidad. "
            f"ID de referencia: {appointment_id}"
        )
    return (
        f"Registré tu solicitud de visita (entorno de prueba: todavía no se "
        f"envió un aviso real a un agente). ID de referencia: {appointment_id}"
    )

@tool(args_schema=CreateLeadInput)
async def create_or_get_lead(client_id, listing_id):
    """Crea u obtiene el lead del backend para este cliente y listing. Devuelve el
    lead con su agent_id derivado (úsalo para check_agent_availability) y su id
    (úsalo como lead_id para book_appointment). Úsala antes de agendar una visita.
    No inventes client_id ni listing_id — usa solo valores confirmados en la conversación."""
    import httpx
    from agent.leads import get_lead_provider
    from agent.listing_agency_resolver import get_listing_agency_resolver_provider
    from agent import agency_registry
    from agent.fakes import UnknownListingError

    # Resolver listing_id → agency_id antes de llamar al backend, de modo que
    # HttpLead pueda incluir X-Agency-Id en POST /leads.
    # Cada rama de error retorna inmediatamente con un `code` legible por el LLM;
    # si llegamos al bloque de provider, agency_id es siempre un str válido.
    resolver = get_listing_agency_resolver_provider()
    try:
        agency_id: str = await resolver.resolve(listing_id)
        agency_registry.register(listing_id=listing_id, agency_id=agency_id)
    except UnknownListingError:
        # 404/422 del resolver: listing inexistente o fuera de la agencia del bot.
        return {
            "client_id": client_id,
            "listing_id": listing_id,
            "error": (
                f"El listing {listing_id!r} no existe o no está disponible "
                f"bajo la agencia del bot. Verifica que el listing_id sea correcto."
            ),
            "error_code": None,
            "code": "UNKNOWN_LISTING",
        }
    except httpx.HTTPStatusError as e:
        http_code = e.response.status_code
        if http_code in (400, 401, 403):
            code_str = "BACKEND_AUTH_ERROR"
            msg = f"Error de autenticación ({http_code}) al validar el listing."
        else:
            code_str = "BACKEND_UNAVAILABLE"
            msg = f"Error del servidor ({http_code}) al validar el listing."
        return {
            "client_id": client_id,
            "listing_id": listing_id,
            "error": msg,
            "error_code": http_code,
            "code": code_str,
        }
    except httpx.TransportError as e:
        # ConnectError, ReadTimeout, u otro error de transporte del resolver.
        return {
            "client_id": client_id,
            "listing_id": listing_id,
            "error": str(e),
            "error_code": None,
            "code": "BACKEND_UNAVAILABLE",
        }
    except Exception as e:
        # Error no categorizado del resolver — no agregar `code` para no
        # prometer más de lo que sabemos.
        return {
            "client_id": client_id,
            "listing_id": listing_id,
            "error": str(e),
            "error_code": None,
        }

    provider = get_lead_provider()
    try:
        result = await provider.create_or_get_lead(client_id, listing_id, "TELEGRAM")
        # agency_id es siempre str aquí (todas las ramas de fallo retornaron arriba).
        agency_registry.register(
            lead_id=result["id"],
            agent_id=result["agent_id"],
            agency_id=agency_id,
        )
        return {**result, "error": None, "error_code": None}
    except httpx.HTTPStatusError as e:
        code = e.response.status_code
        if code == 422:
            msg = "client_id o listing_id inválido (no existe en el backend)."
        else:
            msg = f"Error del servidor ({code}) al crear el lead."
        return {"client_id": client_id, "listing_id": listing_id, "error": msg, "error_code": code}
    except Exception as e:
        return {"client_id": client_id, "listing_id": listing_id, "error": str(e), "error_code": None}


@tool(args_schema=AgentAvailabilityInput)
async def check_agent_availability(agent_id, date_from, date_to):
    """Consulta los slots disponibles de un agente inmobiliario entre dos fechas.
    Solo retorna slots reales; si no hay ninguno retorna lista vacía — nunca inventa horarios."""
    from agent import agency_registry
    if not agency_registry.is_registered(agent_id):
        return {
            "agent_id": agent_id,
            "slots": [],
            "error": (
                "No tengo un agente válido para consultar disponibilidad. "
                "Ejecuta primero create_or_get_lead(client_id, listing_id) "
                "y usa el agent_id que devuelve."
            ),
            "error_code": None,
            "code": "BOT_AGENT_NOT_REGISTERED",
        }
    from agent.agent_slots import get_agent_slots_provider
    provider = get_agent_slots_provider()
    try:
        result = await provider.list_agent_slots(agent_id, date_from, date_to)
        return {**result, "error": None}
    except Exception as e:
        return {"agent_id": agent_id, "slots": [], "error": str(e)}


@tool(args_schema=BookAppointmentInput)
async def book_appointment(lead_id, scheduled_at, duration_min=30, agent_id=None):
    """Agenda una visita a una propiedad usando un slot real obtenido de check_agent_availability.
    Nunca inventes scheduled_at ni lead_id — usa solo valores confirmados en la conversación.
    Incluye agent_id (del resultado de create_or_get_lead) para que, en caso de conflicto,
    el tool pueda proponer los horarios alternativos más cercanos automáticamente."""
    import httpx
    from agent.booking import get_appointment_booking_provider
    from agent.booking_recovery import (
        classify_appointment_error,
        nearest_slots,
        format_alternatives,
        alternatives_window,
        UNAVAILABLE, TAKEN, TOO_SOON, OPEN_VISIT, CLOSED_LEAD, UNKNOWN,
    )
    from agent import agency_registry
    if not agency_registry.is_registered(lead_id):
        return {
            "lead_id": lead_id,
            "scheduled_at": scheduled_at,
            "error": (
                "No tengo un lead válido para agendar. "
                "Ejecuta primero create_or_get_lead(client_id, listing_id), "
                "luego check_agent_availability, y finalmente book_appointment."
            ),
            "error_code": None,
            "code": "BOT_LEAD_NOT_REGISTERED",
            "category": UNKNOWN,
            "alternatives": [],
        }

    provider = get_appointment_booking_provider()
    try:
        result = await provider.book(lead_id, scheduled_at, duration_min)
        # Añadimos scheduled_at_local (hora Bogotá) para que el mensaje de confirmación
        # al cliente use hora local. El campo scheduled_at (UTC) sigue siendo la fuente
        # de verdad para integraciones — no lo reemplazamos.
        from agent.agent_slots import _to_local
        try:
            local_str = _to_local(scheduled_at)
        except Exception:
            local_str = None
        return {**result, "error": None, "error_code": None, "scheduled_at_local": local_str}
    except httpx.HTTPStatusError as e:
        code = e.response.status_code
        # Extraer detail del cuerpo JSON; si no es JSON, usar cadena vacía.
        try:
            detail = e.response.json().get("detail", "")
        except Exception:
            detail = ""

        category = classify_appointment_error(code, detail)

        if category == UNKNOWN:
            logger.warning(
                "book_appointment: error no reconocido — status=%d detail=%r",
                code, detail,
            )
            msg = "No se pudo completar el agendamiento. Por favor intenta de nuevo más tarde."
            return {
                "lead_id": lead_id, "scheduled_at": scheduled_at,
                "error": msg, "error_code": code,
                "category": category, "alternatives": [],
            }

        if category in (OPEN_VISIT, CLOSED_LEAD):
            if category == OPEN_VISIT:
                msg = "Este inmueble ya tiene una visita abierta en progreso. No es posible agendar otra en este momento."
            else:
                msg = "El lead asociado a esta solicitud está cerrado. No es posible agendar una nueva visita."
            return {
                "lead_id": lead_id, "scheduled_at": scheduled_at,
                "error": msg, "error_code": code,
                "category": category, "alternatives": [],
            }

        # Categorías con alternativas: unavailable, taken, too_soon
        later_only = (category == TOO_SOON)

        if not agent_id:
            # Sin agent_id no podemos consultar slots — devolver mensaje seguro.
            msg = (
                "El horario solicitado no está disponible. "
                "Consulta check_agent_availability para elegir un horario libre."
            )
            return {
                "lead_id": lead_id, "scheduled_at": scheduled_at,
                "error": msg, "error_code": code,
                "category": category, "alternatives": [],
            }

        # Intentar obtener alternativas.
        try:
            from agent.agent_slots import get_agent_slots_provider
            date_from, date_to = alternatives_window(scheduled_at)
            slots_result = await get_agent_slots_provider().list_agent_slots(
                agent_id, date_from, date_to
            )
            slot_starts = [s["start"] for s in slots_result.get("slots", [])]
            nearest = nearest_slots(slot_starts, scheduled_at, limit=3, later_only=later_only)
            alternatives = format_alternatives(nearest)
        except Exception as fetch_err:
            logger.warning("book_appointment: no se pudieron obtener alternativas — %s", fetch_err)
            msg = (
                "El horario solicitado no está disponible y no fue posible "
                "cargar horarios alternativos. Intenta consultar check_agent_availability."
            )
            return {
                "lead_id": lead_id, "scheduled_at": scheduled_at,
                "error": msg, "error_code": code,
                "category": category, "alternatives": [],
            }

        if alternatives:
            slots_text = "; ".join(a["display"] for a in alternatives)
            msg = (
                f"El horario solicitado no está disponible. "
                f"Estos son los horarios más cercanos disponibles: {slots_text}. "
                f"¿Cuál prefieres?"
            )
        else:
            msg = (
                "El horario solicitado no está disponible y no hay horarios "
                "alternativos en los próximos 7 días. "
                "Consulta check_agent_availability para un rango distinto."
            )

        return {
            "lead_id": lead_id, "scheduled_at": scheduled_at,
            "error": msg, "error_code": code,
            "category": category, "alternatives": alternatives,
        }

    except Exception as e:
        return {
            "lead_id": lead_id, "scheduled_at": scheduled_at,
            "error": str(e), "error_code": None,
            "category": UNKNOWN, "alternatives": [],
        }


def get_tools():
    """Retorna los tools activos del agente.

    check_availability y schedule_meeting son la generación anterior (fake hardcodeado,
    sin endpoint http real). Fueron retirados en Sprint 3 para que el LLM use
    exclusivamente la ruta http real de HU-22:
      create_or_get_lead → check_agent_availability → book_appointment
    Las definiciones de función se mantienen como código muerto (deuda de limpieza).
    """
    return [
        search_properties,
        answer_property_question,
        save_liked_property,
        request_visit,
        create_or_get_lead,
        check_agent_availability,
        book_appointment,
    ]
