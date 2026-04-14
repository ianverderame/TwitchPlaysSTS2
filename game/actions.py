import logging

from game.state import GameState

logger = logging.getLogger(__name__)


def build_api_body(state: GameState, winner: str) -> dict:
    """Translate a vote winner string into a STS2MCP action request body.

    Vote options are 1-indexed strings (e.g. "1", "2"); the API uses 0-indexed
    integers. Raises ValueError for unrecognised (state_type, winner) pairs so
    bad mappings surface loudly during PoC live testing.
    """
    st = state.state_type

    if st == "monster":
        if winner == "end":
            return {"action": "end_turn"}
        try:
            idx = int(winner) - 1
            return {"action": "play_card", "card_index": idx}
        except ValueError:
            pass

    elif st == "card_reward":
        try:
            idx = int(winner) - 1
            return {"action": "select_card_reward", "card_index": idx}
        except ValueError:
            pass

    elif st == "map":
        try:
            idx = int(winner) - 1
            return {"action": "choose_map_node", "index": idx}
        except ValueError:
            pass

    elif st == "event":
        try:
            idx = int(winner) - 1
            return {"action": "choose_event_option", "index": idx}
        except ValueError:
            pass

    elif st == "hand_select":
        try:
            idx = int(winner) - 1
            return {"action": "combat_select_card", "card_index": idx}
        except ValueError:
            pass

    raise ValueError(
        f"No API mapping for state_type={st!r}, winner={winner!r}. "
        "Add this combination to game/actions.py."
    )
