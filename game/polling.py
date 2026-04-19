import asyncio
import logging

from game.api_client import STS2Client
from game.events import GameEndedEvent, GameStartedEvent, GameEvent, MenuSelectNeededEvent, VoteNeededEvent
from game.options import KNOWN_STATES
from game.state import GameState, IDLE_STATES

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

    for prev_enemy, enemy in zip(prev.enemies, curr.enemies):
        if enemy.get("hp") != prev_enemy.get("hp"):
            logger.info(
                "%s HP: %s → %s",
                enemy.get("name", prev_enemy.get("name", "Enemy")),
                prev_enemy.get("hp"),
                enemy.get("hp"),
            )
        if enemy.get("block") != prev_enemy.get("block"):
            logger.info(
                "%s block: %s → %s",
                enemy.get("name", prev_enemy.get("name", "Enemy")),
                prev_enemy.get("block"),
                enemy.get("block"),
            )


async def poll_game_state(
    client: STS2Client,
    interval: float,
    event_queue: asyncio.Queue[GameEvent],
    recheck_attempts: int = 5,
    recheck_interval: float = 0.5,
    action_signal: asyncio.Event | None = None,
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
                if state.state_type not in KNOWN_STATES.keys() | IDLE_STATES:
                    logger.info("UNKNOWN STATE: type=%s keys=%s", state.state_type, list(data.keys()))

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
                    elif previous_state.is_combat_state() and state.state_type == "overlay":
                        # Player died — defeat screen appears as overlay before/instead of game_over
                        logger.info("Combat ended in overlay — treating as game ended")
                        event_queue.put_nowait(GameEndedEvent(state))
                    elif state.state_type == "menu":
                        logger.info("Game is at main menu — queuing character select vote")
                        event_queue.put_nowait(MenuSelectNeededEvent())
                    elif state.requires_player_input():
                        logger.info("Queuing vote for state: %s", state.state_type)
                        event_queue.put_nowait(VoteNeededEvent(state))
                    else:
                        logger.info("State '%s' does not require player input — no vote queued", state.state_type)
                    previous_state = state

                else:
                    # Same state_type — check for within-state changes
                    _log_within_state_changes(previous_state, state)
                    logger.debug("Poll: same state '%s'", state.state_type)
                    if state.is_combat_state() and not state.is_play_phase:
                        logger.debug("Combat '%s': enemy turn (is_play_phase=False)", state.state_type)
                    elif state.is_combat_state() and state.is_play_phase:
                        if not previous_state.is_play_phase:
                            # Edge: enemy turn → player turn (caught by poller)
                            logger.info(
                                "Player turn started (is_play_phase=True) — queuing vote"
                            )
                            event_queue.put_nowait(VoteNeededEvent(state))
                        elif (
                            state.battle_round is not None
                            and previous_state.battle_round is not None
                            and state.battle_round > previous_state.battle_round
                        ):
                            # Enemy turn completed faster than the poll interval — both
                            # snapshots have is_play_phase=True, but battle.round incremented,
                            # which is a definitive signal that a new player turn started.
                            logger.info(
                                "New player turn detected (battle round %d → %d, enemy turn missed by poller) — queuing vote",
                                previous_state.battle_round,
                                state.battle_round,
                            )
                            event_queue.put_nowait(VoteNeededEvent(state))
                        elif (
                            (action_signal is not None and action_signal.is_set())
                        ) or (
                            state.hand_size is not None
                            and previous_state.hand_size is not None
                            and state.hand_size != previous_state.hand_size
                        ) or (
                            set(state.playable_card_indices) != set(previous_state.playable_card_indices)
                        ) or (
                            len(state.player_potions) < len(previous_state.player_potions)
                        ) or (
                            state.player_energy is not None
                            and previous_state.player_energy is not None
                            and state.player_energy < previous_state.player_energy
                        ):
                            # Action was just posted (guaranteed recheck), hand size changed,
                            # playable cards changed, or a potion was consumed. Poll briefly before
                            # re-queuing — some cards (e.g. Dagger Throw) or potions may trigger
                            # hand_select after a short delay.
                            if action_signal is not None:
                                action_signal.clear()
                            recheck_state = state
                            for _ in range(recheck_attempts):
                                await asyncio.sleep(recheck_interval)
                                recheck_data = await client.get_state()
                                if not recheck_data:
                                    break
                                try:
                                    recheck_state = GameState.from_api_response(recheck_data)
                                except ValueError:
                                    break
                                if recheck_state.state_type != state.state_type:
                                    break  # state changed — exit early

                            if recheck_state.state_type != state.state_type:
                                # State already changed — queue new state directly, skip combat re-queue
                                logger.info(
                                    "State changed to '%s' after card play — queuing directly",
                                    recheck_state.state_type,
                                )
                                if recheck_state.requires_player_input():
                                    event_queue.put_nowait(VoteNeededEvent(recheck_state))
                                elif state.is_combat_state() and recheck_state.state_type == "overlay":
                                    logger.info("Combat ended in overlay after card play — treating as game ended")
                                    event_queue.put_nowait(GameEndedEvent(recheck_state))
                            else:
                                logger.info(
                                    "Mid-turn change (hand %s → %s, potions %d → %d) — re-queuing vote",
                                    previous_state.hand_size,
                                    recheck_state.hand_size,
                                    len(previous_state.player_potions),
                                    len(recheck_state.player_potions),
                                )
                                event_queue.put_nowait(VoteNeededEvent(recheck_state))
                            # Update state so previous_state = state (line below) uses recheck_state
                            state = recheck_state
                        else:
                            logger.debug(
                                "Combat '%s': player turn, no new-turn trigger (round=%s, hand=%s)",
                                state.state_type,
                                state.battle_round,
                                state.hand_size,
                            )
                    elif state.state_type == "event":
                        curr_key = [(o.get("index"), o.get("title")) for o in state.event_options]
                        prev_key = [(o.get("index"), o.get("title")) for o in previous_state.event_options]
                        if prev_key and curr_key != prev_key and state.requires_player_input():
                            logger.info(
                                "Event options changed %s → %s — re-queuing vote",
                                [t for _, t in prev_key],
                                [t for _, t in curr_key],
                            )
                            event_queue.put_nowait(VoteNeededEvent(state))
                    previous_state = state

        except Exception:
            logger.error("Unexpected error in polling loop", exc_info=True)
        await asyncio.sleep(interval)
