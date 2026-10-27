"""Tests para ListingSearchPort, FakeListingSearch, HttpListingSearch y el factory."""
import json
import pytest
import httpx

from agent.fakes import FakeListingSearch, _normalize, _matches, _type_es, FAKE_DEFAULT_AGENCY_ID
from agent.listing_search import (
    HttpListingSearch,
    _map_listing,
    get_listing_search_provider,
    check_listing_search_modes,
)
from agent.types import Property, SearchFilters


# ---------------------------------------------------------------------------
# _type_es
# ---------------------------------------------------------------------------

def test_type_es_known_values():
    assert _type_es("APARTMENT") == "Apartamento"
    assert _type_es("HOUSE") == "Casa"
    assert _type_es("STUDIO") == "Estudio"
    assert _type_es("COUNTRY_HOUSE") == "Casa campestre"


def test_type_es_unknown_returns_raw():
    assert _type_es("PENTHOUSE") == "PENTHOUSE"


def test_type_es_none_returns_generic():
    assert _type_es(None) == "Propiedad"


# ---------------------------------------------------------------------------
# _normalize + _matches — location (accent-insensitive substring)
# ---------------------------------------------------------------------------

def test_normalize_strips_accents():
    assert _normalize("Lauréles") == _normalize("Laureles")
    assert _normalize("Envigadó") == _normalize("Envigado")


def _prop(location="Laureles", price=200_000_000, bedrooms=2, property_type="APARTMENT", operation_type="SALE"):
    return Property("x", "X", location, price, 60, bedrooms, 1, property_type, operation_type=operation_type)


def test_matches_location_substring():
    f = SearchFilters(location="laureles")
    assert _matches(_prop(location="Laureles"), f)
    assert not _matches(_prop(location="Sabaneta"), f)


def test_matches_location_accent_insensitive():
    f = SearchFilters(location="laureles")
    assert _matches(_prop(location="Lauréles"), f)


def test_matches_price_range():
    assert _matches(_prop(price=200_000_000), SearchFilters(min_price=100_000_000, max_price=300_000_000))
    assert not _matches(_prop(price=50_000_000), SearchFilters(min_price=100_000_000))
    assert not _matches(_prop(price=400_000_000), SearchFilters(max_price=300_000_000))


def test_matches_bedrooms_range():
    assert _matches(_prop(bedrooms=3), SearchFilters(min_bedrooms=2, max_bedrooms=4))
    assert not _matches(_prop(bedrooms=1), SearchFilters(min_bedrooms=2))


def test_matches_property_type_case_insensitive():
    assert _matches(_prop(property_type="APARTMENT"), SearchFilters(property_type="apartment"))
    assert not _matches(_prop(property_type="HOUSE"), SearchFilters(property_type="APARTMENT"))


def test_matches_operation_type_exact():
    assert _matches(_prop(operation_type="SALE"), SearchFilters(operation_type="SALE"))
    assert not _matches(_prop(operation_type="RENT"), SearchFilters(operation_type="SALE"))


def test_matches_no_filters_always_true():
    assert _matches(_prop(), SearchFilters())


# ---------------------------------------------------------------------------
# FakeListingSearch
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_fake_search_no_filters_returns_all():
    results = await FakeListingSearch().search(SearchFilters())
    assert len(results) == 4


@pytest.mark.asyncio
async def test_fake_search_no_match_returns_empty():
    results = await FakeListingSearch().search(SearchFilters(location="Bogotá"))
    assert results == []


@pytest.mark.asyncio
async def test_fake_search_limit_respected():
    results = await FakeListingSearch().search(SearchFilters(), limit=2)
    assert len(results) == 2


@pytest.mark.asyncio
async def test_fake_search_operation_type_filters():
    rent = await FakeListingSearch().search(SearchFilters(operation_type="RENT"))
    assert all(p.operation_type == "RENT" for p in rent)
    assert len(rent) >= 1
    sale = await FakeListingSearch().search(SearchFilters(operation_type="SALE"))
    assert all(p.operation_type == "SALE" for p in sale)


@pytest.mark.asyncio
async def test_fake_get_listing_hit():
    prop = await FakeListingSearch().get_listing("prop_001")
    assert prop is not None
    assert prop.id == "prop_001"


@pytest.mark.asyncio
async def test_fake_get_listing_miss_returns_none():
    prop = await FakeListingSearch().get_listing("does-not-exist")
    assert prop is None


# ---------------------------------------------------------------------------
# _map_listing
# ---------------------------------------------------------------------------

_BASE_ROW = {
    "id": "abc123",
    "agent_id": "agent-1",
    "operation_type": "SALE",
    "asking_price": "250000000.00",
    "status": "ACTIVE",
    "published_at": "2026-09-01T00:00:00",
    "city": "Medellín",
    "neighborhood": "Laureles",
    "address": "Cra 80 #45-10",
    "property_type": "APARTMENT",
    "area_m2": "65.50",
    "bedrooms": 2,
    "bathrooms": 1,
}


