"""Tests for agent tools."""
import pytest
from agent.fakes import FakeCatalog, FakeAvailability, FakeBooking
from agent.types import SearchFilters
from datetime import datetime

@pytest.mark.asyncio
async def test_search_returns_results():
    """Search returns matching properties."""
    catalog = FakeCatalog()
    filters = SearchFilters(location="Laureles")
    results = await catalog.search(filters)
    assert len(results) > 0
    assert results[0].name == "Apartamento Laureles"

@pytest.mark.asyncio
async def test_search_no_hallucination_on_empty_catalog():
    """No property names when catalog is empty (grounding test)."""
    catalog = FakeCatalog()
    catalog.properties = {}  # Empty catalog
    results = await catalog.search(SearchFilters(location="Laureles"))
    assert len(results) == 0

@pytest.mark.asyncio
async def test_property_qa_retrieves_facts():
    """Property Q&A returns accurate facts."""
    catalog = FakeCatalog()
    prop = await catalog.get_property("prop_001")
    assert prop is not None
    assert prop.price == 250_000_000

@pytest.mark.asyncio
async def test_availability_lists_slots():
    """Availability lists real slots."""
    availability = FakeAvailability()
    start = datetime(2026, 8, 20)
    end = datetime(2026, 8, 27)
    slots = await availability.list_slots("prop_001", start, end)
    assert len(slots) > 0

@pytest.mark.asyncio
async def test_booking_creates_appointment():
    """Booking creates appointment in pending_confirmation status."""
    booking = FakeBooking()
    appointment = await booking.create_appointment("prop_001", "client_001", "slot_001")
    assert appointment.status == "pending_confirmation"
    assert appointment.property_id == "prop_001"

@pytest.mark.asyncio
async def test_booking_confirmation():
    """Appointment moves to confirmed status."""
    booking = FakeBooking()
    appointment = await booking.create_appointment("prop_001", "client_001", "slot_001")
    confirmed = await booking.confirm_appointment(appointment.id)
    assert confirmed.status == "confirmed"
