"""Abstract interfaces for backend services."""
from abc import ABC, abstractmethod
from typing import Optional
from datetime import datetime
from agent.types import Property, AvailableSlot, Appointment, SearchFilters

class CatalogPort(ABC):
    @abstractmethod
    async def search(self, filters: SearchFilters, limit: int = 5) -> list[Property]:
        pass
    @abstractmethod
    async def get_property(self, property_id: str) -> Optional[Property]:
        pass

class AvailabilityPort(ABC):
    @abstractmethod
    async def list_slots(self, property_id: str, start_date: datetime, end_date: datetime) -> list[AvailableSlot]:
        pass
    @abstractmethod
    async def get_slot(self, slot_id: str) -> Optional[AvailableSlot]:
        pass

class BookingPort(ABC):
    @abstractmethod
    async def create_appointment(self, property_id: str, client_id: str, slot_id: str, notes: str = "") -> Appointment:
        pass
    @abstractmethod
    async def get_appointment(self, appointment_id: str) -> Optional[Appointment]:
        pass
    @abstractmethod
    async def confirm_appointment(self, appointment_id: str) -> Appointment:
        pass

class NotificationsPort(ABC):
    @abstractmethod
    async def notify_agent_appointment(self, appointment_id: str, property_id: str, client_id: str) -> bool:
        pass

class ConversationStorePort(ABC):
    @abstractmethod
    async def save_interaction(self, interaction) -> None:
        pass
    @abstractmethod
    async def get_client_history(self, client_id: str, limit: int = 50) -> list:
        pass
    @abstractmethod
    async def record_liked_property(self, client_id: str, property_id: str) -> None:
        pass

class AgentSlotsPort(ABC):
    """Puerto para consultar disponibilidad de slots de un agente inmobiliario."""
    @abstractmethod
    async def list_agent_slots(self, agent_id: str, date_from: str, date_to: str) -> dict:
        """Retorna {"agent_id", "slot_minutes", "slots": [{"start", "end"}, ...]}."""
        pass

class AppointmentBookingPort(ABC):
    """Puerto para crear citas en el backend real."""
    @abstractmethod
    async def book(self, lead_id: str, scheduled_at: str, duration_min: int) -> dict:
        """
        Crea una cita. Retorna el objeto 201 del backend:
        {"id", "lead_id", "agent_id", "scheduled_at", "duration_min", "status",
         "created_at", "updated_at"}
        Lanza httpx.HTTPStatusError en error HTTP (incluye 409 y 422).
        """
        pass