def test_map_listing_name_composed():
    prop = _map_listing(_BASE_ROW)
    assert prop.name == "Apartamento en Laureles"


def test_map_listing_prefers_neighborhood_over_city():
    prop = _map_listing(_BASE_ROW)
    assert prop.location == "Laureles"


def test_map_listing_price_and_area_as_int():
    prop = _map_listing(_BASE_ROW)
    assert prop.price == 250_000_000
    assert prop.area_sqm == 65


def test_map_listing_operation_type():
    prop = _map_listing(_BASE_ROW)
    assert prop.operation_type == "SALE"


def test_map_listing_unknown_type_uses_raw():
    row = {**_BASE_ROW, "property_type": "PENTHOUSE", "neighborhood": "El Poblado"}
    prop = _map_listing(row)
    assert prop.name.startswith("PENTHOUSE")


def test_map_listing_no_neighborhood_falls_back_to_city():
    row = {**_BASE_ROW, "neighborhood": None}
    prop = _map_listing(row)
    assert prop.location == "Medellín"
    assert "Medellín" in prop.name


# ---------------------------------------------------------------------------
# HttpListingSearch — helpers
# ---------------------------------------------------------------------------

_VALID_ENV = {
    "BACKEND_URL": "https://fake-backend.test",
    "BACKEND_SERVICE_TOKEN": "tok-test",
    "AGENCY_ID": "8768a84f-a76a-4de6-8e9e-1a11fcbb4e59",
}

_LISTING_ROWS = [
    {**_BASE_ROW, "id": "listing-1", "neighborhood": "Laureles", "operation_type": "SALE"},
    {**_BASE_ROW, "id": "listing-2", "neighborhood": "Sabaneta", "operation_type": "RENT",
     "asking_price": "1800000.00", "bedrooms": 1},
]


def _set_env(monkeypatch):
    for k, v in _VALID_ENV.items():
        monkeypatch.setenv(k, v)
    monkeypatch.delenv("BOT_EMAIL", raising=False)
    monkeypatch.delenv("BOT_PASSWORD", raising=False)
    monkeypatch.delenv("DEV_AGENT_ID", raising=False)


# (1) search — maps list response + sends X-Agency-Id + status=ACTIVE

@pytest.mark.asyncio
async def test_http_search_sends_agency_id_and_status(monkeypatch):
    _set_env(monkeypatch)
    captured = {}

    async def mock_get(self, url, *, params=None, headers=None, **kw):
        captured["params"] = params
        captured["headers"] = headers
        req = httpx.Request("GET", url)
        return httpx.Response(200, content=json.dumps(_LISTING_ROWS).encode(), request=req)

    monkeypatch.setattr(httpx.AsyncClient, "get", mock_get)
    results = await HttpListingSearch().search(SearchFilters())

    assert captured["params"]["status"] == "ACTIVE"
    assert captured["params"]["limit"] == 200
    assert captured["headers"]["X-Agency-Id"] == _VALID_ENV["AGENCY_ID"]
    assert len(results) == 2


# (2) search — sends operation_type server-side when set

@pytest.mark.asyncio
async def test_http_search_sends_operation_type_param(monkeypatch):
    _set_env(monkeypatch)
    captured = {}

    async def mock_get(self, url, *, params=None, headers=None, **kw):
        captured["params"] = params
        req = httpx.Request("GET", url)
        return httpx.Response(200, content=json.dumps([]).encode(), request=req)

    monkeypatch.setattr(httpx.AsyncClient, "get", mock_get)
    await HttpListingSearch().search(SearchFilters(operation_type="SALE"))

    assert captured["params"].get("operation_type") == "SALE"


# (3) search — SALE+price excludes RENT listings via _matches client-side

@pytest.mark.asyncio
async def test_http_search_sale_price_excludes_rent(monkeypatch):
    _set_env(monkeypatch)

    async def mock_get(self, url, *, params=None, headers=None, **kw):
        req = httpx.Request("GET", url)
        return httpx.Response(200, content=json.dumps(_LISTING_ROWS).encode(), request=req)

    monkeypatch.setattr(httpx.AsyncClient, "get", mock_get)
    # listing-2 is RENT with price ~1.8M, listing-1 is SALE with 250M
    results = await HttpListingSearch().search(
        SearchFilters(operation_type="SALE", max_price=300_000_000)
    )
    ids = [r.id for r in results]
    assert "listing-1" in ids
    assert "listing-2" not in ids


# (4) search — accent/case-insensitive substring location match

@pytest.mark.asyncio
async def test_http_search_accent_location_match(monkeypatch):
    _set_env(monkeypatch)

    async def mock_get(self, url, *, params=None, headers=None, **kw):
        req = httpx.Request("GET", url)
        return httpx.Response(200, content=json.dumps(_LISTING_ROWS).encode(), request=req)

    monkeypatch.setattr(httpx.AsyncClient, "get", mock_get)
    results = await HttpListingSearch().search(SearchFilters(location="lauréles"))
    assert len(results) == 1
    assert results[0].id == "listing-1"


