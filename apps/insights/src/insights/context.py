"""Estado por request. El token nunca pasa por el modelo: las tools lo leen de aquí."""
from contextvars import ContextVar

auth_header: ContextVar[str] = ContextVar("auth_header", default="")
sources: ContextVar[list[dict]] = ContextVar("sources")
