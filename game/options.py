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


# States where viewers may want to discard a held potion (e.g. to free belt space
# before a potion reward or swap at the shop). Combat and map/treasure/card_select
# screens are excluded — no reason to free a slot mid-fight or mid-selection.
_POTION_DISCARD_STATES: frozenset[str] = frozenset({
    "rewards", "shop", "fake_merchant", "rest_site",
    "map", "treasure", "card_reward", "card_select", "relic_select",
})

POTION_USE_PREFIX = "p"
POTION_DISCARD_PREFIX = "d"

# Potions with these target_types require a living enemy to throw at and cannot
# be used outside combat — even if the potion slot is technically selectable.
_ENEMY_TARGET_TYPES: frozenset[str] = frozenset({"AnyEnemy", "AllEnemies"})

# The Foul Potion is the only enemy-targeting potion usable at the shop or fake
# merchant — it initiates a fight with the merchant instead of throwing at a combat enemy.
_FOUL_POTION_ID = "FOUL_POTION"


def potion_display_name(potion: dict) -> str:
    """Human-readable potion name with `Potion N` slot fallback."""
    return potion.get("name") or f"Potion {potion.get('slot', 0) + 1}"


def parse_potion_winner(winner: str) -> tuple[str, int] | None:
    """Parse a `pN`/`dN` vote winner into (kind, slot_index).

    Returns `("use", slot)`, `("discard", slot)`, or None for non-potion winners.
    Slot is 0-indexed (matches `use_potion.slot` / `discard_potion.slot` in the API).
    """
    if len(winner) < 2 or not winner[1:].isdigit():
        return None
    if winner[0] == POTION_USE_PREFIX:
        return "use", int(winner[1:]) - 1
    if winner[0] == POTION_DISCARD_PREFIX:
        return "discard", int(winner[1:]) - 1
    return None


def potion_vote_entries(state: GameState) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    """Return (use_entries, discard_entries) as lists of (tag, display_name).

    Single source of truth for both `options_for_state` and `labels_for_state`:
    keeps offered options and their labels from drifting apart. Use eligibility
    depends on context (combat vs. out-of-combat); discard eligibility depends
    on state_type alone.
    """
    if not state.player_potions:
        return [], []
    in_combat = state.is_combat_state() or state.state_type == "hand_select"
    use_entries: list[tuple[str, str]] = []
    for p in state.player_potions:
        target_type = p.get("target_type", "")
        if in_combat:
            if not p.get("can_use_in_combat", True):
                continue
        else:
            if target_type in _ENEMY_TARGET_TYPES:
                # Foul Potion can be thrown at the shop or fake merchant to start a fight.
                # All other enemy-targeting potions require combat and are blocked here.
                if not (p.get("id") == _FOUL_POTION_ID and state.state_type in ("shop", "fake_merchant")):
                    continue
        use_entries.append((f"{POTION_USE_PREFIX}{p['slot'] + 1}", potion_display_name(p)))
    discard_entries: list[tuple[str, str]] = (
        [(f"{POTION_DISCARD_PREFIX}{p['slot'] + 1}", potion_display_name(p)) for p in state.player_potions]
        if state.state_type in _POTION_DISCARD_STATES
        else []
    )
    return use_entries, discard_entries


def shop_item_available(item: dict, state: GameState) -> bool:
    """Return True if a shop item can be meaningfully purchased right now."""
    if not item.get("is_stocked", True):
        return False
    if not item.get("can_afford", True):
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
    base = _base_options_for_state(state)
    use_entries, discard_entries = potion_vote_entries(state)
    return base + [tag for tag, _ in use_entries] + [tag for tag, _ in discard_entries]


def _base_options_for_state(state: GameState) -> list[str]:
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

    if state.state_type in ("shop", "fake_merchant"):
        # Only offer items that are stocked, affordable, and purchasable given current state
        available = [i for i in state.shop_items if shop_item_available(i, state)]
        if available:
            return [str(i["index"] + 1) for i in available] + ["end"]
        return ["end"]  # no purchasable items — only option is to leave

    if state.state_type == "event" and state.event_options:
        # Derive options from actual event options, skipping locked ones
        return [str(o["index"] + 1) for o in state.event_options if not o.get("is_locked")]

    if state.state_type == "relic_select" and state.relic_select_relics:
        return [str(r["index"] + 1) for r in state.relic_select_relics] + ["skip"]

    options = KNOWN_STATES.get(state.state_type)
    if options is None:
        logger.warning(
            "Unknown state_type '%s' — using fallback options. "
            "Add this state to KNOWN_STATES in game/options.py.",
            state.state_type,
        )
        return ["1", "2", "3"]
    return options
