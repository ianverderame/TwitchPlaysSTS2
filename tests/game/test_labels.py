import pytest
from tests.conftest import make_state
from game.labels import labels_for_state, target_labels_for_enemies, preamble_for_state


# --- Combat ---

def test_combat_labels_use_card_names():
    state = make_state(
        "monster",
        playable_card_indices=[0, 1],
        hand_card_names={0: "Strike", 1: "Defend"},
    )
    labels = labels_for_state(state)
    assert labels["1"] == "Strike"
    assert labels["2"] == "Defend"
    assert labels["end"] == "End Turn"


def test_combat_labels_fallback_when_name_missing():
    state = make_state("monster", playable_card_indices=[0], hand_card_names={})
    labels = labels_for_state(state)
    assert labels["1"] == "Option 1"
    assert labels["end"] == "End Turn"


def test_combat_labels_elite_and_boss_same_pattern():
    for st in ("elite", "boss"):
        state = make_state(st, playable_card_indices=[0], hand_card_names={0: "Bash"})
        assert labels_for_state(state)["1"] == "Bash"


# --- Event ---

def test_event_labels_use_titles():
    opts = [{"index": 0, "title": "Fight"}, {"index": 1, "title": "Leave"}]
    state = make_state("event", event_options=opts)
    labels = labels_for_state(state)
    assert labels["1"] == "Fight"
    assert labels["2"] == "Leave"


def test_event_labels_exclude_locked():
    opts = [{"index": 0, "title": "Fight", "is_locked": False}, {"index": 1, "title": "Secret", "is_locked": True}]
    state = make_state("event", event_options=opts)
    labels = labels_for_state(state)
    assert "2" not in labels


def test_event_labels_fallback_when_no_title():
    opts = [{"index": 0, "title": None}]
    state = make_state("event", event_options=opts)
    labels = labels_for_state(state)
    assert labels["1"] == "Option 1"


# --- card_reward ---

def test_card_reward_labels_include_card_names_and_skip():
    state = make_state("card_reward", card_reward_names=["Strike+", "Bash+", "Defend+"])
    labels = labels_for_state(state)
    assert labels["1"] == "Strike+"
    assert labels["2"] == "Bash+"
    assert labels["3"] == "Defend+"
    assert labels["skip"] == "Skip"


def test_card_reward_labels_skip_only_when_no_names():
    state = make_state("card_reward", card_reward_names=[])
    labels = labels_for_state(state)
    assert labels == {"skip": "Skip"}


# --- rest_site ---

def test_rest_site_labels_use_option_names():
    opts = [
        {"index": 0, "name": "Rest", "is_enabled": True},
        {"index": 1, "name": "Smith", "is_enabled": True},
    ]
    state = make_state("rest_site", rest_site_options=opts)
    labels = labels_for_state(state)
    assert labels["1"] == "Rest"
    assert labels["2"] == "Smith"


def test_rest_site_labels_exclude_disabled():
    opts = [
        {"index": 0, "name": "Rest", "is_enabled": True},
        {"index": 1, "name": "Smith", "is_enabled": False},
    ]
    state = make_state("rest_site", rest_site_options=opts)
    labels = labels_for_state(state)
    assert "2" not in labels


# --- map ---

def test_map_labels_translate_room_types():
    nodes = [{"index": 0, "col": 1, "type": "MONSTER"}, {"index": 1, "col": 2, "type": "REST"}]
    state = make_state("map", map_next_options=nodes)
    labels = labels_for_state(state)
    assert labels["1"] == "Fight"
    assert labels["2"] == "Rest"


def test_map_labels_sorted_by_col():
    nodes = [{"index": 0, "col": 5, "type": "SHOP"}, {"index": 1, "col": 2, "type": "ELITE"}]
    state = make_state("map", map_next_options=nodes)
    labels = labels_for_state(state)
    assert labels["1"] == "Elite"   # col=2 comes first
    assert labels["2"] == "Shop"


def test_map_labels_unknown_type_uses_raw():
    nodes = [{"index": 0, "col": 1, "type": "WEIRD_ROOM"}]
    state = make_state("map", map_next_options=nodes)
    labels = labels_for_state(state)
    assert labels["1"] == "WEIRD_ROOM"


# --- shop ---

