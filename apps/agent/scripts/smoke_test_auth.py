"""
smoke_test_auth.py
------------------
Prueba manual de login JWT contra Supabase real.
NO es parte del suite de pytest — hace llamadas de red reales.

Uso:
    cd apps/agent
    .\\venv\\Scripts\\Activate.ps1
    python scripts/smoke_test_auth.py
"""

import asyncio
import os
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent   # abs path to scripts/
_AGENT_DIR  = _SCRIPT_DIR.parent               # abs path to apps/agent/

# Permite importar agent.* sin instalar el paquete en modo editable
sys.path.insert(0, str(_AGENT_DIR / "src"))

from dotenv import load_dotenv
_env_path = _AGENT_DIR / ".env"
loaded = load_dotenv(_env_path)
print(f"[config] .env path : {_env_path}")
print(f"[config] .env loaded: {loaded}")
_auth_keys = ["BOT_EMAIL", "BOT_PASSWORD", "SUPABASE_URL", "SUPABASE_ANON_KEY",
              "BACKEND_URL", "BACKEND_SERVICE_TOKEN", "DEV_AGENT_ID"]
print(f"[config] vars present: {[k for k in _auth_keys if os.getenv(k)]}\n")

import httpx
from agent.backend_auth import get_auth_headers


AGENT_ID = "c7b5b2bc-5a8a-4eca-9a50-aec3aabc25fa"


async def main() -> None:
    # ------------------------------------------------------------------ #
    # Step 1: login JWT                                                    #
    # ------------------------------------------------------------------ #
    print("=== Step 1: login JWT ===\n")
    agency_id = os.getenv("AGENCY_ID")
    try:
        headers = await get_auth_headers(agency_id=agency_id)
    except ValueError as exc:
        print(f"[FAIL] ValueError (variable de entorno faltante): {exc}")
        return
    except httpx.TimeoutException as exc:
        print(f"[FAIL] Timeout conectando a Supabase: {exc}")
        return
    except httpx.HTTPStatusError as exc:
        print(f"[FAIL] HTTP {exc.response.status_code} de Supabase Auth")
        print(f"       URL: {exc.request.url}")
        return
    except Exception as exc:
        print(f"[FAIL] Error inesperado ({type(exc).__name__}): {exc}")
        return

    print("[OK] get_auth_headers() completó sin excepción")
    print(f"     Headers presentes: {list(headers.keys())}")
    auth_value = headers.get("Authorization", "")
    if auth_value.startswith("Bearer "):
        token = auth_value[len("Bearer "):]
        print(f"     Authorization: Bearer <token len={len(token)}, inicio={token[:20]}...>")
    elif "X-Dev-Agent-Id" in headers:
        print("     Modo: DEV bypass (X-Dev-Agent-Id) — no es live JWT")
    if agency_id:
        print(f"     X-Agency-Id: {headers.get('X-Agency-Id', '(ausente)')}")

    # ------------------------------------------------------------------ #
    # Step 2: GET /agents/{agent_id}/slots — 3-way probe                  #
    #                                                                      #
    # Objetivo: determinar empíricamente si /slots exige X-Agency-Id y    #
    # si valida el valor contra la agencia real del agente.               #
    #                                                                      #
    # Variante A: X-Agency-Id = AGENCY_ID del caller (valor del .env).    #
    # Variante B: sin X-Agency-Id (¿es el header obligatorio?).           #
    # Variante C: X-Agency-Id = UUID falso (¿valida el backend el valor?) #
    # ------------------------------------------------------------------ #
    print(f"\n=== Step 2: GET /agents/{AGENT_ID}/slots (3-way probe) ===\n")
    backend_url = os.getenv("BACKEND_URL", "").rstrip("/")
    date_from = "2026-09-14T00:00:00Z"
    date_to   = "2026-09-21T23:59:59Z"
    slots_url = f"{backend_url}/agents/{AGENT_ID}/slots"

    # Cabeceras de auth sin X-Agency-Id (base limpia para armar variantes).
    auth_only_headers = {k: v for k, v in headers.items() if k != "X-Agency-Id"}

    probe_variants = [
        ("A — X-Agency-Id = AGENCY_ID (caller)",     {**auth_only_headers, "X-Agency-Id": os.getenv("AGENCY_ID", "")}),
        ("B — sin X-Agency-Id",                       auth_only_headers),
        ("C — X-Agency-Id = UUID falso",              {**auth_only_headers, "X-Agency-Id": "00000000-0000-0000-0000-000000000000"}),
    ]

    async with httpx.AsyncClient(timeout=60.0) as client:
        for label, probe_headers in probe_variants:
            print(f"--- Variante {label} ---")
            print(f"[request] headers enviados : {list(probe_headers.keys())}")
            agency_sent = probe_headers.get("X-Agency-Id", "(ausente)")
            print(f"[request] X-Agency-Id      : {agency_sent}")
            try:
                resp = await client.get(
                    slots_url,
                    params={"from": date_from, "to": date_to},
                    headers=probe_headers,
                )
                print(f"[response] status : {resp.status_code}")
                print(f"[response] body   : {resp.text!r}")
                if resp.status_code == 200:
                    data = resp.json()
                    slots = data.get("slots", [])
                    print(f"     slot_minutes: {data.get('slot_minutes')}")
                    print(f"     slots count : {len(slots)}")
                    if slots:
                        print(f"     primer slot : {slots[0]}")
            except httpx.TimeoutException as exc:
                print(f"[FAIL] Timeout (cold start?): {exc}")
            except Exception as exc:
                print(f"[FAIL] Error inesperado ({type(exc).__name__}): {exc}")
            print()


asyncio.run(main())
