import pytest
from game.state import GameState


def make_state(state_type: str, **kwargs) -> GameState:
    """Build a GameState with sensible defaults for testing."""
    defaults = dict(act=1, floor=1, player_hp=80, player_max_hp=80)
    defaults.update(kwargs)
    return GameState(state_type=state_type, **defaults)
