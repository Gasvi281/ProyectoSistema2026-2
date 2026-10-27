"""Helper HTTP async compartido. Sin lógica de auth: el caller pasa los headers."""
import httpx

# 60 s: el backend en Render puede tardar 30-50 s en un cold start.
TIMEOUT_SECONDS = 60.0


async def get(
    base_url: str,
    path: str,
    *,
    headers: dict,
    params: dict | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> httpx.Response:
    """GET contra base_url + path. Devuelve la respuesta cruda (sin raise_for_status)."""
    async with httpx.AsyncClient(
        base_url=base_url, timeout=TIMEOUT_SECONDS, transport=transport
    ) as client:
        return await client.get(path, headers=headers, params=params)
