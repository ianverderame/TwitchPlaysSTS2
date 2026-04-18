import pytest
from game.state import GameState


MINIMAL_COMBAT_RESPONSE = {
    "state_type": "monster",
    "run": {"act": 1, "floor": 3},
    "player": {
        "hp": 70,
        "max_hp": 80,
        "block": 0,
        "gold": 99,
        "energy": 3,
        "hand": [
            {"index": 0, "name": "Strike", "can_play": True, "target_type": "AnyEnemy"},
            {"index": 1, "name": "Defend", "can_play": True, "target_type": "Self"},
            {"index": 2, "name": "Clash", "can_play": False, "target_type": "AnyEnemy"},
        ],
        "potions": [
            {"slot": 0, "name": "Fire Potion", "target_type": "AnyEnemy", "can_use_in_combat": True}
        ],
    },
    "battle": {
        "is_play_phase": True,
        "round": 2,
        "enemies": [{"entity_id": "e1", "name": "Cultist", "hp": 50, "block": 0}],
    },
}


# --- from_api_response ---

def test_from_api_response_minimal():
    state = GameState.from_api_response({"state_type": "menu"})
    assert state.state_type == "menu"
    assert state.act is None
    assert state.player_hp is None


def test_from_api_response_missing_state_type_raises():
    with pytest.raises(ValueError, match="state_type"):
        GameState.from_api_response({})


def test_from_api_response_parses_run_fields():
    state = GameState.from_api_response(MINIMAL_COMBAT_RESPONSE)
    assert state.act == 1
    assert state.floor == 3


def test_from_api_response_parses_player_fields():
    state = GameState.from_api_response(MINIMAL_COMBAT_RESPONSE)
    assert state.player_hp == 70
    assert state.player_max_hp == 80
    assert state.player_energy == 3
    assert state.player_gold == 99
    assert state.player_block == 0


def test_from_api_response_parses_hand():
    state = GameState.from_api_response(MINIMAL_COMBAT_RESPONSE)
    assert state.hand_size == 3
    assert state.playable_card_indices == [0, 1]
    assert state.hand_card_names == {0: "Strike", 1: "Defend", 2: "Clash"}
    assert state.hand_card_target_types == {0: "AnyEnemy", 1: "Self", 2: "AnyEnemy"}


def test_from_api_response_parses_battle():
    state = GameState.from_api_response(MINIMAL_COMBAT_RESPONSE)
    assert state.is_play_phase is True
    assert state.battle_round == 2
    assert len(state.enemies) == 1
    assert state.enemies[0]["entity_id"] == "e1"


def test_from_api_response_parses_potions():
    state = GameState.from_api_response(MINIMAL_COMBAT_RESPONSE)
    assert len(state.player_potions) == 1
    assert state.player_potions[0]["name"] == "Fire Potion"


def test_from_api_response_shop_items_from_shop_key():
    data = {
        "state_type": "shop",
        "shop": {"items": [{"index": 0, "name": "Strike+", "is_stocked": True, "can_afford": True}]},
    }
    state = GameState.from_api_response(data)
    assert len(state.shop_items) == 1


def test_from_api_response_shop_items_from_fake_merchant_key():
    data = {
        "state_type": "fake_merchant",
        "fake_merchant": {"shop": {"items": [{"index": 0, "name": "Potion", "is_stocked": True, "can_afford": True}]}},
    }
    state = GameState.from_api_response(data)
    assert len(state.shop_items) == 1


def test_from_api_response_null_nested_keys_dont_crash():
    data = {"state_type": "monster", "run": None, "player": None, "battle": None}
    state = GameState.from_api_response(data)
    assert state.act is None
    assert state.player_hp is None
    assert state.enemies == []


# --- is_combat_state ---

@pytest.mark.parametrize("st", ["monster", "elite", "boss"])
def test_is_combat_state_true(st):
    state = GameState(state_type=st, act=1, floor=1, player_hp=80, player_max_hp=80)
    assert state.is_combat_state() is True


@pytest.mark.parametrize("st", ["shop", "map", "event", "rest_site", "menu", "card_reward", "rewards"])
def test_is_combat_state_false(st):
    state = GameState(state_type=st, act=1, floor=1, player_hp=80, player_max_hp=80)
    assert state.is_combat_state() is False


# --- requires_player_input ---

@pytest.mark.parametrize("st", ["menu", "game_over", "unknown", "overlay"])
def test_requires_player_input_false_for_idle(st):
    state = GameState(state_type=st, act=None, floor=None, player_hp=None, player_max_hp=None)
    assert state.requires_player_input() is False


@pytest.mark.parametrize("st", ["monster", "shop", "map", "event", "rest_site", "card_reward"])
def test_requires_player_input_true_for_actionable(st):
    state = GameState(state_type=st, act=1, floor=1, player_hp=80, player_max_hp=80)
    assert state.requires_player_input() is True


# --- summary ---

def test_summary_with_full_data():
    state = GameState(state_type="monster", act=2, floor=7, player_hp=60, player_max_hp=80)
    result = state.summary()
    assert "monster" in result
    assert "Act 2" in result
    assert "Floor 7" in result
    assert "60/80" in result


def test_summary_with_no_location():
    state = GameState(state_type="menu", act=None, floor=None, player_hp=None, player_max_hp=None)
    result = state.summary()
    assert result == "menu"


def test_summary_partial_data_no_crash():
    state = GameState(state_type="shop", act=1, floor=None, player_hp=50, player_max_hp=None)
    result = state.summary()
    assert "shop" in result
