import logging

from game.state import GameState

logger = logging.getLogger(__name__)

# Living registry of state_type → vote options.
# During live testing, unknown state_types surface as WARNING logs with instructions
# to add them here. In 1.0, values will be replaced with real API-derived options.
KNOWN_STATES: dict[str, list[str]] = {
    "monster":     ["1", "2", "3", "4", "5", "end"],  # combat encounter
    "elite":       ["1", "2", "3", "4", "5", "end"],  # elite combat
    "boss":        ["1", "2", "3", "4", "5", "end"],  # boss combat
    "hand_select": ["1", "2", "3", "4", "5"],          # select a card from hand (card effect)
    "card_reward": ["1", "2", "3"],
    "map":         ["1", "2", "3", "4", "5"],  # node index — exact count unverified; trim via live testing
    "event":       ["1", "2", "3"],
    "shop":        ["end"],                            # "end" → proceed (leave shop)
    "rest_site":   ["1", "2", "3"],                    # rest site options
    "rewards":     ["end"],                            # "end" → proceed (leave rewards screen)
    "treasure":    ["1", "end"],                       # "1" → claim relic, "end" → proceed
}


def options_for_state(state: GameState) -> list[str]:
    """Return the list of valid vote choices for the given game state.

    If the state_type is unrecognised, logs a warning and returns a generic
    fallback so voting is never completely blocked. Add new state_types to
    KNOWN_STATES in this module as they are discovered through live testing.
    """
    options = KNOWN_STATES.get(state.state_type)
    if options is None:
        logger.warning(
            "Unknown state_type '%s' — using fallback options. "
            "Add this state to KNOWN_STATES in game/options.py.",
            state.state_type,
        )
        return ["1", "2", "3"]
    return options
