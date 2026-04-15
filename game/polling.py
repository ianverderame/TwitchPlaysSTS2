import asyncio
import logging

from game.api_client import STS2Client
from game.events import GameEndedEvent, GameStartedEvent, GameEvent, MenuSelectNeededEvent, VoteNeededEvent
from game.state import GameState

logger = logging.getLogger(__name__)


def _log_within_state_changes(prev: GameState, curr: GameState) -> None:
    """Log meaningful field-level changes when state_type hasn't changed."""
    if curr.player_hp != prev.player_hp and curr.player_hp is not None:
        logger.info(
            "Player HP: %s → %s/%s",
            prev.player_hp,
            curr.player_hp,
            curr.player_max_hp,
        )
    if curr.player_block != prev.player_block and curr.player_block is not None:
        logger.info("Player block: %s → %s", prev.player_block, curr.player_block)
    if curr.player_energy != prev.player_energy and curr.player_energy is not None:
        logger.info("Player energy: %s → %s", prev.player_energy, curr.player_energy)

    for i, enemy in enumerate(curr.enemies):
        if i >= len(prev.enemies):
            break
        prev_enemy = prev.enemies[i]
        if enemy.get("hp") != prev_enemy.get("hp"):
            logger.info(
                "%s HP: %s → %s",
                enemy.get("name", f"Enemy {i}"),
                prev_enemy.get("hp"),
                enemy.get("hp"),
            )
        if enemy.get("block") != prev_enemy.get("block"):
            logger.info(
                "%s block: %s → %s",
                enemy.get("name", f"Enemy {i}"),
                prev_enemy.get("block"),
                enemy.get("block"),
            )


async def poll_game_state(
    client: STS2Client,
    interval: float,
    event_queue: asyncio.Queue[GameEvent],
) -> None:
    """Poll STS2MCP every `interval` seconds and emit typed GameEvents on state transitions."""
    previous_state: GameState | None = None
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

                if previous_state is None:
                    # First successful poll — emit if input needed
                    logger.info("Initial game state: %s", state.summary())
                    if state.state_type == "menu":
                        logger.info("Game is at main menu — queuing character select vote")
                        event_queue.put_nowait(MenuSelectNeededEvent())
                    elif state.requires_player_input():
                        logger.info("Queuing vote for initial state: %s", state.state_type)
                        event_queue.put_nowait(VoteNeededEvent(state))
                    previous_state = state

                elif state.state_type != previous_state.state_type:
                    # State transition
                    logger.info("Game state changed: %s", state.summary())
                    if previous_state.state_type == "menu" and state.state_type != "menu":
                        event_queue.put_nowait(GameStartedEvent(state))
                    elif state.state_type == "game_over":
                        event_queue.put_nowait(GameEndedEvent(state))
                    elif state.state_type == "menu":
                        logger.info("Game is at main menu — queuing character select vote")
                        event_queue.put_nowait(MenuSelectNeededEvent())
                    elif state.requires_player_input():
                        logger.info("Queuing vote for state: %s", state.state_type)
                        event_queue.put_nowait(VoteNeededEvent(state))
                    previous_state = state

                else:
                    # Same state_type — check for within-state changes
                    _log_within_state_changes(previous_state, state)
                    if state.is_combat_state() and state.is_play_phase:
                        if not previous_state.is_play_phase:
                            # Edge: enemy turn → player turn
                            logger.info(
                                "Player turn started (is_play_phase=True) — queuing vote"
                            )
                            event_queue.put_nowait(VoteNeededEvent(state))
                        elif (
                            state.hand_size is not None
                            and previous_state.hand_size is not None
                            and state.hand_size < previous_state.hand_size
                        ):
                            # Card was played mid-turn — re-queue so the next card can be voted on
                            logger.info(
                                "Card played mid-turn (hand %d → %d) — re-queuing vote",
                                previous_state.hand_size,
                                state.hand_size,
                            )
                            event_queue.put_nowait(VoteNeededEvent(state))
                    previous_state = state

        except Exception:
            logger.error("Unexpected error in polling loop", exc_info=True)
        await asyncio.sleep(interval)
