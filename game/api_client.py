import logging

import httpx

logger = logging.getLogger(__name__)


class STS2Client:
    def __init__(self, base_url: str) -> None:
        self._base_url = base_url.rstrip("/")

    async def ping(self) -> bool:
        """Ping the STS2MCP API. Returns True on success, False on failure."""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{self._base_url}/state")
            if response.is_success:
                logger.info("STS2MCP API reachable at %s", self._base_url)
                return True
            logger.warning("STS2MCP API returned status %s", response.status_code)
            return False
        except httpx.ConnectError:
            logger.warning("STS2MCP API not reachable at %s — is STS2 running?", self._base_url)
            return False
        except httpx.TimeoutException:
            logger.warning("STS2MCP API timed out at %s", self._base_url)
            return False
