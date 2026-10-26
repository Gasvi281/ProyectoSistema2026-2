"""Límites de reintentos/timeout del LLM y mapeo de fallos a 502 (sin red)."""
import httpx
import pytest
from fastapi.testclient import TestClient
from langchain_core.exceptions import ModelError

from insights import agent, backend, config
from insights.main import app
from shared.llm import get_langchain_llm


class _RecordingChat:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


@pytest.fixture
def recording_gemini(monkeypatch):
    import langchain_google_genai

    monkeypatch.setattr(langchain_google_genai, "ChatGoogleGenerativeAI", _RecordingChat)
    monkeypatch.setenv("GEMINI_API_KEY", "k")


def test_get_langchain_llm_passes_limits_when_given(recording_gemini):
    llm = get_langchain_llm("gemini", max_retries=1, timeout=60.0)
    assert llm.kwargs["max_retries"] == 1
    assert llm.kwargs["timeout"] == 60.0


def test_get_langchain_llm_omits_limits_when_none(recording_gemini):
    llm = get_langchain_llm("gemini")
    assert "max_retries" not in llm.kwargs
    assert "timeout" not in llm.kwargs


def test_config_defaults(monkeypatch):
    monkeypatch.delenv("INSIGHTS_LLM_MAX_RETRIES", raising=False)
    monkeypatch.delenv("INSIGHTS_LLM_TIMEOUT", raising=False)
    assert config.llm_max_retries() == 1
    assert config.llm_timeout() == 60.0


def test_config_env_overrides(monkeypatch):
    monkeypatch.setenv("INSIGHTS_LLM_MAX_RETRIES", "3")
    monkeypatch.setenv("INSIGHTS_LLM_TIMEOUT", "12.5")
    assert config.llm_max_retries() == 3
    assert config.llm_timeout() == 12.5


def test_config_max_retries_never_below_one(monkeypatch):
    monkeypatch.setenv("INSIGHTS_LLM_MAX_RETRIES", "0")
    assert config.llm_max_retries() == 1


class _FailingGraph:
    def __init__(self, exc):
        self.exc = exc

    async def ainvoke(self, *args, **kwargs):
        raise self.exc


def _me_handler(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json={"role": "TEAM_ADMIN", "active": True})


@pytest.mark.parametrize("exc", [ModelError("503 UNAVAILABLE"), httpx.ReadTimeout("timeout")])
def test_llm_failure_returns_502(monkeypatch, exc):
    monkeypatch.setattr(backend, "_transport", httpx.MockTransport(_me_handler))
    monkeypatch.setattr(agent, "get_graph", lambda: _FailingGraph(exc))

    resp = TestClient(app).post(
        "/insights/chat",
        json={"message": "hi"},
        headers={"Authorization": "Bearer t"},
    )

    assert resp.status_code == 502
    assert resp.json() == {"detail": "Backend unavailable"}
