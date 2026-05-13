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


def detect_transition(prev: GameState | None, curr: GameState) -> GameEvent | None:
    """Return the GameEvent triggered by a state_type transition (or initial state), or None.

    Handles:
      - Initial state (prev is None): menu → MenuSelectNeeded; actionable → VoteNeeded.
      - state_type change: menu→non-menu → GameStarted; →game_over → GameEnded;
        combat→overlay → GameEnded (death); →menu → MenuSelectNeeded;
        →actionable → VoteNeeded; otherwise None.

    Pure: no I/O, no side effects beyond a log line when no input is required.
    """
    if prev is None:
        logger.info("Initial game state: %s", curr.summary())
        if curr.state_type == "menu":
            logger.info("Game is at main menu — queuing character select vote")
            return MenuSelectNeededEvent()
        if curr.requires_player_input():
            logger.info("Queuing vote for initial state: %s", curr.state_type)
            return VoteNeededEvent(curr)
        return None

    if curr.state_type == prev.state_type:
        return None

    logger.info("Game state changed: %s", curr.summary())
    if prev.state_type == "menu" and curr.state_type != "menu":
        return GameStartedEvent(curr)
    if curr.state_type == "game_over":
        return GameEndedEvent(curr)
    if prev.is_combat_state() and curr.state_type == "overlay":
        logger.info("Combat ended in overlay — treating as game ended")
        return GameEndedEvent(curr)
    if curr.state_type == "menu":
        logger.info("Game is at main menu — queuing character select vote")
        return MenuSelectNeededEvent()
    if curr.requires_player_input():
        logger.info("Queuing vote for state: %s", curr.state_type)
        return VoteNeededEvent(curr)
    logger.info("State '%s' does not require player input — no vote queued", curr.state_type)
    return None


def _mid_turn_change_reason(
    prev: GameState,
    curr: GameState,
    action_signal: asyncio.Event | None,
) -> str | None:
    """Return which clause triggered the mid-turn re-queue, or None.

    Reasons (checked in order):
      - "action_signal": an action was just posted (guaranteed recheck).
      - "hand_size": hand_size changed.
      - "playable": set of playable card indices changed.
      - "potions": a potion slot was consumed.
      - "energy": player energy decreased.
    """
    if action_signal is not None and action_signal.is_set():
        return "action_signal"
    if (
        curr.hand_size is not None
        and prev.hand_size is not None
        and curr.hand_size != prev.hand_size
    ):
        return "hand_size"
    if set(curr.playable_card_indices) != set(prev.playable_card_indices):
        return "playable"
    if len(curr.player_potions) < len(prev.player_potions):
        return "potions"
    if (
        curr.player_energy is not None
        and prev.player_energy is not None
        and curr.player_energy < prev.player_energy
    ):
        return "energy"
    return None


async def recheck_after_action(
    client: STS2Client,
    prev_state: GameState,
    curr_state: GameState,
    attempts: int,
    interval: float,
) -> tuple[GameState, GameEvent | None]:
    """Poll briefly after an action to catch delayed state changes (e.g. Dagger Throw).

    Returns (final_state, event_to_queue). The event is:
      - VoteNeededEvent(final_state) if state_type changed and requires input,
      - GameEndedEvent(final_state) if combat→overlay (death) during recheck,
      - VoteNeededEvent(final_state) for plain mid-turn re-queue (state unchanged),
      - None if final state doesn't require input and isn't a death overlay.
    """
    recheck_state = curr_state
    for _ in range(attempts):
        await asyncio.sleep(interval)
        recheck_data = await client.get_state()
        if not recheck_data:
            break
        try:
            recheck_state = GameState.from_api_response(recheck_data)
        except ValueError:
            break
        if recheck_state.state_type != curr_state.state_type:
            break  # state changed — exit early

    if recheck_state.state_type != curr_state.state_type:
        logger.info(
            "State changed to '%s' after card play — queuing directly",
            recheck_state.state_type,
        )
        if recheck_state.requires_player_input():
            return recheck_state, VoteNeededEvent(recheck_state)
        if curr_state.is_combat_state() and recheck_state.state_type == "overlay":
            logger.info("Combat ended in overlay after card play — treating as game ended")
            return recheck_state, GameEndedEvent(recheck_state)
        return recheck_state, None

    logger.info(
        "Mid-turn change (hand %s → %s, potions %d → %d) — re-queuing vote",
        prev_state.hand_size,
        recheck_state.hand_size,
        len(prev_state.player_potions),
        len(recheck_state.player_potions),
    )
    return recheck_state, VoteNeededEvent(recheck_state)


