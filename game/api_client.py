import logging

import httpx

logger = logging.getLogger(__name__)


class STS2Client:
    def __init__(self, base_url: str, dry_run: bool = False, http_timeout: float = 5.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._http = httpx.AsyncClient(timeout=http_timeout)
        self.dry_run = dry_run

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

    async def post_action(self, body: dict) -> dict | None:
        """Submit a player action to STS2MCP. Returns parsed JSON or None on failure.

        In dry-run mode, logs the action and returns a synthetic ok response
        without touching the API — game state is unchanged.
        """
        if self.dry_run:
            logger.info("[DRY RUN] Skipping action: %s", body)
            return {"status": "ok", "message": f"[DRY RUN] {body}"}
        try:
            response = await self._http.post(
                f"{self._base_url}/api/v1/singleplayer", json=body
            )
            if response.is_success:
                return response.json()
            logger.warning(
                "STS2MCP action POST returned status %s: %s",
                response.status_code,
                response.text,
            )
            return None
        except (httpx.ConnectError, httpx.TimeoutException):
            return None