def test_shop_labels_include_name_price_and_leave():
    items = [
        {"index": 0, "is_stocked": True, "can_afford": True, "category": "card", "card_name": "Strike+", "price": 50},
        {"index": 1, "is_stocked": True, "can_afford": True, "category": "relic", "relic_name": "Odd Mushroom", "price": 150},
    ]
    state = make_state("shop", shop_items=items)
    labels = labels_for_state(state)
    assert labels["1"] == "Strike+ (50g)"
    assert labels["2"] == "Odd Mushroom (150g)"
    assert labels["end"] == "Leave"


def test_shop_labels_exclude_unaffordable():
    items = [
        {"index": 0, "is_stocked": True, "can_afford": False, "category": "card", "card_name": "Rare", "price": 999},
    ]
    state = make_state("shop", shop_items=items)
    labels = labels_for_state(state)
    assert "1" not in labels
    assert labels["end"] == "Leave"


# --- relic_select ---

def test_relic_select_labels_use_relic_names():
    relics = [{"index": 0, "name": "Burning Blood"}, {"index": 1, "name": "Ring of the Snake"}]
    state = make_state("relic_select", relic_select_relics=relics)
    labels = labels_for_state(state)
    assert labels["1"] == "Burning Blood"
    assert labels["2"] == "Ring of the Snake"


# --- treasure ---

def test_treasure_labels_include_relic_and_proceed():
    relics = [{"index": 0, "name": "Bottled Flame"}]
    state = make_state("treasure", treasure_relics=relics)
    labels = labels_for_state(state)
    assert labels["1"] == "Bottled Flame"
    assert labels["end"] == "Proceed"


# --- hand_select ---

def test_hand_select_labels_use_card_names():
    cards = [{"name": "Strike"}, {"name": "Defend"}]
    state = make_state("hand_select", hand_select_cards=cards)
    labels = labels_for_state(state)
    assert labels["1"] == "Strike"
    assert labels["2"] == "Defend"


# --- card_select ---

def test_card_select_labels_use_card_names():
    cards = [{"name": "Bash"}, {"name": "Clash"}]
    state = make_state("card_select", card_select_cards=cards)
    labels = labels_for_state(state)
    assert labels["1"] == "Bash"
    assert labels["2"] == "Clash"


# --- Potions merged in ---

def test_combat_labels_include_potion_use():
    potions = [{"slot": 0, "name": "Fire Potion", "target_type": "AnyEnemy", "can_use_in_combat": True}]
    state = make_state("monster", playable_card_indices=[], player_potions=potions)
    labels = labels_for_state(state)
    assert labels["p1"] == "Use Fire Potion"


def test_non_combat_labels_include_potion_discard():
    potions = [{"slot": 0, "name": "Block Potion", "target_type": "Self", "can_use_in_combat": True}]
    state = make_state("rewards", player_potions=potions)
    labels = labels_for_state(state)
    assert labels["d1"] == "Discard Block Potion"


# --- Empty / unknown states ---

def test_unknown_state_returns_empty_dict():
    state = make_state("overlay")
    assert labels_for_state(state) == {}


# --- target_labels_for_enemies ---

def test_target_labels_for_enemies():
    enemies = [
        {"name": "Cultist", "hp": 50, "max_hp": 60},
        {"name": "Jaw Worm", "hp": 40, "max_hp": 44},
    ]
    labels = target_labels_for_enemies(enemies)
    assert labels["1"] == "Cultist (50/60hp)"
    assert labels["2"] == "Jaw Worm (40/44hp)"


# --- preamble_for_state ---

def test_preamble_map():
    state = make_state("map")
    assert preamble_for_state(state) == "Map (left -> right):"


def test_preamble_shop_includes_gold():
    state = make_state("shop", player_gold=120)
    assert preamble_for_state(state) == "Vote open! | Gold: 120g"


def test_preamble_shop_no_gold():
    state = make_state("shop", player_gold=None)
    assert preamble_for_state(state) == "Vote open!"


def test_preamble_hand_select_with_prompt():
    state = make_state("hand_select", hand_select_prompt="Choose a card to exhaust.")
    assert preamble_for_state(state) == "Choose a card to exhaust:"


def test_preamble_default():
    state = make_state("monster")
    assert preamble_for_state(state) == "Vote open!"
