import logging

import httpx

from game._http import fetch_json

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

    async def get_state(self) -> dict | None:
        """Fetch current game state from STS2MCP. Returns parsed JSON or None on failure."""
        return await fetch_json(
            label="STS2MCP GET",
            bad_status_label="STS2MCP API",
            coro_factory=lambda: self._http.get(f"{self._base_url}/api/v1/singleplayer"),
            attempts=self._http_retry_attempts,
            backoff_seconds=self._http_retry_backoff_seconds,
            logger=logger,
        )

    async def post_action(self, body: dict) -> dict | None:
        """Submit a player action to STS2MCP. Returns parsed JSON or None on failure.

        In dry-run mode, logs the action and returns a synthetic ok response
        without touching the API — game state is unchanged.
        """
        if self.dry_run:
            logger.info("[DRY RUN] Skipping action: %s", body)
            return {"status": "ok", "message": f"[DRY RUN] {body}"}
        return await fetch_json(
            label="STS2MCP POST",
            bad_status_label="STS2MCP action POST",
            coro_factory=lambda: self._http.post(f"{self._base_url}/api/v1/singleplayer", json=body),
            attempts=self._http_retry_attempts,
            backoff_seconds=self._http_retry_backoff_seconds,
            logger=logger,
        )
