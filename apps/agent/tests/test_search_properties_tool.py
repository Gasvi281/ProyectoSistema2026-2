"""Tests para los tools search_properties y answer_property_question."""
import json
import pytest
import httpx

from agent.tools_langchain import search_properties, answer_property_question
from agent.ports import ListingSearchPort
from agent.types import Property, SearchFilters


# ---------------------------------------------------------------------------
# Stubs
# ---------------------------------------------------------------------------

class _SearchReturns(ListingSearchPort):
    def __init__(self, props):
        self._props = props

    async def search(self, filters: SearchFilters, limit: int = 5) -> list[Property]:
        return self._props[:limit]

    async def get_listing(self, listing_id: str):
        return next((p for p in self._props if p.id == listing_id), None)


class _SearchRaises(ListingSearchPort):
    def __init__(self, exc):
        self._exc = exc

    async def search(self, filters, limit=5):
        raise self._exc

    async def get_listing(self, listing_id):
        raise self._exc


_PROP_SALE = Property(
    "c34b9fbb-8d4a-45b8-951a-c8ea585a0afa", "Apartamento en Laureles", "Laureles",
    250_000_000, 65, 2, 1, "APARTMENT", [], "Cra 80 #45", "SALE",
)
_PROP_RENT = Property(
    "92698698-61a1-4729-bcb9-83501b4da0fe", "Apartamento en Centro", "Centro",
    1_800_000, 45, 1, 1, "APARTMENT", [], "Calle 50 #10", "RENT",
)


# ---------------------------------------------------------------------------
# search_properties
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_search_results_contain_id_not_in_summary(monkeypatch):
    monkeypatch.setattr(
        "agent.listing_search.get_listing_search_provider",
        lambda: _SearchReturns([_PROP_SALE]),
    )
    result = await search_properties.ainvoke({"location": "Laureles"})

    assert result["count"] == 1
    assert result["results"][0]["id"] == _PROP_SALE.id
    assert _PROP_SALE.id not in result["summary"]


@pytest.mark.asyncio
async def test_search_summary_shows_venta_arriendo(monkeypatch):
    monkeypatch.setattr(
        "agent.listing_search.get_listing_search_provider",
        lambda: _SearchReturns([_PROP_SALE, _PROP_RENT]),
    )
    result = await search_properties.ainvoke({})

    assert "venta" in result["summary"]
    assert "arriendo" in result["summary"]


@pytest.mark.asyncio
async def test_search_empty_returns_count_zero(monkeypatch):
    monkeypatch.setattr(
        "agent.listing_search.get_listing_search_provider",
        lambda: _SearchReturns([]),
    )
    result = await search_properties.ainvoke({"location": "Bogotá"})

    assert result["count"] == 0
    assert result["results"] == []
    assert result["error"] is None


@pytest.mark.asyncio
async def test_search_5xx_returns_backend_unavailable(monkeypatch):
    resp = httpx.Response(503, request=httpx.Request("GET", "http://x"))
    exc = httpx.HTTPStatusError("down", request=resp.request, response=resp)
    monkeypatch.setattr(
        "agent.listing_search.get_listing_search_provider",
        lambda: _SearchRaises(exc),
    )
    result = await search_properties.ainvoke({})

    assert result["code"] == "BACKEND_UNAVAILABLE"
    assert result["error_code"] == 503
    assert result["count"] == 0


@pytest.mark.asyncio
async def test_search_transport_error_returns_backend_unavailable(monkeypatch):
    monkeypatch.setattr(
        "agent.listing_search.get_listing_search_provider",
        lambda: _SearchRaises(httpx.ConnectError("refused")),
    )
    result = await search_properties.ainvoke({})

    assert result["code"] == "BACKEND_UNAVAILABLE"
    assert result["error_code"] is None


@pytest.mark.asyncio
async def test_search_403_returns_backend_auth_error(monkeypatch):
    resp = httpx.Response(403, request=httpx.Request("GET", "http://x"))
    exc = httpx.HTTPStatusError("forbidden", request=resp.request, response=resp)
    monkeypatch.setattr(
        "agent.listing_search.get_listing_search_provider",
        lambda: _SearchRaises(exc),
    )
    result = await search_properties.ainvoke({})

    assert result["code"] == "BACKEND_AUTH_ERROR"
    assert result["error_code"] == 403


# ---------------------------------------------------------------------------
# answer_property_question
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_answer_price_question(monkeypatch):
    monkeypatch.setattr(
        "agent.listing_search.get_listing_search_provider",
        lambda: _SearchReturns([_PROP_SALE]),
    )
    result = await answer_property_question.ainvoke(
        {"property_id": _PROP_SALE.id, "question": "¿cuál es el precio?"}
    )
    assert "250,000,000" in result["answer"]
    assert result["error"] is None


@pytest.mark.asyncio
async def test_answer_404_returns_unknown_listing(monkeypatch):
    monkeypatch.setattr(
        "agent.listing_search.get_listing_search_provider",
        lambda: _SearchReturns([]),
    )
    result = await answer_property_question.ainvoke(
        {"property_id": "no-such-id", "question": "precio"}
    )
    assert result["code"] == "UNKNOWN_LISTING"
    assert result["answer"] is None


@pytest.mark.asyncio
async def test_answer_backend_unavailable(monkeypatch):
    resp = httpx.Response(503, request=httpx.Request("GET", "http://x"))
    exc = httpx.HTTPStatusError("down", request=resp.request, response=resp)
    monkeypatch.setattr(
        "agent.listing_search.get_listing_search_provider",
        lambda: _SearchRaises(exc),
    )
    result = await answer_property_question.ainvoke(
        {"property_id": "any-id", "question": "precio"}
    )
    assert result["code"] == "BACKEND_UNAVAILABLE"


@pytest.mark.asyncio
async def test_answer_operation_type_question(monkeypatch):
    monkeypatch.setattr(
        "agent.listing_search.get_listing_search_provider",
        lambda: _SearchReturns([_PROP_SALE]),
    )
    result = await answer_property_question.ainvoke(
        {"property_id": _PROP_SALE.id, "question": "¿está en venta o arriendo?"}
    )
    assert "venta" in result["answer"].lower() or "SALE" in result["answer"]
