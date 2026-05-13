import logging

import httpx

from game._http import fetch_json

logger = logging.getLogger(__name__)


class MenuClient:
    def __init__(
        self,
        base_url: str,
        http_timeout: float = 5.0,
        http_retry_attempts: int = 3,
        http_retry_backoff_seconds: float = 0.5,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._http = httpx.AsyncClient(timeout=http_timeout)
        self._http_retry_attempts = http_retry_attempts
        self._http_retry_backoff_seconds = http_retry_backoff_seconds

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._http.aclose()

    async def get_menu_state(self) -> dict | None:
        """Fetch current menu screen state from STS2-MenuControl. Returns parsed JSON or None on failure."""
        return await fetch_json(
            label="MenuControl GET",
            bad_status_label="MenuControl API",
            coro_factory=lambda: self._http.get(f"{self._base_url}/api/v1/menu"),
            attempts=self._http_retry_attempts,
            backoff_seconds=self._http_retry_backoff_seconds,
            logger=logger,
        )

    async def post_menu_action(
        self, action: str, option_index: int | None = None
    ) -> dict | None:
        """Execute a menu action via STS2-MenuControl. Returns parsed JSON or None on failure."""
        body: dict = {"action": action}
        if option_index is not None:
            body["option_index"] = option_index
        return await fetch_json(
            label="MenuControl POST",
            bad_status_label="MenuControl action POST",
            coro_factory=lambda: self._http.post(f"{self._base_url}/api/v1/menu", json=body),
            attempts=self._http_retry_attempts,
            backoff_seconds=self._http_retry_backoff_seconds,
            logger=logger,
        )
