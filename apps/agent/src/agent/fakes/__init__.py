"""In-memory implementations of all ports."""
from datetime import datetime, timedelta, timezone
from collections import defaultdict
import uuid
from agent.types import Property, AvailableSlot, Appointment, SearchFilters, ClientInteraction
from agent.ports import CatalogPort, AvailabilityPort, BookingPort, NotificationsPort, ConversationStorePort, AgentSlotsPort, AppointmentBookingPort, ClientResolverPort, LeadPort

class FakeCatalog(CatalogPort):
    def __init__(self):
        # DEUDA TÉCNICA (T-xx, vinculada a HU-21/HU-22): estos son IDs sintéticos
        # que violarían la FK real del backend si llegaran a un POST http.
        # Riesgo solo si se mezcla modo fake y modo http sin aislar datos de
        # prueba — hoy no ocurre porque agent_slots.py/booking.py (modo http)
        # no consumen FakeCatalog. No resolver sin antes decidir si el fix es
        # usar UUIDs reales de seed o aislar los modos más estrictamente.
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

class FakeAgentSlots(AgentSlotsPort):
    """Disponibilidad predefinida para un agente ficticio (sin HTTP)."""

    SLOT_MINUTES = 30

    async def list_agent_slots(self, agent_id: str, date_from: str, date_to: str) -> dict:
        base = datetime(2026, 9, 10, 9, 0, tzinfo=timezone.utc)
        slots = []
        for offset in range(4):
            start = base + timedelta(hours=offset)
            end = start + timedelta(minutes=self.SLOT_MINUTES)
            slots.append({"start": start.isoformat(), "end": end.isoformat()})
        return {
            "agent_id": agent_id,
            "slot_minutes": self.SLOT_MINUTES,
            "slots": slots,
        }


class FakeAppointmentBooking(AppointmentBookingPort):
    """Crea una cita en memoria (sin HTTP) para dev y tests."""

    async def book(self, lead_id: str, scheduled_at: str, duration_min: int) -> dict:
        now = datetime.now(timezone.utc).isoformat()
        return {
            "id": f"appt-{uuid.uuid4().hex[:8]}",
            "lead_id": lead_id,
            "agent_id": "agent-fake",
            "scheduled_at": scheduled_at,
            "duration_min": duration_min,
            "status": "PENDING_CONFIRMATION",
            "created_at": now,
            "updated_at": now,
        }


# Datos de seed verificados contra el backend desplegado (CLAUDE.md).
# DEUDA TÉCNICA: inválidos si se reseedea la DB — mismo riesgo que prop_001-004.
SEED_CLIENT_ID = "6cdfee4d-a409-44a4-8a64-cf59ac9ec4ad"
SEED_LISTING_ID = "c34b9fbb-8d4a-45b8-951a-c8ea585a0afa"
SEED_AGENT_ID   = "02627f73-1292-4f83-af8c-485bc07a30f2"  # dueño de SEED_LISTING_ID (33 listings)

class FakeClientResolver(ClientResolverPort):
    """Mapea cualquier chat_id al client_id de seed, de forma estable en memoria.

    El dict garantiza que el mismo chat_id devuelve siempre el mismo id durante
    la sesión — deja el punto de extensión listo para ids por-cliente reales.
    """
    def __init__(self):
        self._map: dict[str, str] = {}

    async def resolve_client(self, chat_id: str, phone: str | None = None, full_name: str | None = None) -> str:
        return self._map.setdefault(chat_id, SEED_CLIENT_ID)


class FakeLead(LeadPort):
    """Crea/recupera un lead en memoria, emulando el upsert por (client_id, listing_id).

    El backend hace dedup server-side — el bot nunca hace pre-check. Este fake modela
    ese contrato: la misma combinación (client_id, listing_id) devuelve el mismo lead.
    agent_id = SEED_AGENT_ID para que la cadena lead→check_agent_availability sea
    consistente con los datos reales de seed (FakeAgentSlots lo espeja sin mapear).
    """
    def __init__(self):
        self._leads: dict[tuple[str, str], dict] = {}

    async def create_or_get_lead(self, client_id: str, listing_id: str, source_channel: str = "IN_APP") -> dict:
        key = (client_id, listing_id)
        if key in self._leads:
            return self._leads[key]          # get: mismo lead que la llamada previa
        now = datetime.now(timezone.utc).isoformat()
        lead = {
            "id": f"lead-{uuid.uuid4().hex[:8]}",
            "client_id": client_id,
            "listing_id": listing_id,
            "agent_id": SEED_AGENT_ID,       # el backend lo deriva; el fake usa el de seed
            "source_channel": source_channel,
            "status": "NEW",
            "created_at": now,
            "updated_at": now,
        }
        self._leads[key] = lead
        return lead


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