# (5) search — 503 raises HTTPStatusError

@pytest.mark.asyncio
async def test_http_search_503_raises(monkeypatch):
    _set_env(monkeypatch)

    async def mock_get(self, url, *, params=None, headers=None, **kw):
        req = httpx.Request("GET", url)
        return httpx.Response(503, content=b'{"detail":"down"}', request=req)

    monkeypatch.setattr(httpx.AsyncClient, "get", mock_get)
    with pytest.raises(httpx.HTTPStatusError):
        await HttpListingSearch().search(SearchFilters())


# (6) missing AGENCY_ID — ValueError on construct

def test_http_missing_agency_id_raises(monkeypatch):
    _set_env(monkeypatch)
    monkeypatch.delenv("AGENCY_ID", raising=False)
    with pytest.raises(ValueError, match="AGENCY_ID"):
        HttpListingSearch()


# (7) get_listing — 200 returns Property

@pytest.mark.asyncio
async def test_http_get_listing_200(monkeypatch):
    _set_env(monkeypatch)

    async def mock_get(self, url, *, params=None, headers=None, **kw):
        req = httpx.Request("GET", url)
        return httpx.Response(200, content=json.dumps(_BASE_ROW).encode(), request=req)

    monkeypatch.setattr(httpx.AsyncClient, "get", mock_get)
    prop = await HttpListingSearch().get_listing("abc123")
    assert prop is not None
    assert prop.id == "abc123"


# (8) get_listing — 404 returns None

@pytest.mark.asyncio
async def test_http_get_listing_404_returns_none(monkeypatch):
    _set_env(monkeypatch)

    async def mock_get(self, url, *, params=None, headers=None, **kw):
        req = httpx.Request("GET", url)
        return httpx.Response(404, content=b'{"detail":"not found"}', request=req)

    monkeypatch.setattr(httpx.AsyncClient, "get", mock_get)
    prop = await HttpListingSearch().get_listing("no-such-id")
    assert prop is None


# (9) get_listing — 422 returns None

@pytest.mark.asyncio
async def test_http_get_listing_422_returns_none(monkeypatch):
    _set_env(monkeypatch)

    async def mock_get(self, url, *, params=None, headers=None, **kw):
        req = httpx.Request("GET", url)
        return httpx.Response(422, content=b'{"detail":"invalid uuid"}', request=req)

    monkeypatch.setattr(httpx.AsyncClient, "get", mock_get)
    prop = await HttpListingSearch().get_listing("not-a-uuid")
    assert prop is None


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def test_factory_default_is_fake(monkeypatch):
    monkeypatch.delenv("LISTING_SEARCH_MODE", raising=False)
    assert isinstance(get_listing_search_provider(), FakeListingSearch)


def test_factory_fake_explicit(monkeypatch):
    monkeypatch.setenv("LISTING_SEARCH_MODE", "fake")
    assert isinstance(get_listing_search_provider(), FakeListingSearch)


def test_factory_http(monkeypatch):
    _set_env(monkeypatch)
    monkeypatch.setenv("LISTING_SEARCH_MODE", "http")
    assert isinstance(get_listing_search_provider(), HttpListingSearch)


def test_factory_invalid_raises(monkeypatch):
    monkeypatch.setenv("LISTING_SEARCH_MODE", "invalid")
    with pytest.raises(ValueError, match="LISTING_SEARCH_MODE inválido"):
        get_listing_search_provider()


# ---------------------------------------------------------------------------
# check_listing_search_modes
# ---------------------------------------------------------------------------

def test_guard_http_without_agency_id_raises(monkeypatch):
    monkeypatch.setenv("LISTING_SEARCH_MODE", "http")
    monkeypatch.delenv("AGENCY_ID", raising=False)
    with pytest.raises(ValueError, match="AGENCY_ID"):
        check_listing_search_modes()


def test_guard_lead_http_search_fake_raises(monkeypatch):
    monkeypatch.setenv("LEAD_MODE", "http")
    monkeypatch.setenv("LISTING_SEARCH_MODE", "fake")
    with pytest.raises(ValueError, match="LISTING_SEARCH_MODE=fake"):
        check_listing_search_modes()


def test_guard_all_fake_ok(monkeypatch):
    monkeypatch.setenv("LEAD_MODE", "fake")
    monkeypatch.setenv("LISTING_SEARCH_MODE", "fake")
    check_listing_search_modes()  # no debe lanzar


def test_guard_all_http_ok(monkeypatch):
    monkeypatch.setenv("LEAD_MODE", "http")
    monkeypatch.setenv("LISTING_SEARCH_MODE", "http")
    monkeypatch.setenv("AGENCY_ID", "some-agency-id")
    monkeypatch.setenv("BACKEND_URL", "https://x.example.com")
    monkeypatch.setenv("BACKEND_SERVICE_TOKEN", "tok")
    check_listing_search_modes()  # no debe lanzar
