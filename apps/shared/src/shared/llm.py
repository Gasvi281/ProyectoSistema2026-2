"""LLM integration with LangChain."""
import os
from abc import ABC, abstractmethod
from langchain_core.language_models import LLM

class FakeLLM(LLM):
    """Fake LLM for testing - keyword based."""
    
    @property
    def _llm_type(self) -> str:
        return "fake"
    
    def _call(self, prompt: str, stop=None, **kwargs) -> str:
        prompt_lower = prompt.lower()
        if "search" in prompt_lower or "looking for" in prompt_lower:
            return "I found several properties matching your criteria."
        if "schedule" in prompt_lower or "visit" in prompt_lower:
            return "I can help you schedule a visit."
        if "price" in prompt_lower:
            return "Price information is available from property details."
        return "I understand. What are you looking for?"

class GeminiLLMProvider:
    """Gemini LLM provider via LangChain."""
    
    @staticmethod
    def get_gemini_llm(max_retries: int | None = None, timeout: float | None = None):
        """Get ChatGoogleGenerativeAI instance.

        max_retries: intentos totales (1 = sin reintentos). timeout: segundos por intento.
        Si son None se usan los defaults de la librería.
        """
        try:
            from langchain_google_genai import ChatGoogleGenerativeAI
        except ImportError:
            raise RuntimeError("Install langchain-google-genai")
        
        api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        model_name = os.getenv("GEMINI_MODEL", "gemini-3.6-flash")

        if not api_key:
            raise ValueError("GEMINI_API_KEY o GOOGLE_API_KEY no está configurado")
        
        extra = {}
        if max_retries is not None:
            extra["max_retries"] = max_retries
        if timeout is not None:
            extra["timeout"] = timeout

        return ChatGoogleGenerativeAI(
            model=model_name,
            google_api_key=api_key,
            #temperature=0.7,
            #max_tokens=512,
            **extra,
        )

def get_langchain_llm(
    mode: str | None = None,
    max_retries: int | None = None,
    timeout: float | None = None,
):
    """Get LLM for `mode`; if None, based on AGENT_LLM_MODE."""
    mode = (mode or os.getenv("AGENT_LLM_MODE", "fake")).lower()

    if mode == "fake":
        return FakeLLM()
    elif mode == "gemini":
        return GeminiLLMProvider.get_gemini_llm(max_retries=max_retries, timeout=timeout)
    else:
        raise ValueError(f"Invalid AGENT_LLM_MODE: {mode}")
