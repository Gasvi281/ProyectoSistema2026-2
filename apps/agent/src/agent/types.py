"""Domain types for the conversational agent."""
from dataclasses import dataclass, field
from typing import Optional
from datetime import datetime

@dataclass
class Property:
    id: str
    name: str
    location: str
    price: int
    area_sqm: int
    bedrooms: int
    bathrooms: int
    property_type: str
    features: list[str] = field(default_factory=list)
    description: str = ""

@dataclass
class AvailableSlot:
    slot_id: str
    property_id: str
    start_time: datetime
    end_time: datetime
    agent_id: Optional[str] = None

@dataclass
class Appointment:
    id: str
    property_id: str
    client_id: str
    slot_id: str
    scheduled_at: datetime
    status: str
    notes: str = ""

@dataclass
class SearchFilters:
    location: Optional[str] = None
    min_price: Optional[int] = None
    max_price: Optional[int] = None
    min_bedrooms: Optional[int] = None
    max_bedrooms: Optional[int] = None
    property_type: Optional[str] = None

@dataclass
class AgentReply:
    reply_text: str
    matched_properties: list[Property] = field(default_factory=list)
    proposed_appointment: Optional[Appointment] = None
    metadata: dict = field(default_factory=dict)

@dataclass
class ClientInteraction:
    id: str
    client_id: str
    channel: str
    channel_user_id: str
    message: str
    reply: str
    timestamp: datetime
    liked_properties: list[str] = field(default_factory=list)
    asked_questions: list[str] = field(default_factory=list)
