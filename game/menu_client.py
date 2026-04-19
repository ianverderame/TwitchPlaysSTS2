import asyncio
import logging
from collections.abc import Callable, Awaitable

import httpx

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

    async def _retry(
        self,
        label: str,
        coro_factory: Callable[[], Awaitable[httpx.Response]],
    ) -> httpx.Response | None:
        """Execute coro_factory() with exponential backoff retry on transient failures.

        Retries up to `http_retry_attempts` times on ConnectError or TimeoutException.
        Returns None when all attempts are exhausted.
        """
        for attempt in range(self._http_retry_attempts + 1):
            try:
                return await coro_factory()
            except (httpx.ConnectError, httpx.TimeoutException) as exc:
                if attempt < self._http_retry_attempts:
                    delay = self._http_retry_backoff_seconds * (2 ** attempt)
                    logger.warning(
                        "%s: transient error (%s) — retry %d/%d in %.1fs",
                        label, type(exc).__name__, attempt + 1, self._http_retry_attempts, delay,
                    )
                    await asyncio.sleep(delay)
        return None

    async def get_menu_state(self) -> dict | None:
        """Fetch current menu screen state from STS2-MenuControl. Returns parsed JSON or None on failure."""
        response = await self._retry(
            "MenuControl GET",
            lambda: self._http.get(f"{self._base_url}/api/v1/menu"),
        )
        if response is None:
            return None
        if response.is_success:
            return response.json()
        logger.warning("MenuControl API returned status %s", response.status_code)
        return None

    async def post_menu_action(
        self, action: str, option_index: int | None = None
    ) -> dict | None:
        """Execute a menu action via STS2-MenuControl. Returns parsed JSON or None on failure."""
        body: dict = {"action": action}
        if option_index is not None:
            body["option_index"] = option_index
        response = await self._retry(
            "MenuControl POST",
            lambda: self._http.post(f"{self._base_url}/api/v1/menu", json=body),
        )
        if response is None:
            return None
        if response.is_success:
            return response.json()
        logger.warning(
            "MenuControl action POST returned status %s: %s",
            response.status_code,
            response.text,
        )
        return None
