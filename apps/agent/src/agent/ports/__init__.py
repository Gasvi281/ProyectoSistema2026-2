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
