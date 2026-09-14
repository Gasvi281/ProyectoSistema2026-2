"""
jwt_provider.py
---------------
Proveedor de JWT de Supabase para autenticación de la cuenta de servicio del bot.

Hace login con BOT_EMAIL/BOT_PASSWORD contra el endpoint de Supabase Auth
(POST /auth/v1/token?grant_type=password) y renueva el token de forma proactiva
antes de que expire, para que las sesiones largas no fallen silenciosamente con
un token caducado.

Diseñado como módulo independiente (tarea 3.9); la integración en get_auth_headers()
queda para la siguiente tarea.

Decisiones de diseño:
  - El constructor solo acepta el callable de reloj (now). No lee ni valida
    variables de entorno en __init__ — esa validación ocurre de forma perezosa
    en _login(), igual que check_backend_config() se llama en tiempo de request.
  - La inyección del reloj (now: Callable[[], datetime]) permite testear la
    lógica de expiración sin dependencias externas ni freezegun.
  - Se llama a resp.raise_for_status() antes de parsear el cuerpo para que
    credenciales inválidas lancen httpx.HTTPStatusError, no KeyError.
"""

import os
from datetime import datetime, timedelta, timezone
from typing import Callable

import httpx

# Cuántos segundos antes de la expiración real se considera que el token ya
# "caducó" a efectos de renovación proactiva. Evita enviar requests con un
# token que expirará en segundos.
_REFRESH_SKEW_SECONDS = 60


def _default_now() -> datetime:
    """Reloj de producción — sustituible en tests con un callable falso."""
    return datetime.now(timezone.utc)


class SupabaseJwtProvider:
    """
    Mantiene un token JWT de Supabase válido para la cuenta de servicio del bot.

    Uso típico:
        provider = SupabaseJwtProvider()
        token = await provider.get_token()
        headers = {"Authorization": f"Bearer {token}"}

    En tests, pasa un ``now`` falso para controlar el reloj:
        fake_time = [datetime(2026, 1, 1, tzinfo=timezone.utc)]
        provider = SupabaseJwtProvider(now=lambda: fake_time[0])
    """

    def __init__(self, *, now: Callable[[], datetime] = _default_now):
        # El constructor SOLO acepta el reloj. No toca variables de entorno —
        # la validación es perezosa (ocurre en _login en el primer uso).
        self._now = now
        self._token: str | None = None
        self._expires_at: datetime | None = None

    async def get_token(self) -> str:
        """
        Devuelve un token JWT vigente.

        Si no hay token en caché o está a punto de expirar (dentro de
        _REFRESH_SKEW_SECONDS), hace login de nuevo y actualiza la caché.
        """
        if self._needs_refresh():
            await self._login()
        # _login() garantiza que _token no es None en este punto.
        assert self._token is not None  # para los type checkers
        return self._token

    def _needs_refresh(self) -> bool:
        """True si no hay token o si ya pasó el umbral de renovación proactiva."""
        if self._token is None or self._expires_at is None:
            return True
        skew = timedelta(seconds=_REFRESH_SKEW_SECONDS)
        return self._now() >= self._expires_at - skew

    async def _login(self) -> None:
        """
        Hace POST al endpoint de Supabase Auth y actualiza _token / _expires_at.

        Lee y valida las cuatro variables de entorno de forma perezosa (en la
        primera llamada real, no en __init__). Lanza ValueError si falta alguna,
        y httpx.HTTPStatusError si el servidor responde con 4xx/5xx.
        """
        # --- Validación perezosa de variables de entorno ---
        supabase_url = os.getenv("SUPABASE_URL", "").rstrip("/")
        anon_key = os.getenv("SUPABASE_ANON_KEY", "")
        bot_email = os.getenv("BOT_EMAIL", "")
        bot_password = os.getenv("BOT_PASSWORD", "")

        faltantes = [
            nombre
            for nombre, valor in [
                ("SUPABASE_URL", supabase_url),
                ("SUPABASE_ANON_KEY", anon_key),
                ("BOT_EMAIL", bot_email),
                ("BOT_PASSWORD", bot_password),
            ]
            if not valor
        ]
        if faltantes:
            raise ValueError(
                f"Faltan variables de entorno para autenticación Supabase: "
                f"{', '.join(faltantes)}"
            )

        # --- Login contra Supabase Auth ---
        # Se usa un timeout más generoso (60 s) porque el backend en Render
        # puede tardar 30-50 s en despertar desde un cold start.
        url = f"{supabase_url}/auth/v1/token"
        headers = {
            "apikey": anon_key,
            "Content-Type": "application/json",
        }
        body = {"email": bot_email, "password": bot_password}

        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                url,
                json=body,
                headers=headers,
                params={"grant_type": "password"},
            )
            # raise_for_status ANTES de parsear — si las credenciales son
            # inválidas el servidor devuelve 400/401 con un cuerpo de error,
            # y el caller recibiría un KeyError en vez de HTTPStatusError.
            resp.raise_for_status()
            data = resp.json()

        self._token = data["access_token"]
        expires_in: int = data.get("expires_in", 3600)
        self._expires_at = self._now() + timedelta(seconds=expires_in)
