import logging

import httpx

logger = logging.getLogger(__name__)


class MenuClient:
    def __init__(self, base_url: str, http_timeout: float = 5.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._http = httpx.AsyncClient(timeout=http_timeout)

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._http.aclose()

    async def get_menu_state(self) -> dict | None:
        """Fetch current menu screen state from STS2-MenuControl. Returns parsed JSON or None on failure."""
        try:
            response = await self._http.get(f"{self._base_url}/api/v1/menu")
            if response.is_success:
                return response.json()
            logger.warning("MenuControl API returned status %s", response.status_code)
            return None
        except (httpx.ConnectError, httpx.TimeoutException):
            return None

    async def post_menu_action(
        self, action: str, option_index: int | None = None
    ) -> dict | None:
        """Execute a menu action via STS2-MenuControl. Returns parsed JSON or None on failure."""
        body: dict = {"action": action}
        if option_index is not None:
            body["option_index"] = option_index
        try:
            response = await self._http.post(
                f"{self._base_url}/api/v1/menu", json=body
            )
            if response.is_success:
                return response.json()
            logger.warning(
                "MenuControl action POST returned status %s: %s",
                response.status_code,
                response.text,
            )
            return None
        except (httpx.ConnectError, httpx.TimeoutException):
            return None
