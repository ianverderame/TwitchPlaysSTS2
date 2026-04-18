import pytest
from tests.conftest import make_state
from game.actions import build_api_body
from game.state import GameState


ENEMY = {"entity_id": "e-abc", "name": "Cultist", "hp": 50}


def combat_state(**kwargs) -> GameState:
    return make_state("monster", enemies=[ENEMY], **kwargs)


# --- Potion actions (state-agnostic) ---

def test_use_potion_no_target():
    state = combat_state()
    assert build_api_body(state, "p1") == {"action": "use_potion", "slot": 0}


def test_use_potion_slot_index():
    state = combat_state()
    assert build_api_body(state, "p3") == {"action": "use_potion", "slot": 2}


def test_use_potion_with_explicit_target():
    state = combat_state()
    body = build_api_body(state, "p1", target_entity_id="enemy-xyz")
    assert body == {"action": "use_potion", "slot": 0, "target": "enemy-xyz"}


def test_discard_potion():
    state = combat_state()
    assert build_api_body(state, "d2") == {"action": "discard_potion", "slot": 1}


# --- Combat (monster / elite / boss) ---

def test_combat_end_turn():
    state = combat_state()
    assert build_api_body(state, "end") == {"action": "end_turn"}


def test_combat_play_card_uses_first_enemy():
    state = combat_state()
    body = build_api_body(state, "1")
    assert body["action"] == "play_card"
    assert body["card_index"] == 0
    assert body["target"] == ENEMY["entity_id"]


def test_combat_play_card_explicit_target_overrides():
    state = combat_state()
    body = build_api_body(state, "2", target_entity_id="override-id")
    assert body["target"] == "override-id"
    assert body["card_index"] == 1


def test_combat_play_card_no_enemies_no_target():
    state = make_state("monster", enemies=[])
    body = build_api_body(state, "1")
    assert body["action"] == "play_card"
    assert "target" not in body


@pytest.mark.parametrize("st", ["elite", "boss"])
def test_combat_all_types_end_turn(st):
    state = make_state(st, enemies=[ENEMY])
    assert build_api_body(state, "end") == {"action": "end_turn"}


# --- hand_select ---

def test_hand_select_select_card():
    state = make_state("hand_select")
    assert build_api_body(state, "2") == {"action": "combat_select_card", "card_index": 1}


def test_hand_select_confirm():
    state = make_state("hand_select")
    assert build_api_body(state, "confirm") == {"action": "combat_confirm_selection"}


# --- rewards ---

def test_rewards_claim():
    state = make_state("rewards")
    assert build_api_body(state, "1") == {"action": "claim_reward", "index": 0}


def test_rewards_proceed():
    state = make_state("rewards")
    assert build_api_body(state, "end") == {"action": "proceed"}


# --- card_reward ---

def test_card_reward_select():
    state = make_state("card_reward")
    assert build_api_body(state, "2") == {"action": "select_card_reward", "card_index": 1}


def test_card_reward_skip():
    state = make_state("card_reward")
    assert build_api_body(state, "skip") == {"action": "skip_card_reward"}


# --- map ---

def test_map_choose():
    state = make_state("map")
    assert build_api_body(state, "3") == {"action": "choose_map_node", "index": 2}


# --- event ---

def test_event_choose():
    state = make_state("event")
    assert build_api_body(state, "2") == {"action": "choose_event_option", "index": 1}


# --- rest_site ---

def test_rest_site_choose():
    state = make_state("rest_site")
    assert build_api_body(state, "1") == {"action": "choose_rest_option", "index": 0}


# --- shop ---

def test_shop_purchase():
    state = make_state("shop")
    assert build_api_body(state, "2") == {"action": "shop_purchase", "index": 1}


def test_shop_proceed():
    state = make_state("shop")
    assert build_api_body(state, "end") == {"action": "proceed"}


# --- fake_merchant ---

def test_fake_merchant_purchase():
    state = make_state("fake_merchant")
    assert build_api_body(state, "1") == {"action": "shop_purchase", "index": 0}


def test_fake_merchant_proceed():
    state = make_state("fake_merchant")
    assert build_api_body(state, "end") == {"action": "proceed"}


# --- treasure ---

def test_treasure_claim():
    state = make_state("treasure")
    assert build_api_body(state, "1") == {"action": "claim_treasure_relic", "index": 0}


def test_treasure_proceed():
    state = make_state("treasure")
    assert build_api_body(state, "end") == {"action": "proceed"}


# --- card_select ---

def test_card_select_select():
    state = make_state("card_select")
    assert build_api_body(state, "2") == {"action": "select_card", "index": 1}


def test_card_select_confirm():
    state = make_state("card_select")
    assert build_api_body(state, "confirm") == {"action": "confirm_selection"}


def test_card_select_cancel():
    state = make_state("card_select")
    assert build_api_body(state, "cancel") == {"action": "cancel_selection"}


# --- bundle_select ---

def test_bundle_select_select():
    state = make_state("bundle_select")
    assert build_api_body(state, "1") == {"action": "select_bundle", "index": 0}


def test_bundle_select_cancel():
    state = make_state("bundle_select")
    assert build_api_body(state, "cancel") == {"action": "cancel_bundle_selection"}


# --- relic_select ---

def test_relic_select_select():
    state = make_state("relic_select")
    assert build_api_body(state, "1") == {"action": "select_relic", "index": 0}


def test_relic_select_skip():
    state = make_state("relic_select")
    assert build_api_body(state, "skip") == {"action": "skip_relic_selection"}


# --- crystal_sphere ---

def test_crystal_sphere_click():
    cells = [{"x": 10, "y": 20}, {"x": 30, "y": 40}]
    state = make_state("crystal_sphere", crystal_sphere_cells=cells)
    body = build_api_body(state, "2")
    assert body == {"action": "crystal_sphere_click_cell", "x": 30, "y": 40}


def test_crystal_sphere_empty_cells_raises():
    state = make_state("crystal_sphere", crystal_sphere_cells=[])
    with pytest.raises(ValueError):
        build_api_body(state, "1")


def test_crystal_sphere_out_of_range_raises():
    cells = [{"x": 5, "y": 5}]
    state = make_state("crystal_sphere", crystal_sphere_cells=cells)
    with pytest.raises(ValueError):
        build_api_body(state, "3")


# --- unknown state ---

def test_unknown_state_raises():
    state = make_state("not_a_real_state")
    with pytest.raises(ValueError, match="No API mapping"):
        build_api_body(state, "1")
