import pytest
from tests.conftest import make_state
from game.options import options_for_state, parse_potion_winner


# --- parse_potion_winner ---

def test_parse_potion_winner_use():
    assert parse_potion_winner("p1") == ("use", 0)


def test_parse_potion_winner_use_slot_3():
    assert parse_potion_winner("p3") == ("use", 2)


def test_parse_potion_winner_discard():
    assert parse_potion_winner("d1") == ("discard", 0)


def test_parse_potion_winner_discard_slot_3():
    assert parse_potion_winner("d3") == ("discard", 2)


def test_parse_potion_winner_non_potion_returns_none():
    assert parse_potion_winner("end") is None
    assert parse_potion_winner("1") is None
    assert parse_potion_winner("skip") is None
    assert parse_potion_winner("confirm") is None


def test_parse_potion_winner_single_char_returns_none():
    assert parse_potion_winner("p") is None
    assert parse_potion_winner("d") is None


# --- Combat options ---

def _potion(slot: int, name: str, target_type: str = "Self", in_combat: bool = True, potion_id: str = "") -> dict:
    return {"slot": slot, "id": potion_id, "name": name, "target_type": target_type, "can_use_in_combat": in_combat}


def test_combat_options_from_playable_indices():
    state = make_state("monster", playable_card_indices=[0, 2])
    opts = options_for_state(state)
    assert "1" in opts
    assert "3" in opts
    assert "2" not in opts
    assert "end" in opts


def test_combat_options_end_only_when_no_playable():
    state = make_state("monster", playable_card_indices=[])
    opts = options_for_state(state)
    assert opts == ["end"]


def test_combat_includes_usable_potions():
    potions = [_potion(0, "Fire Potion", "AnyEnemy", in_combat=True)]
    state = make_state("monster", playable_card_indices=[0], player_potions=potions)
    opts = options_for_state(state)
    assert "p1" in opts


def test_combat_excludes_potions_with_can_use_in_combat_false():
    potions = [_potion(0, "Weird Potion", "Self", in_combat=False)]
    state = make_state("monster", playable_card_indices=[0], player_potions=potions)
    opts = options_for_state(state)
    assert "p1" not in opts


def test_combat_discard_NOT_offered_in_combat():
    potions = [_potion(0, "Fire Potion")]
    state = make_state("monster", player_potions=potions)
    opts = options_for_state(state)
    assert "d1" not in opts


def test_out_of_combat_excludes_enemy_target_potions():
    potions = [
        _potion(0, "Fire Potion", target_type="AnyEnemy"),
        _potion(1, "Block Potion", target_type="Self"),
    ]
    state = make_state("rewards", player_potions=potions)
    opts = options_for_state(state)
    assert "p1" not in opts  # AnyEnemy — can't use outside combat
    assert "p2" in opts      # Self — fine outside combat


def test_out_of_combat_excludes_all_enemies_potions():
    potions = [_potion(0, "Explosive Potion", target_type="AllEnemies")]
    state = make_state("rewards", player_potions=potions)
    opts = options_for_state(state)
    assert "p1" not in opts


def test_discard_offered_in_eligible_states():
    potions = [_potion(0, "Potion")]
    for st in ["rewards", "shop", "rest_site", "map", "treasure", "card_reward", "card_select", "relic_select", "fake_merchant"]:
        state = make_state(st, player_potions=potions)
        opts = options_for_state(state)
        assert "d1" in opts, f"Expected d1 in options for state_type={st!r}"


# --- Shop options ---

def _shop_item(index: int, stocked: bool = True, afford: bool = True, category: str = "card") -> dict:
    return {"index": index, "is_stocked": stocked, "can_afford": afford, "category": category}


def test_shop_includes_available_items_and_end():
    items = [_shop_item(0), _shop_item(1)]
    state = make_state("shop", shop_items=items)
    opts = options_for_state(state)
    assert "1" in opts
    assert "2" in opts
    assert "end" in opts


