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
    availability = FakeAvailability()
    booking = FakeBooking()

    slot = availability.slots.get(slot_id)
    if not slot or slot.property_id != property_id:
        return f"Slot {slot_id} invalid for this property."

    appt = await booking.create_appointment(property_id, client_id, slot_id, "Via assistant")
    time_str = slot.start_time.strftime("%a %b %d %H:%M")
    return f"Appointment scheduled for {time_str}. ID: {appt.id}. Status: pending_confirmation. Agent will confirm soon."

@tool(args_schema=LikePropertyInput)
async def save_liked_property(client_id, property_id):
    """Record client's interest in property."""
    from agent.fakes import FakeConversationStore
    store = FakeConversationStore()
    await store.record_liked_property(client_id, property_id)
    return f"Saved {property_id} to your preferences."

def get_tools():
    """Get all tools."""
    return [search_properties, answer_property_question, check_availability, schedule_meeting, save_liked_property]
