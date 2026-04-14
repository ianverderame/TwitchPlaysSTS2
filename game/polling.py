import asyncio
import logging

from game.api_client import STS2Client
from game.events import GameEndedEvent, GameStartedEvent, GameEvent, VoteNeededEvent
from game.state import GameState

logger = logging.getLogger(__name__)


async def poll_game_state(
    client: STS2Client,
    interval: float,
    event_queue: asyncio.Queue[GameEvent],
) -> None:
    """Poll STS2MCP every `interval` seconds and emit typed GameEvents on state transitions."""
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
                    if previous_state_type == "menu" and state.state_type != "menu":
                        event_queue.put_nowait(GameStartedEvent(state))
                    elif state.state_type == "game_over":
                        event_queue.put_nowait(GameEndedEvent(state))
                    elif state.requires_player_input():
                        logger.info("Queuing vote for state: %s", state.state_type)
                        event_queue.put_nowait(VoteNeededEvent(state))
                    previous_state_type = state.state_type
        except Exception:
            logger.error("Unexpected error in polling loop", exc_info=True)
        await asyncio.sleep(interval)
