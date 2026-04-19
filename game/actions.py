import logging

from game.options import parse_potion_winner
from game.state import GameState

logger = logging.getLogger(__name__)


def build_api_body(state: GameState, winner: str, target_entity_id: str | None = None) -> dict:
    """Translate a vote winner string into a STS2MCP action request body.

    Vote options are 1-indexed strings (e.g. "1", "2"); the API uses 0-indexed
    integers. Raises ValueError for unrecognised (state_type, winner) pairs so
    bad mappings surface loudly during PoC live testing.
    """
    st = state.state_type

    # Potion actions are state-agnostic — handled before state-specific
    # branches so potions work in combat and out-of-combat contexts alike.
    potion_action = parse_potion_winner(winner)
    if potion_action is not None:
        kind, slot = potion_action
        if kind == "use":
            body: dict = {"action": "use_potion", "slot": slot}
            if target_entity_id is not None:
                body["target"] = target_entity_id
            return body
        return {"action": "discard_potion", "slot": slot}

    if st in {"monster", "elite", "boss"}:
        if winner == "end":
            return {"action": "end_turn"}
        try:
            # Vote number matches the 1-indexed hand position shown in-game
            card_index = int(winner) - 1
            body: dict = {"action": "play_card", "card_index": card_index}
            if target_entity_id is not None:
                body["target"] = target_entity_id
            elif state.enemies:
                body["target"] = state.enemies[0]["entity_id"]
            return body
        except ValueError:
            pass

    elif st == "hand_select":
        if winner == "confirm":
            return {"action": "combat_confirm_selection"}
        try:
            idx = int(winner) - 1
            return {"action": "combat_select_card", "card_index": idx}
        except ValueError:
            pass

    elif st == "rewards":
        if winner == "end":
            return {"action": "proceed"}
        try:
            idx = int(winner) - 1
            return {"action": "claim_reward", "index": idx}
        except ValueError:
            pass

    elif st == "card_reward":
        if winner == "skip":
            return {"action": "skip_card_reward"}
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

    elif st == "rest_site":
        try:
            idx = int(winner) - 1
            return {"action": "choose_rest_option", "index": idx}
        except ValueError:
            pass

    elif st in ("shop", "fake_merchant"):
        if winner == "end":
            return {"action": "proceed"}
        try:
            idx = int(winner) - 1
            return {"action": "shop_purchase", "index": idx}
        except ValueError:
            pass

    elif st == "treasure":
        if winner == "end":
            return {"action": "proceed"}
        try:
            idx = int(winner) - 1
            return {"action": "claim_treasure_relic", "index": idx}
        except ValueError:
            pass

    elif st == "card_select":
        if winner == "confirm":
            return {"action": "confirm_selection"}
        if winner == "cancel":
            return {"action": "cancel_selection"}
        try:
            idx = int(winner) - 1
            return {"action": "select_card", "index": idx}
        except ValueError:
            pass

    elif st == "bundle_select":
        if winner == "cancel":
            return {"action": "cancel_bundle_selection"}
        try:
            idx = int(winner) - 1
            return {"action": "select_bundle", "index": idx}
        except ValueError:
            pass

    elif st == "relic_select":
        if winner == "skip":
            return {"action": "skip_relic_selection"}
        try:
            idx = int(winner) - 1
            return {"action": "select_relic", "index": idx}
        except ValueError:
            pass

    elif st == "crystal_sphere":
        try:
            idx = int(winner) - 1
        except ValueError:
            pass
        else:
            cells = state.crystal_sphere_cells
            if not cells:
                raise ValueError("crystal_sphere_cells is empty — cannot resolve coordinates")
            if idx >= len(cells):
                raise ValueError(
                    f"Vote index {idx} out of range; only {len(cells)} clickable cells available"
                )
            cell = cells[idx]
            return {"action": "crystal_sphere_click_cell", "x": cell["x"], "y": cell["y"]}

    raise ValueError(
        f"No API mapping for state_type={st!r}, winner={winner!r}. "
        "Add this combination to game/actions.py."
    )
