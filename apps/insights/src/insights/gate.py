"""Gate previo a cualquier llamada al LLM: solo TEAM_ADMIN activos."""
import httpx
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from insights.backend import backend_get
from shared.observability import trace_span

# auto_error=False: sin header respondemos 401 nosotros (HTTPBearer daría 403).
_bearer = HTTPBearer(auto_error=False)


async def require_team_admin(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> str:
    """Valida el token contra GET /me y devuelve el header Authorization a reenviar."""
    if credentials is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    authorization = f"Bearer {credentials.credentials}"

    try:
        with trace_span("gate.me"):
            resp = await backend_get("/me", authorization=authorization)
    except httpx.RequestError:
        raise HTTPException(status_code=502, detail="Backend unavailable")

    # Se mapea solo por status HTTP, nunca por `code`/`detail` del backend.
    if resp.status_code == 401:
        raise HTTPException(status_code=401, detail="Not authenticated")
    if resp.status_code == 403:
        raise HTTPException(status_code=403, detail="Forbidden")
    if resp.status_code != 200:
        raise HTTPException(status_code=502, detail="Backend unavailable")

    me = resp.json()
    if me.get("role") != "TEAM_ADMIN" or me.get("active") is False:
        raise HTTPException(status_code=403, detail="Forbidden")
    return authorization
