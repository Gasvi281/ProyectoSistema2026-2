"""
test_listing_agency_resolver.py
--------------------------------
Pruebas unitarias de ListingAgencyResolverPort / FakeListingAgencyResolver.
"""
import pytest
from agent.fakes import FakeListingAgencyResolver, UnknownListingError, KNOWN_AGENCY_IDS

# Listing real de seed (CLAUDE.md) y agencia asignada arbitraria pero coherente.
SEED_LISTING = "c34b9fbb-8d4a-45b8-951a-c8ea585a0afa"
SEED_AGENCY  = "8768a84f-a76a-4de6-8e9e-1a11fcbb4e59"  # Cruz-Oviedo Realty


@pytest.mark.asyncio
async def test_known_listing_resolves_to_agency():
    """Un listing mapeado en el constructor retorna exactamente ese agency_id."""
    resolver = FakeListingAgencyResolver({SEED_LISTING: SEED_AGENCY})
    result = await resolver.resolve(SEED_LISTING)
    assert result == SEED_AGENCY


@pytest.mark.asyncio
async def test_known_listing_agency_is_in_known_agencies():
    """El agency_id resuelto pertenece al universo de agencias válidas."""
    resolver = FakeListingAgencyResolver({SEED_LISTING: SEED_AGENCY})
    result = await resolver.resolve(SEED_LISTING)
    assert result in KNOWN_AGENCY_IDS


@pytest.mark.asyncio
async def test_unknown_listing_raises_error():
    """Un listing no mapeado lanza UnknownListingError — nunca retorna None."""
    resolver = FakeListingAgencyResolver()  # sin seed
    with pytest.raises(UnknownListingError):
        await resolver.resolve("00000000-0000-0000-0000-000000000000")
