"""Tracing opcional con Langfuse para el agente LangGraph.

Se activa solo si LANGFUSE_PUBLIC_KEY y LANGFUSE_SECRET_KEY están presentes.
Si faltan, todo queda como no-op: sin handler, sin warnings, sin efectos al
importar. Además es fail-open: cualquier error creando el handler o haciendo
flush se traga aquí y nunca sube a handle_turn.
"""
import logging
import os

logger = logging.getLogger("agent.observability")


def _tracing_enabled() -> bool:
    return bool(
        os.getenv("LANGFUSE_PUBLIC_KEY") and os.getenv("LANGFUSE_SECRET_KEY")
    )


def get_langfuse_callbacks() -> list:
    """Devuelve [CallbackHandler()] si el tracing está activo, [] en caso contrario.

    El CallbackHandler lee LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY /
    LANGFUSE_BASE_URL del entorno por su cuenta.
    """
    if not _tracing_enabled():
        return []
    try:
        from langfuse.langchain import CallbackHandler

        return [CallbackHandler()]
    except Exception:
        logger.warning(
            "Langfuse deshabilitado: no se pudo crear el CallbackHandler",
            exc_info=True,
        )
        return []


def flush_traces() -> None:
    """Vacía las trazas pendientes. No-op si el tracing está deshabilitado."""
    if not _tracing_enabled():
        return
    try:
        from langfuse import get_client

        get_client().flush()
    except Exception:
        logger.warning("Langfuse flush falló", exc_info=True)
