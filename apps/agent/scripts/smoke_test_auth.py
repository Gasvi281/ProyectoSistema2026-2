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
    # Step 2: GET /agents/{agent_id}/slots (solo lectura)                 #
    # ------------------------------------------------------------------ #
    print(f"\n=== Step 2: GET /agents/{AGENT_ID}/slots ===\n")
    backend_url = os.getenv("BACKEND_URL", "").rstrip("/")
    date_from = "2026-09-14T00:00:00Z"
    date_to   = "2026-09-21T23:59:59Z"
    url = f"{backend_url}/agents/{AGENT_ID}/slots"

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            req = client.build_request(
                "GET", url,
                params={"from": date_from, "to": date_to},
                headers=headers,
            )
            print(f"[request] method  : {req.method}")
            print(f"[request] url     : {req.url}")
            print(f"[request] headers : {list(req.headers.keys())}")
            resp = await client.send(req)
        print(f"\n[response] status : {resp.status_code}")
        print(f"[response] body   : {resp.text!r}")
        resp.raise_for_status()
        data = resp.json()
        slots = data.get("slots", [])
        print(f"     agent_id    : {data.get('agent_id')}")
        print(f"     slot_minutes: {data.get('slot_minutes')}")
        print(f"     slots count : {len(slots)}")
        if slots:
            print(f"     primer slot : {slots[0]}")
            print(f"     último slot : {slots[-1]}")
        print("\n[OK] Llamada autenticada al backend completada.")
    except httpx.HTTPStatusError as exc:
        print(f"[FAIL] HTTP {exc.response.status_code} del backend")
        print(f"       URL: {exc.request.url}")
        try:
            print(f"       Body: {exc.response.json()}")
        except Exception:
            print(f"       Body (raw): {exc.response.text[:200]}")
    except httpx.TimeoutException as exc:
        print(f"[FAIL] Timeout conectando al backend (cold start?): {exc}")
    except Exception as exc:
        print(f"[FAIL] Error inesperado ({type(exc).__name__}): {exc}")


asyncio.run(main())
