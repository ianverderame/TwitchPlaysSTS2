import asyncio
import logging
from collections.abc import Callable, Awaitable

import httpx

logger = logging.getLogger(__name__)


class STS2Client:
    def __init__(
        self,
        base_url: str,
        dry_run: bool = False,
        http_timeout: float = 5.0,
        http_retry_attempts: int = 3,
        http_retry_backoff_seconds: float = 0.5,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._http = httpx.AsyncClient(timeout=http_timeout)
        self.dry_run = dry_run
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

    async def get_state(self) -> dict | None:
        """Fetch current game state from STS2MCP. Returns parsed JSON or None on failure."""
        response = await self._retry(
            "STS2MCP GET",
            lambda: self._http.get(f"{self._base_url}/api/v1/singleplayer"),
        )
        if response is None:
            return None
        if response.is_success:
            return response.json()
        logger.warning("STS2MCP API returned status %s", response.status_code)
        return None

    async def post_action(self, body: dict) -> dict | None:
        """Submit a player action to STS2MCP. Returns parsed JSON or None on failure.

        In dry-run mode, logs the action and returns a synthetic ok response
        without touching the API — game state is unchanged.
        """
        if self.dry_run:
            logger.info("[DRY RUN] Skipping action: %s", body)
            return {"status": "ok", "message": f"[DRY RUN] {body}"}
        response = await self._retry(
            "STS2MCP POST",
            lambda: self._http.post(f"{self._base_url}/api/v1/singleplayer", json=body),
        )
        if response is None:
            return None
        if response.is_success:
            return response.json()
        logger.warning(
            "STS2MCP action POST returned status %s: %s",
            response.status_code,
            response.text,
        )
        return None
