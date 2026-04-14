import logging

import httpx

logger = logging.getLogger(__name__)


class STS2Client:
    def __init__(self, base_url: str) -> None:
        self._base_url = base_url.rstrip("/")
        self._http = httpx.AsyncClient(timeout=5.0)

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._http.aclose()

    async def get_state(self) -> dict | None:
        """Fetch current game state from STS2MCP. Returns parsed JSON or None on failure."""
        try:
            response = await self._http.get(f"{self._base_url}/api/v1/singleplayer")
            if response.is_success:
                return response.json()
            logger.warning("STS2MCP API returned status %s", response.status_code)
            return None
        except (httpx.ConnectError, httpx.TimeoutException):
            return None
