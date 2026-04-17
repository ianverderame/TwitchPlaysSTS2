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
    player_gold: int | None = None             # player.gold
    player_potion_count: int = 0               # len(player.potions) — for shop potion availability
    player_energy: int | None = None      # player.energy (combat only)
    is_play_phase: bool | None = None          # battle.is_play_phase (combat only)
    battle_round: int | None = None            # battle.round — increments each full turn cycle
    hand_size: int | None = None               # len(player.hand) — used for mid-turn re-queue detection
    playable_card_indices: list[int] = field(default_factory=list)  # hand indices of can_play=True cards
    enemies: list[dict] = field(default_factory=list)  # Combat only; empty outside combat
    crystal_sphere_cells: list[dict] = field(default_factory=list)  # crystal_sphere.clickable_cells
    event_options: list[dict] = field(default_factory=list)         # event.options (event state only)
    hand_select_card_count: int = 0                                  # len(hand_select.cards) (hand_select state only)
    hand_select_can_confirm: bool = False                            # hand_select.can_confirm (hand_select state only)
    hand_select_prompt: str = ""                                     # hand_select.prompt (hand_select state only)
    rewards_items: list[dict] = field(default_factory=list)          # rewards.items (rewards state only)
    card_select_can_confirm: bool = False                             # card_select.can_confirm (card_select state only)
    card_select_screen_type: str = ""                                 # card_select.screen_type (e.g. "upgrade", "transform")
    # Label data — human-readable names for vote option display
    hand_card_names: dict[int, str] = field(default_factory=dict)        # hand index → card name (combat)
    hand_card_target_types: dict[int, str] = field(default_factory=dict) # hand index → target_type (combat)
    card_reward_names: list[str] = field(default_factory=list)       # card_reward.cards[i].name
    rest_site_can_proceed: bool = False                               # rest_site.can_proceed
    rest_site_options: list[dict] = field(default_factory=list)      # rest_site.options (has index, name, is_enabled)
    map_next_options: list[dict] = field(default_factory=list)       # map.next_options (has index, col, type)
    relic_select_relics: list[dict] = field(default_factory=list)    # relic_select.relics (has index, name)
    treasure_relics: list[dict] = field(default_factory=list)        # treasure.relics (has index, name)
    hand_select_cards: list[dict] = field(default_factory=list)      # hand_select.cards (has name)
    card_select_cards: list[dict] = field(default_factory=list)      # card_select.cards (has name)
    shop_items: list[dict] = field(default_factory=list)             # shop.items or fake_merchant.shop.items

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
        card_reward_data = data.get("card_reward") or {}
        rest_site_data = data.get("rest_site") or {}
        map_data = data.get("map") or {}
        relic_select_data = data.get("relic_select") or {}
        treasure_data = data.get("treasure") or {}

        return cls(
            state_type=data["state_type"],
            act=run.get("act"),
            floor=run.get("floor"),
            player_hp=player.get("hp"),
            player_max_hp=player.get("max_hp"),
            player_block=player.get("block"),
            player_gold=player.get("gold"),
            player_potion_count=len(player.get("potions") or []),
            player_energy=player.get("energy"),
            is_play_phase=battle.get("is_play_phase"),
            battle_round=battle.get("round"),
            hand_size=len(player.get("hand") or []),
            playable_card_indices=[
                c["index"] for c in (player.get("hand") or []) if c.get("can_play")
            ],
            enemies=battle.get("enemies") or [],
            crystal_sphere_cells=crystal_sphere.get("clickable_cells") or [],
            event_options=event.get("options") or [],
            hand_select_card_count=len(hand_select.get("cards") or []),
            hand_select_can_confirm=bool(hand_select.get("can_confirm")),
            hand_select_prompt=hand_select.get("prompt") or "",
            rewards_items=rewards.get("items") or [],
            card_select_can_confirm=bool(card_select.get("can_confirm")),
            card_select_screen_type=card_select.get("screen_type") or "",
            hand_card_names={c["index"]: c["name"] for c in (player.get("hand") or []) if "name" in c},
            hand_card_target_types={c["index"]: c["target_type"] for c in (player.get("hand") or []) if "target_type" in c},
            card_reward_names=[c["name"] for c in (card_reward_data.get("cards") or []) if "name" in c],
            rest_site_can_proceed=bool(rest_site_data.get("can_proceed")),
            rest_site_options=rest_site_data.get("options") or [],
            map_next_options=map_data.get("next_options") or [],
            relic_select_relics=relic_select_data.get("relics") or [],
            treasure_relics=treasure_data.get("relics") or [],
            hand_select_cards=hand_select.get("cards") or [],
            card_select_cards=card_select.get("cards") or [],
            shop_items=(
                (data.get("shop") or {}).get("items")
                or (data.get("fake_merchant") or {}).get("shop", {}).get("items")
                or []
            ),
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
