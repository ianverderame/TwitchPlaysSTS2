from dataclasses import dataclass

from game.state import GameState


@dataclass
class VoteNeededEvent:
    """Emitted when the game transitions to a state requiring a player decision."""
    state: GameState


@dataclass
class GameStartedEvent:
    """Emitted when the game transitions from MENU into an active run."""
    state: GameState


@dataclass
class GameEndedEvent:
    """Emitted when the game reaches GAME_OVER."""
    state: GameState


@dataclass
class MenuSelectNeededEvent:
    """Emitted when STS2MCP reports state_type=menu, triggering a character-select vote."""


GameEvent = VoteNeededEvent | GameStartedEvent | GameEndedEvent | MenuSelectNeededEvent
