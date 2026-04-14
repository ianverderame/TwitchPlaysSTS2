import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Denylist of state_types that do NOT require player input.
# Start minimal — unknown states trigger votes and surface via options.py warnings during testing.
# Add entries here as non-input states are discovered through live testing.
IDLE_STATES: frozenset[str] = frozenset({"menu", "game_over", "unknown", "rewards"})


@dataclass
class GameState:
    state_type: str
    act: int | None
    floor: int | None
    player_hp: int | None
    player_max_hp: int | None

    @classmethod
    def from_api_response(cls, data: dict) -> "GameState":
        """Parse a STS2MCP /api/v1/singleplayer response into a GameState.

        Raises ValueError if state_type is missing (malformed response).
        act/floor/player fields are silently None when absent (expected in menu state).
        """
        if "state_type" not in data:
            logger.warning("STS2MCP response missing state_type: %s", data)
            raise ValueError("Response missing required field: state_type")

        run = data.get("run") or {}
        player = data.get("player") or {}

        return cls(
            state_type=data["state_type"],
            act=run.get("act"),
            floor=run.get("floor"),
            player_hp=player.get("hp"),
            player_max_hp=player.get("max_hp"),
        )

    def requires_player_input(self) -> bool:
        """Return True when the game state needs a player decision."""
        return self.state_type not in IDLE_STATES

    def summary(self) -> str:
        """One-line description of current state for terminal logging."""
        if self.act is not None and self.floor is not None:
            location = f"Act {self.act}, Floor {self.floor}"
        else:
            location = None

        if self.player_hp is not None and self.player_max_hp is not None:
            hp = f"HP {self.player_hp}/{self.player_max_hp}"
        else:
            hp = None

        parts = [self.state_type]
        if location:
            parts.append(location)
        if hp:
            parts.append(hp)
        return " | ".join(parts)
