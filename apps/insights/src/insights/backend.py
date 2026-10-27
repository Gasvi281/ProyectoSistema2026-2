"""Cliente del backend: reenvía el JWT del request tal cual. Sin X-Agency-Id."""
import httpx

from shared import http
from insights import config
from insights.context import auth_header

# Los tests inyectan un httpx.MockTransport aquí.
_transport: httpx.AsyncBaseTransport | None = None


async def backend_get(
    path: str, params: dict | None = None, *, authorization: str | None = None
) -> httpx.Response:
    headers = {"Authorization": authorization or auth_header.get()}
    return await http.get(
        config.backend_url(), path, headers=headers, params=params, transport=_transport
    )