def test_shop_filters_unaffordable():
    items = [_shop_item(0, afford=False), _shop_item(1, afford=True)]
    state = make_state("shop", shop_items=items)
    opts = options_for_state(state)
    assert "1" not in opts
    assert "2" in opts


def test_shop_filters_out_of_stock():
    items = [_shop_item(0, stocked=False)]
    state = make_state("shop", shop_items=items)
    opts = options_for_state(state)
    assert "1" not in opts
    assert "end" in opts


def test_shop_end_only_when_nothing_available():
    items = [_shop_item(0, stocked=False)]
    state = make_state("shop", shop_items=items)
    assert options_for_state(state) == ["end"]


# --- Rest site options ---

def test_rest_site_enabled_options_only():
    options = [
        {"index": 0, "name": "Rest", "is_enabled": True},
        {"index": 1, "name": "Smith", "is_enabled": False},
    ]
    state = make_state("rest_site", rest_site_options=options)
    opts = options_for_state(state)
    assert "1" in opts
    assert "2" not in opts


def test_rest_site_falls_back_to_known_states_when_empty():
    state = make_state("rest_site", rest_site_options=[])
    opts = options_for_state(state)
    assert "1" in opts  # uses KNOWN_STATES fallback


# --- Map options ---

def test_map_sorted_left_to_right_by_col():
    nodes = [{"index": 0, "col": 3, "type": "MONSTER"}, {"index": 1, "col": 1, "type": "REST"}]
    state = make_state("map", map_next_options=nodes)
    opts = options_for_state(state)
    assert opts == ["1", "2"]  # 2 nodes sorted by col


# --- Event options ---

def test_event_skips_locked_options():
    event_opts = [
        {"index": 0, "title": "Fight", "is_locked": False},
        {"index": 1, "title": "Leave", "is_locked": True},
    ]
    state = make_state("event", event_options=event_opts)
    opts = options_for_state(state)
    assert "1" in opts
    assert "2" not in opts


# --- Relic select ---

def test_relic_select_options_include_skip():
    relics = [{"index": 0, "name": "A"}, {"index": 1, "name": "B"}]
    state = make_state("relic_select", relic_select_relics=relics)
    opts = options_for_state(state)
    assert "1" in opts
    assert "2" in opts
    assert "skip" in opts


# --- Foul Potion at shop / fake_merchant ---

def test_shop_allows_foul_potion():
    potions = [_potion(0, "Foul Potion", target_type="AnyEnemy", potion_id="FOUL_POTION")]
    state = make_state("shop", player_potions=potions)
    opts = options_for_state(state)
    assert "p1" in opts


def test_fake_merchant_allows_foul_potion():
    potions = [_potion(0, "Foul Potion", target_type="AnyEnemy", potion_id="FOUL_POTION")]
    state = make_state("fake_merchant", player_potions=potions)
    opts = options_for_state(state)
    assert "p1" in opts


def test_shop_blocks_other_any_enemy_potions():
    potions = [_potion(0, "Fire Potion", target_type="AnyEnemy", potion_id="FIRE_POTION")]
    state = make_state("shop", player_potions=potions)
    opts = options_for_state(state)
    assert "p1" not in opts


def test_out_of_combat_foul_potion_blocked_outside_merchant_states():
    potions = [_potion(0, "Foul Potion", target_type="AnyEnemy", potion_id="FOUL_POTION")]
    state = make_state("rewards", player_potions=potions)
    opts = options_for_state(state)
    assert "p1" not in opts


def test_fake_merchant_post_fight_end_only():
    state = make_state("fake_merchant", shop_items=[])
    assert options_for_state(state) == ["end"]


# --- Unknown state fallback ---

def test_unknown_state_returns_fallback():
    state = make_state("totally_unknown_state")
    opts = options_for_state(state)
    assert opts == ["1", "2", "3"]
