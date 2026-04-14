import asyncio
import logging

from game.api_client import STS2Client
from game.state import GameState

logger = logging.getLogger(__name__)


async def poll_game_state(client: STS2Client, interval: float) -> None:
    """Poll STS2MCP every `interval` seconds and log state_type transitions."""
    previous_state_type: str | None = None
    api_reachable: bool = True

    while True:
        try:
            data = await client.get_state()
            if data is None:
                if api_reachable:
                    logger.warning("STS2MCP API unreachable — waiting for STS2 to start")
                    api_reachable = False
            else:
                if not api_reachable:
                    logger.info("STS2MCP API reconnected")
                    api_reachable = True
                state = GameState.from_api_response(data)
                if state.state_type != previous_state_type:
                    logger.info("Game state changed: %s", state.summary())
                    previous_state_type = state.state_type
        except Exception:
            logger.error("Unexpected error in polling loop", exc_info=True)
        await asyncio.sleep(interval)
