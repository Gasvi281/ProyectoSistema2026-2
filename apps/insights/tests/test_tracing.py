from unittest.mock import MagicMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import AIMessage

from insights import agent, backend
from insights.main import app
from shared.observability import trace_span

ME_ADMIN = {"id": "a1", "agency_id": "g1", "role": "TEAM_ADMIN", "active": True}
NORTH_STAR = {
    "leads": 40,
    "median_first_response_hours": None,
    "pct_with_follow_up": 62.5,
    "lead_to_visit_conversion_pct": 30.0,
    "pct_lost_within_48h": 5.0,
    "stage_conversion": [],
}


def _handler(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/me":
        return httpx.Response(200, json=ME_ADMIN)
    if request.url.path == "/analytics/north-star":
        return httpx.Response(200, json=NORTH_STAR)
    return httpx.Response(404)


@pytest.fixture(autouse=True)
def _backend(monkeypatch):
    monkeypatch.setenv("INSIGHTS_LLM_MODE", "fake")
    monkeypatch.setattr(backend, "_transport", httpx.MockTransport(_handler))
    # Grafo nuevo por test (el singleton puede venir de otro módulo).
    monkeypatch.setattr(agent, "_graph", None)


def _tracing_off(monkeypatch):
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)


def _tracing_on(monkeypatch):
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-test")


def _chat(client, conversation_id=None):
    return client.post(
        "/insights/chat",
        json={"message": "How is the agency doing?", "conversation_id": conversation_id},
        headers={"Authorization": "Bearer t"},
    )


def test_tracing_off_creates_no_handler_and_no_span(monkeypatch):
    _tracing_off(monkeypatch)
    with patch("langfuse.get_client") as get_client, patch(
        "langfuse.langchain.CallbackHandler"
    ) as handler_cls:
        resp = _chat(TestClient(app))
    assert resp.status_code == 200
    assert "leads: 40" in resp.json()["reply"]
    get_client.assert_not_called()
    handler_cls.assert_not_called()


def test_span_failure_does_not_break_request(monkeypatch):
    # Langfuse inalcanzable al abrir spans: el request sigue en 200.
    _tracing_on(monkeypatch)
    with patch("langfuse.get_client", side_effect=ConnectionError("langfuse down")), patch(
        "insights.agent.get_langfuse_callbacks", return_value=[]
    ):
        resp = _chat(TestClient(app))
    assert resp.status_code == 200
    assert "leads: 40" in resp.json()["reply"]


def test_handler_that_raises_does_not_break_request(monkeypatch):
    _tracing_on(monkeypatch)

    class BrokenHandler(BaseCallbackHandler):
        def on_chain_start(self, *args, **kwargs):
            raise RuntimeError("langfuse handler exploded")

        def on_llm_start(self, *args, **kwargs):
            raise RuntimeError("langfuse handler exploded")

    with patch("langfuse.get_client", return_value=MagicMock()), patch(
        "insights.agent.get_langfuse_callbacks", return_value=[BrokenHandler()]
    ):
        resp = _chat(TestClient(app))
    assert resp.status_code == 200
    assert "leads: 40" in resp.json()["reply"]


def test_session_id_and_trace_name_in_run_config(monkeypatch):
    _tracing_on(monkeypatch)
    captured = {}

    class StubGraph:
        async def ainvoke(self, inputs, config=None):
            captured["config"] = config
            return {"messages": [AIMessage(content="ok")]}

    monkeypatch.setattr(agent, "_graph", StubGraph())
    handler = BaseCallbackHandler()
    client_mock = MagicMock()
    with patch("langfuse.get_client", return_value=client_mock), patch(
        "insights.agent.get_langfuse_callbacks", return_value=[handler]
    ):
        body = _chat(TestClient(app), conversation_id="conv-123").json()

    config = captured["config"]
    assert config["callbacks"] == [handler]
    assert config["metadata"]["langfuse_session_id"] == "conv-123" == body["conversation_id"]
    assert config["metadata"]["langfuse_trace_name"] == "insights.chat"
    # Un span raíz para el chat y uno para el gate, en el mismo trace.
    names = [c.kwargs["name"] for c in client_mock.start_as_current_observation.call_args_list]
    assert names == ["insights.chat", "gate.me"]


def test_no_config_metadata_without_callbacks(monkeypatch):
    _tracing_off(monkeypatch)
    captured = {}

    class StubGraph:
        async def ainvoke(self, inputs, config=None):
            captured["config"] = config
            return {"messages": [AIMessage(content="ok")]}

    monkeypatch.setattr(agent, "_graph", StubGraph())
    _chat(TestClient(app))
    assert "callbacks" not in captured["config"]
    assert "metadata" not in captured["config"]


def test_health_opens_no_span(monkeypatch):
    _tracing_on(monkeypatch)
    with patch("langfuse.get_client") as get_client:
        resp = TestClient(app).get("/health")
    assert resp.status_code == 200
    get_client.assert_not_called()


def test_flush_on_shutdown_only(monkeypatch):
    _tracing_off(monkeypatch)
    with patch("insights.main.flush_traces") as flush:
        with TestClient(app) as client:
            _chat(client)
            flush.assert_not_called()  # no hay flush por request
        flush.assert_called_once()


def test_trace_span_off_yields_none_without_importing_sdk(monkeypatch):
    _tracing_off(monkeypatch)
    with patch("langfuse.get_client") as get_client:
        with trace_span("x") as span:
            assert span is None
    get_client.assert_not_called()


def test_trace_span_propagates_body_exception(monkeypatch):
    _tracing_on(monkeypatch)
    with patch("langfuse.get_client", return_value=MagicMock()):
        with pytest.raises(ValueError, match="boom"):
            with trace_span("x"):
                raise ValueError("boom")
