import logging

from game.options import _shop_item_available
from game.state import GameState

logger = logging.getLogger(__name__)

MAP_ROOM_LABELS: dict[str, str] = {
    "MONSTER": "Fight",
    "ELITE": "Elite",
    "BOSS": "Boss",
    "EVENT": "Event",
    "REST": "Rest",
    "RESTSITE": "Rest",       # API returns "RestSite"
    "SHOP": "Shop",
    "TREASURE": "Treasure",
    "TREASUREROOM": "Treasure",  # guard against "TreasureRoom"
    "UNKNOWN": "?",
}


def labels_for_state(state: GameState) -> dict[str, str]:
    """Return {option_str: display_label} for chat vote announcements.

    Uses human-readable names from GameState label fields where available.
    Falls back to 'Option N' for missing numeric labels and capitalised key
    for missing word-key labels (e.g. 'cancel' → 'Cancel').
    Returns an empty dict for states with no label data.
    """
    if state.is_combat_state():
        labels: dict[str, str] = {
            str(idx + 1): state.hand_card_names.get(idx, f"Option {idx + 1}")
            for idx in state.playable_card_indices
        }
        labels["end"] = "End Turn"
        return labels

    if state.state_type == "event" and state.event_options:
        return {
            str(o["index"] + 1): o.get("title") or f"Option {o['index'] + 1}"
            for o in state.event_options
            if not o.get("is_locked")
        }

    if state.state_type == "card_reward":
        labels = {str(i + 1): name for i, name in enumerate(state.card_reward_names)}
        if not labels:
            labels = {}
        labels["skip"] = "Skip"
        return labels

    if state.state_type == "rest_site" and state.rest_site_options:
        return {
            str(o["index"] + 1): o.get("name") or f"Option {o['index'] + 1}"
            for o in state.rest_site_options
            if o.get("is_enabled", True)
        }

    if state.state_type == "map" and state.map_next_options:
        sorted_nodes = sorted(state.map_next_options, key=lambda n: n["col"])
        return {
            str(i + 1): MAP_ROOM_LABELS.get(
                n.get("type", "").upper(), n.get("type") or "?"
            )
            for i, n in enumerate(sorted_nodes)
        }

    if state.state_type in ("shop", "fake_merchant") and state.shop_items:
        stocked = [i for i in state.shop_items if _shop_item_available(i, state)]
        def _shop_label(item: dict) -> str:
            category = item.get("category", "")
            # API uses flat prefixed fields: card_name, relic_name, potion_name
            name = (
                item.get(f"{category}_name")
                or item.get("name")
                or ("Remove Card" if category == "card_removal" else None)
                or category.replace("_", " ").title()
                or f"Option {item['index'] + 1}"
            )
            price = item.get("price")
            return f"{name} ({price}g)" if price is not None else name

        labels = {str(i["index"] + 1): _shop_label(i) for i in stocked}
        labels["end"] = "Leave"
        return labels

    if state.state_type == "relic_select" and state.relic_select_relics:
        return {
            str(r["index"] + 1): r.get("name") or f"Option {r['index'] + 1}"
            for r in state.relic_select_relics
        }

    if state.state_type == "treasure" and state.treasure_relics:
        labels = {
            str(r["index"] + 1): r.get("name") or f"Option {r['index'] + 1}"
            for r in state.treasure_relics
        }
        labels["end"] = "Proceed"
        return labels

    if state.state_type == "hand_select" and state.hand_select_cards:
        return {
            str(i + 1): c.get("name") or f"Option {i + 1}"
            for i, c in enumerate(state.hand_select_cards)
        }

    if state.state_type == "card_select" and state.card_select_cards:
        return {
            str(i + 1): c.get("name") or f"Option {i + 1}"
            for i, c in enumerate(state.card_select_cards)
        }

    return {}


def target_labels_for_enemies(enemies: list[dict]) -> dict[str, str]:
    """Return {option_str: display_label} for a target-selection vote.

    Labels use the format "Name (hp/max_hphp)", ordered by the enemies list
    (left-to-right screen order as returned by the API).
    """
    return {
        str(i + 1): f"{e['name']} ({e['hp']}/{e['max_hp']}hp)"
        for i, e in enumerate(enemies)
    }


def preamble_for_state(state: GameState) -> str:
    """Return the opening phrase for a vote announcement.

    Most states use the generic 'Vote open!' prefix. Map gets a directional
    note so viewers know options are numbered left to right.
    """
    if state.state_type == "map":
        return "Map (left -> right):"
    if state.state_type in ("shop", "fake_merchant"):
        gold_str = f" | Gold: {state.player_gold}g" if state.player_gold is not None else ""
        return f"Vote open!{gold_str}"
    if state.state_type == "hand_select" and state.hand_select_prompt:
        return f"{state.hand_select_prompt.rstrip('.')}:"
    return "Vote open!"