async def _handle_within_state(
    client: STS2Client,
    prev: GameState,
    curr: GameState,
    event_queue: asyncio.Queue[GameEvent],
    action_signal: asyncio.Event | None,
    recheck_attempts: int,
    recheck_interval: float,
) -> GameState:
    """Handle a poll where state_type is unchanged. Returns the state to store as previous."""
    _log_within_state_changes(prev, curr)
    logger.debug("Poll: same state '%s'", curr.state_type)

    if curr.is_combat_state() and not curr.is_play_phase:
        logger.debug("Combat '%s': enemy turn (is_play_phase=False)", curr.state_type)
        return curr

    if curr.is_combat_state() and curr.is_play_phase:
        if not prev.is_play_phase:
            logger.info("Player turn started (is_play_phase=True) — queuing vote")
            event_queue.put_nowait(VoteNeededEvent(curr))
            return curr
        if (
            curr.battle_round is not None
            and prev.battle_round is not None
            and curr.battle_round > prev.battle_round
        ):
            logger.info(
                "New player turn detected (battle round %d → %d, enemy turn missed by poller) — queuing vote",
                prev.battle_round,
                curr.battle_round,
            )
            event_queue.put_nowait(VoteNeededEvent(curr))
            return curr
        reason = _mid_turn_change_reason(prev, curr, action_signal)
        if reason is not None:
            logger.info("mid-turn re-queue: %s", reason)
            if action_signal is not None:
                action_signal.clear()
            final_state, event = await recheck_after_action(
                client, prev, curr, recheck_attempts, recheck_interval
            )
            if event is not None:
                event_queue.put_nowait(event)
            return final_state
        logger.debug(
            "Combat '%s': player turn, no new-turn trigger (round=%s, hand=%s)",
            curr.state_type,
            curr.battle_round,
            curr.hand_size,
        )
        return curr

    if curr.state_type == "event":
        curr_key = [(o.get("index"), o.get("title")) for o in curr.event_options]
        prev_key = [(o.get("index"), o.get("title")) for o in prev.event_options]
        if prev_key and curr_key != prev_key and curr.requires_player_input():
            logger.info(
                "Event options changed %s → %s — re-queuing vote",
                [t for _, t in prev_key],
                [t for _, t in curr_key],
            )
            event_queue.put_nowait(VoteNeededEvent(curr))
    return curr


#: Number of consecutive unexpected exceptions tolerated in the polling loop
#: before the loop escalates by re-raising. Keeps the bot from quietly logging
#: the same error every interval forever when something genuinely broken happens
#: (e.g. an upstream API change that breaks state parsing).
POLL_MAX_CONSECUTIVE_FAILURES: int = 10


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
    consecutive_failures: int = 0

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

                if previous_state is None or state.state_type != previous_state.state_type:
                    event = detect_transition(previous_state, state)
                    if event is not None:
                        event_queue.put_nowait(event)
                    previous_state = state
                else:
                    previous_state = await _handle_within_state(
                        client, previous_state, state, event_queue,
                        action_signal, recheck_attempts, recheck_interval,
                    )
            consecutive_failures = 0
        except asyncio.CancelledError:
            raise
        except Exception:
            consecutive_failures += 1
            logger.error(
                "Unexpected error in polling loop (%d/%d consecutive)",
                consecutive_failures,
                POLL_MAX_CONSECUTIVE_FAILURES,
                exc_info=True,
            )
            if consecutive_failures >= POLL_MAX_CONSECUTIVE_FAILURES:
                logger.critical(
                    "Polling loop hit %d consecutive failures — escalating",
                    consecutive_failures,
                )
                raise
        await asyncio.sleep(interval)
