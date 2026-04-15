import logging

from game.state import GameState

logger = logging.getLogger(__name__)

# Living registry of state_type → vote options.
# All state_types from the STS2MCP API are enumerated here.
# Numeric options ("1", "2", ...) are 1-indexed and map to 0-indexed API calls in actions.py.
KNOWN_STATES: dict[str, list[str]] = {
    # Combat encounters
    "monster":       ["1", "2", "3", "4", "5", "end"],
    "elite":         ["1", "2", "3", "4", "5", "end"],
    "boss":          ["1", "2", "3", "4", "5", "end"],
    # In-combat card selection (exhaust/discard/upgrade prompts)
    "hand_select":   ["1", "2", "3", "4", "5", "confirm"],
    # Post-combat rewards
    "rewards":       ["1", "2", "3", "4", "5", "end"],   # numeric=claim, end=proceed
    "card_reward":   ["1", "2", "3", "skip"],
    # Map navigation
    "map":           ["1", "2", "3", "4", "5"],
    # Room types
    "event":         ["1", "2", "3"],
    "rest_site":     ["1", "2", "3"],
    "shop":          ["1", "2", "3", "4", "5", "end"],   # numeric=purchase, end=proceed
    "fake_merchant": ["1", "2", "3", "end"],
    "treasure":      ["1", "end"],                        # 1=claim relic, end=proceed
    # Card/relic selection overlays
    "card_select":   ["1", "2", "3", "4", "5", "cancel"],
    "bundle_select": ["1", "2", "3", "cancel"],
    "relic_select":  ["1", "2", "3", "skip"],
    # Crystal Sphere minigame — Nth clickable cell; exact cells resolved at action time
    "crystal_sphere": ["1", "2", "3", "4", "5"],
}


_DEFAULT_MAX_POTION_SLOTS = 3  # STS2 default; may change with certain relics


def _shop_item_available(item: dict, state: GameState) -> bool:
    """Return True if a shop item can be meaningfully purchased right now."""
    if not item.get("is_stocked", True):
        return False
    if not item.get("can_afford", True):
        return False
    # Potions can't be bought when the belt is full
    if item.get("category") == "potion" and state.player_potion_count >= _DEFAULT_MAX_POTION_SLOTS:
        return False
    return True


def options_for_state(state: GameState) -> list[str]:
    """Return the list of valid vote choices for the given game state.

    For combat states (monster/elite/boss), options are derived from the actual
    hand size so voters only see choices that correspond to real cards.

    If the state_type is unrecognised, logs a warning and returns a generic
    fallback so voting is never completely blocked. Add new state_types to
    KNOWN_STATES in this module as they are discovered through live testing.
    """
    if state.is_combat_state():
        # Use actual hand positions (1-indexed) so chat options match the in-game card numbers
        numeric = [str(idx + 1) for idx in state.playable_card_indices]
        return numeric + ["end"]

    if state.state_type == "hand_select" and state.hand_select_card_count:
        # Derive options from actual selectable cards; confirm is auto-sent after selection
        return [str(i + 1) for i in range(state.hand_select_card_count)]

    if state.state_type == "rest_site" and state.rest_site_options:
        # Only offer enabled options (e.g. Smith may be unavailable early)
        enabled = [o for o in state.rest_site_options if o.get("is_enabled", True)]
        if enabled:
            return [str(o["index"] + 1) for o in enabled]

    if state.state_type == "map" and state.map_next_options:
        # Sort by col ascending (left → right) so !1 is always the leftmost path
        sorted_nodes = sorted(state.map_next_options, key=lambda n: n["col"])
        return [str(i + 1) for i in range(len(sorted_nodes))]

    if state.state_type in ("shop", "fake_merchant") and state.shop_items:
        # Only offer items that are stocked, affordable, and purchasable given current state
        available = [i for i in state.shop_items if _shop_item_available(i, state)]
        if available:
            return [str(i["index"] + 1) for i in available] + ["end"]

    if state.state_type == "event" and state.event_options:
        # Derive options from actual event options, skipping locked ones
        return [str(o["index"] + 1) for o in state.event_options if not o.get("is_locked")]

    options = KNOWN_STATES.get(state.state_type)
    if options is None:
        logger.warning(
            "Unknown state_type '%s' — using fallback options. "
            "Add this state to KNOWN_STATES in game/options.py.",
            state.state_type,
        )
        return ["1", "2", "3"]
    return options
