"""In-memory implementations of all ports."""
from datetime import datetime, timedelta
from collections import defaultdict
import uuid
from agent.types import Property, AvailableSlot, Appointment, SearchFilters, ClientInteraction
from agent.ports import CatalogPort, AvailabilityPort, BookingPort, NotificationsPort, ConversationStorePort

class FakeCatalog(CatalogPort):
    def __init__(self):
        self.properties = {
            "prop_001": Property("prop_001", "Apartamento Laureles", "Laureles", 250_000_000, 65, 2, 1, "apartment", ["balcony", "parking"], "Modern 2-bedroom"),
            "prop_002": Property("prop_002", "Casa Sabaneta", "Sabaneta", 350_000_000, 120, 3, 2, "house", ["garden", "garage"], "Family house"),
            "prop_003": Property("prop_003", "Apartamento Centro", "Centro", 180_000_000, 45, 1, 1, "apartment", ["balcony"], "Compact apartment"),
            "prop_004": Property("prop_004", "Casa Envigado", "Envigado", 450_000_000, 180, 4, 3, "house", ["pool", "garden"], "Luxury house"),
        }
    
    async def search(self, filters: SearchFilters, limit: int = 5) -> list[Property]:
        results = []
        for prop in self.properties.values():
            if filters.location and prop.location.lower() != filters.location.lower():
                continue
            if filters.min_price and prop.price < filters.min_price:
                continue
            if filters.max_price and prop.price > filters.max_price:
                continue
            if filters.min_bedrooms and prop.bedrooms < filters.min_bedrooms:
                continue
            if filters.max_bedrooms and prop.bedrooms > filters.max_bedrooms:
                continue
            if filters.property_type and prop.property_type != filters.property_type:
                continue
            results.append(prop)
        return results[:limit]
    
    async def get_property(self, property_id: str) -> Property:
        return self.properties.get(property_id)

class FakeAvailability(AvailabilityPort):
    def __init__(self):
        self.slots = {}
        base_date = datetime(2026, 8, 20)
        slot_id = 0
        for prop_id in ["prop_001", "prop_002", "prop_003", "prop_004"]:
            for day_offset in range(14):
                date = base_date + timedelta(days=day_offset)
                slot_id += 1
                self.slots[f"slot_{slot_id}"] = AvailableSlot(f"slot_{slot_id}", prop_id, date.replace(hour=9), date.replace(hour=10), "agent_001")
                slot_id += 1
                self.slots[f"slot_{slot_id}"] = AvailableSlot(f"slot_{slot_id}", prop_id, date.replace(hour=14), date.replace(hour=15), "agent_002")
    
    async def list_slots(self, property_id: str, start_date: datetime, end_date: datetime) -> list[AvailableSlot]:
        results = [s for s in self.slots.values() if s.property_id == property_id and start_date <= s.start_time <= end_date]
        return sorted(results, key=lambda s: s.start_time)
    
    async def get_slot(self, slot_id: str) -> AvailableSlot:
        return self.slots.get(slot_id)

class FakeBooking(BookingPort):
    def __init__(self):
        self.appointments = {}
    
    async def create_appointment(self, property_id: str, client_id: str, slot_id: str, notes: str = "") -> Appointment:
        appointment = Appointment(str(uuid.uuid4()), property_id, client_id, slot_id, datetime.now(), "pending_confirmation", notes)
        self.appointments[appointment.id] = appointment
        return appointment
    
    async def get_appointment(self, appointment_id: str) -> Appointment:
        return self.appointments.get(appointment_id)
    
    async def confirm_appointment(self, appointment_id: str) -> Appointment:
        appointment = self.appointments.get(appointment_id)
        if appointment:
            appointment.status = "confirmed"
        return appointment

class FakeNotifications(NotificationsPort):
    def __init__(self):
        self.sent = []
    
    async def notify_agent_appointment(self, appointment_id: str, property_id: str, client_id: str) -> bool:
        self.sent.append({"appointment_id": appointment_id, "property_id": property_id, "client_id": client_id})
        return True

class FakeConversationStore(ConversationStorePort):
    def __init__(self):
        self.interactions = {}
        self.client_interactions = defaultdict(list)
        self.liked = defaultdict(set)
    
    async def save_interaction(self, interaction: ClientInteraction) -> None:
        self.interactions[interaction.id] = interaction
        self.client_interactions[interaction.client_id].append(interaction.id)
    
    async def get_client_history(self, client_id: str, limit: int = 50) -> list:
        ids = self.client_interactions.get(client_id, [])
        return [self.interactions[iid] for iid in reversed(ids[-limit:])]
    
    async def record_liked_property(self, client_id: str, property_id: str) -> None:
        self.liked[client_id].add(property_id)
