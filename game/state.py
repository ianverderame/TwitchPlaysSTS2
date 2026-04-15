import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# Denylist of state_types that do NOT require player input.
IDLE_STATES: frozenset[str] = frozenset({"menu", "game_over", "unknown", "overlay"})


@dataclass
class GameState:
    state_type: str
    act: int | None
    floor: int | None
    player_hp: int | None
    player_max_hp: int | None
    player_block: int | None = None       # player.block
    player_energy: int | None = None      # player.energy (combat only)
    is_play_phase: bool | None = None          # battle.is_play_phase (combat only)
    hand_size: int | None = None               # len(player.hand) — used for mid-turn re-queue detection
    playable_card_indices: list[int] = field(default_factory=list)  # hand indices of can_play=True cards
    enemies: list[dict] = field(default_factory=list)  # Combat only; empty outside combat
    crystal_sphere_cells: list[dict] = field(default_factory=list)  # crystal_sphere.clickable_cells
    event_options: list[dict] = field(default_factory=list)         # event.options (event state only)
    hand_select_card_count: int = 0                                  # len(hand_select.cards) (hand_select state only)
    rewards_items: list[dict] = field(default_factory=list)          # rewards.items (rewards state only)
    card_select_can_confirm: bool = False                             # card_select.can_confirm (card_select state only)

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
        battle = data.get("battle") or {}
        crystal_sphere = data.get("crystal_sphere") or {}
        event = data.get("event") or {}
        hand_select = data.get("hand_select") or {}
        rewards = data.get("rewards") or {}
        card_select = data.get("card_select") or {}

        return cls(
            state_type=data["state_type"],
            act=run.get("act"),
            floor=run.get("floor"),
            player_hp=player.get("hp"),
            player_max_hp=player.get("max_hp"),
            player_block=player.get("block"),
            player_energy=player.get("energy"),
            is_play_phase=battle.get("is_play_phase"),
            hand_size=len(player.get("hand") or []),
            playable_card_indices=[
                c["index"] for c in (player.get("hand") or []) if c.get("can_play")
            ],
            enemies=battle.get("enemies") or [],
            crystal_sphere_cells=crystal_sphere.get("clickable_cells") or [],
            event_options=event.get("options") or [],
            hand_select_card_count=len(hand_select.get("cards") or []),
            rewards_items=rewards.get("items") or [],
            card_select_can_confirm=bool(card_select.get("can_confirm")),
        )

    def is_combat_state(self) -> bool:
        """Return True when the current state is a combat encounter."""
        return self.state_type in {"monster", "elite", "boss"}

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
