"""LangChain tools for property search, Q&A, availability, scheduling."""
from typing import Optional
from pydantic import BaseModel, Field
from langchain.tools import tool
from datetime import datetime

class SearchInput(BaseModel):
    location: Optional[str] = Field(None, description="City or neighborhood")
    min_price: Optional[int] = Field(None, description="Min price in COP")
    max_price: Optional[int] = Field(None, description="Max price in COP")
    min_bedrooms: Optional[int] = Field(None, description="Min bedrooms")
    max_bedrooms: Optional[int] = Field(None, description="Max bedrooms")
    property_type: Optional[str] = Field(None, description="apartment, house, or commercial")

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

class RequestVisitInput(BaseModel):
    client_id: str = Field(..., description="Client ID — usa el que aparece al inicio del mensaje del sistema, nunca lo inventes")
    property_description: str = Field(..., description="Descripción del inmueble en las propias palabras del cliente (ubicación, tipo, lo que haya mencionado)")
    preferred_datetime: str = Field(..., description="Fecha/hora preferida tal como la expresó el cliente (puede ser texto libre, ej. 'mañana en la tarde')")

@tool(args_schema=SearchInput)
def search_properties(location=None, min_price=None, max_price=None, min_bedrooms=None, max_bedrooms=None, property_type=None):
    """Search property catalog. Grounding: returns no-matches message if empty, never invents."""
    from agent.fakes import FakeCatalog
    from agent.types import SearchFilters
    
    catalog = FakeCatalog()
    filters = SearchFilters(location=location, min_price=min_price, max_price=max_price, min_bedrooms=min_bedrooms, max_bedrooms=max_bedrooms, property_type=property_type)
    results = catalog.properties.values()
    
    filtered = []
    for prop in results:
        if location and prop.location.lower() != location.lower(): continue
        if min_price and prop.price < min_price: continue
        if max_price and prop.price > max_price: continue
        if min_bedrooms and prop.bedrooms < min_bedrooms: continue
        if max_bedrooms and prop.bedrooms > max_bedrooms: continue
        if property_type and prop.property_type != property_type: continue
        filtered.append(prop)
    
    if not filtered:
        return "No properties match. Try adjusting budget, location, or rooms."
    
    result_text = f"Found {len(filtered[:5])} properties:\n"
    for prop in filtered[:5]:
        result_text += f"- {prop.name} ({prop.location}): ${prop.price:,} | {prop.bedrooms}bed {prop.bathrooms}bath | ID:{prop.id}\n"
    return result_text

@tool(args_schema=PropertyQAInput)
def answer_property_question(property_id, question):
    """Answer facts about a property from record only. No hallucination."""
    from agent.fakes import FakeCatalog
    catalog = FakeCatalog()
    prop = catalog.properties.get(property_id)
    if not prop:
        return f"Property {property_id} not found."
    
    q = question.lower()
    if "price" in q: return f"${prop.price:,} COP"
    if "area" in q or "size" in q: return f"{prop.area_sqm}m²"
    if "bed" in q: return f"{prop.bedrooms} bedrooms"
    if "bath" in q: return f"{prop.bathrooms} bathrooms"
    if "feature" in q: return f"{', '.join(prop.features) if prop.features else 'No special features'}"
    if "location" in q: return f"{prop.location}"
    if "type" in q: return f"{prop.property_type}"
    return f"{prop.name}: ${prop.price:,} | {prop.bedrooms}bed {prop.bathrooms}bath {prop.area_sqm}m² | {prop.location}"

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
    """Request a property visit WITHOUT checking the real catalog/availability
    (use this only while search_properties/check_availability have no real
    data to offer — i.e. the database isn't connected yet). Sends the
    request directly to the human agent by email, based only on what the
    client described in the conversation. Do not invent a client_id — use
    the one given in the system context for this conversation."""
    import uuid
    from agent.notifications import send_manual_visit_request

    appointment_id = f"manual-{uuid.uuid4().hex[:8]}"

    try:
        ok = await send_manual_visit_request(
            appointment_id, client_id, property_description, preferred_datetime
        )
    except Exception as e:
        print(f"[request_visit] No se pudo notificar al agente: {e}")
        return "Tuve un problema enviando tu solicitud, intenta de nuevo en un momento."

    if ok:
        return (
            f"Listo, envié tu solicitud de visita al agente inmobiliario. "
            f"Te contactará pronto para confirmar disponibilidad. "
            f"ID de referencia: {appointment_id}"
        )
    return "No pude enviar la solicitud en este momento, pero tu interés quedó registrado. Intenta de nuevo más tarde."

def get_tools():
    """Get all tools."""
    return [search_properties, answer_property_question, check_availability, schedule_meeting, save_liked_property, request_visit]
