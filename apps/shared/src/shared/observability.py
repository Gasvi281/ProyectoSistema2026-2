"""Tracing opcional con Langfuse para el agente LangGraph.

Se activa solo si LANGFUSE_PUBLIC_KEY y LANGFUSE_SECRET_KEY están presentes.
Si faltan, todo queda como no-op: sin handler, sin warnings, sin efectos al
importar. Además es fail-open: cualquier error creando el handler o haciendo
flush se traga aquí y nunca sube a handle_turn.
"""
import logging
import os
import sys
from contextlib import contextmanager

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


@contextmanager
def trace_span(name: str):
    """Abre un span de Langfuse como span OTel actual (los hijos se anidan en él).

    No-op sin keys y fail-open: un error del SDK al abrir o cerrar se registra
    y se ignora; nunca oculta la excepción del cuerpo.
    """
    if not _tracing_enabled():
        yield None
        return
    try:
        from langfuse import get_client

        cm = get_client().start_as_current_observation(name=name, as_type="span")
        span = cm.__enter__()
    except Exception:
        logger.warning("Langfuse span %s deshabilitado", name, exc_info=True)
        yield None
        return
    try:
        yield span
    finally:
        try:
            cm.__exit__(*sys.exc_info())
        except Exception:
            logger.warning("Langfuse span %s no se pudo cerrar", name, exc_info=True)
