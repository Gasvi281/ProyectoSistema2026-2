"""Solo dev: imprime el access_token de Supabase de un TEAM_ADMIN de prueba.

Lee SUPABASE_URL, SUPABASE_ANON_KEY, INSIGHTS_DEV_EMAIL e INSIGHTS_DEV_PASSWORD
de apps/insights/.env. Imprime únicamente el token (nada más va a stdout).
"""
import os
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

NAMES = ("SUPABASE_URL", "SUPABASE_ANON_KEY", "INSIGHTS_DEV_EMAIL", "INSIGHTS_DEV_PASSWORD")


def main() -> int:
    env = {n: os.getenv(n, "") for n in NAMES}
    missing = [n for n, v in env.items() if not v]
    if missing:
        print(f"Faltan variables en apps/insights/.env: {', '.join(missing)}", file=sys.stderr)
        return 1

    resp = httpx.post(
        f"{env['SUPABASE_URL'].rstrip('/')}/auth/v1/token",
        params={"grant_type": "password"},
        headers={"apikey": env["SUPABASE_ANON_KEY"]},
        json={"email": env["INSIGHTS_DEV_EMAIL"], "password": env["INSIGHTS_DEV_PASSWORD"]},
        timeout=60.0,
    )
    if resp.status_code != 200:
        # Solo el status: el cuerpo/credenciales no se imprimen.
        print(f"Login falló: HTTP {resp.status_code}", file=sys.stderr)
        return 1
    print(resp.json()["access_token"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
