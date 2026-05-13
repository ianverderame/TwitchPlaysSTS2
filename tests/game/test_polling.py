import asyncio
from unittest.mock import AsyncMock, MagicMock
import pytest

from game.polling import (
    poll_game_state,
    detect_transition,
    _mid_turn_change_reason,
    recheck_after_action,
)
from game.state import GameState
from game.events import VoteNeededEvent, MenuSelectNeededEvent, GameStartedEvent, GameEndedEvent


def _api_response(state_type: str, **overrides) -> dict:
    """Minimal valid API response dict."""
    base = {"state_type": state_type}
    base.update(overrides)
    return base


def _make_client(responses: list) -> MagicMock:
    """Return a mock STS2Client whose get_state() returns items from `responses` in order,
    then raises asyncio.CancelledError to terminate the polling loop."""
    client = MagicMock()
    side_effects = list(responses) + [asyncio.CancelledError()]
    client.get_state = AsyncMock(side_effect=side_effects)
    return client


async def _drain(client: MagicMock, queue: asyncio.Queue, interval: float = 0) -> list:
    """Run poll_game_state until CancelledError, return collected events."""
    try:
        await poll_game_state(client, interval, queue)
    except asyncio.CancelledError:
        pass
    events = []
    while not queue.empty():
        events.append(queue.get_nowait())
    return events


# --- First-poll behaviour ---

async def test_first_poll_actionable_state_emits_vote_needed():
    q: asyncio.Queue = asyncio.Queue()
    client = _make_client([_api_response("monster")])
    events = await _drain(client, q)
    assert len(events) == 1
    assert isinstance(events[0], VoteNeededEvent)
    assert events[0].state.state_type == "monster"


async def test_first_poll_menu_emits_menu_select():
    q: asyncio.Queue = asyncio.Queue()
    client = _make_client([_api_response("menu")])
    events = await _drain(client, q)
    assert len(events) == 1
    assert isinstance(events[0], MenuSelectNeededEvent)


async def test_first_poll_idle_state_no_event():
    q: asyncio.Queue = asyncio.Queue()
    client = _make_client([_api_response("game_over")])
    events = await _drain(client, q)
    assert events == []


# --- State transition behaviour ---

async def test_transition_menu_to_combat_emits_game_started():
    q: asyncio.Queue = asyncio.Queue()
    client = _make_client([_api_response("menu"), _api_response("monster")])
    events = await _drain(client, q)
    types = [type(e) for e in events]
    assert MenuSelectNeededEvent in types
    assert GameStartedEvent in types


async def test_transition_to_game_over_emits_game_ended():
    q: asyncio.Queue = asyncio.Queue()
    client = _make_client([_api_response("monster"), _api_response("game_over")])
    events = await _drain(client, q)
    assert any(isinstance(e, GameEndedEvent) for e in events)


async def test_transition_combat_to_overlay_emits_game_ended():
    """Player death often manifests as combat → overlay, not combat → game_over."""
    q: asyncio.Queue = asyncio.Queue()
    client = _make_client([_api_response("monster"), _api_response("overlay")])
    events = await _drain(client, q)
    assert any(isinstance(e, GameEndedEvent) for e in events)


async def test_transition_to_new_actionable_state_emits_vote_needed():
    q: asyncio.Queue = asyncio.Queue()
    client = _make_client([_api_response("monster"), _api_response("card_reward")])
    events = await _drain(client, q)
    vote_events = [e for e in events if isinstance(e, VoteNeededEvent)]
    state_types = [e.state.state_type for e in vote_events]
    assert "card_reward" in state_types


async def test_transition_to_idle_state_no_vote_needed():
    q: asyncio.Queue = asyncio.Queue()
    client = _make_client([_api_response("monster"), _api_response("overlay")])
    events = await _drain(client, q)
    vote_events = [e for e in events if isinstance(e, VoteNeededEvent)]
    assert all(e.state.state_type != "overlay" for e in vote_events)


# --- Same-state dedup ---

async def test_same_state_twice_no_duplicate_vote():
    q: asyncio.Queue = asyncio.Queue()
    client = _make_client([_api_response("map"), _api_response("map")])
    events = await _drain(client, q)
    vote_events = [e for e in events if isinstance(e, VoteNeededEvent)]
    assert len(vote_events) == 1


# --- API unreachable ---

async def test_api_unreachable_no_crash_no_event():
    q: asyncio.Queue = asyncio.Queue()
    client = _make_client([None])
    events = await _drain(client, q)
    assert events == []


async def test_api_recovers_after_none():
    q: asyncio.Queue = asyncio.Queue()
    client = _make_client([None, _api_response("shop")])
    events = await _drain(client, q)
    assert any(isinstance(e, VoteNeededEvent) for e in events)


# --- Combat within-turn re-queue ---

async def test_combat_enemy_turn_to_player_turn_emits_vote():
    """Polling detects is_play_phase flipping False→True and queues a new vote."""
    q: asyncio.Queue = asyncio.Queue()
    enemy_turn = _api_response("monster", battle={"is_play_phase": False, "round": 1, "enemies": []})
    player_turn = _api_response("monster", battle={"is_play_phase": True, "round": 1, "enemies": []})
    client = _make_client([enemy_turn, player_turn])
    events = await _drain(client, q)
    vote_events = [e for e in events if isinstance(e, VoteNeededEvent)]
    # First poll: is_play_phase=False, no vote. Second poll: is_play_phase=True → vote
    assert len(vote_events) >= 1


async def test_combat_new_round_detected_by_battle_round_increment():
    """battle.round incrementing while is_play_phase stays True signals a new player turn."""
    q: asyncio.Queue = asyncio.Queue()
    r1 = _api_response("monster", battle={"is_play_phase": True, "round": 1, "enemies": []})
    r2 = _api_response("monster", battle={"is_play_phase": True, "round": 2, "enemies": []})
    client = _make_client([r1, r2])
    events = await _drain(client, q)
    vote_events = [e for e in events if isinstance(e, VoteNeededEvent)]
    assert len(vote_events) >= 2  # initial + new round


def _state(state_type: str = "monster", **kwargs) -> GameState:
    """Build a GameState with sensible defaults for helper tests."""
    defaults = dict(
        state_type=state_type,
        act=None,
        floor=None,
        player_hp=None,
        player_max_hp=None,
    )
    defaults.update(kwargs)
    return GameState(**defaults)


# --- detect_transition ---

def test_detect_transition_initial_actionable_returns_vote():
    curr = _state("monster")
    ev = detect_transition(None, curr)
    assert isinstance(ev, VoteNeededEvent)
    assert ev.state is curr


def test_detect_transition_initial_menu_returns_menu_select():
    ev = detect_transition(None, _state("menu"))
    assert isinstance(ev, MenuSelectNeededEvent)


def test_detect_transition_initial_idle_returns_none():
    assert detect_transition(None, _state("game_over")) is None


def test_detect_transition_same_state_returns_none():
    s = _state("map")
    assert detect_transition(s, _state("map")) is None


def test_detect_transition_menu_to_combat_returns_game_started():
    ev = detect_transition(_state("menu"), _state("monster"))
    assert isinstance(ev, GameStartedEvent)


def test_detect_transition_to_game_over_returns_game_ended():
    ev = detect_transition(_state("monster"), _state("game_over"))
    assert isinstance(ev, GameEndedEvent)


def test_detect_transition_combat_to_overlay_returns_game_ended():
    ev = detect_transition(_state("monster"), _state("overlay"))
    assert isinstance(ev, GameEndedEvent)


def test_detect_transition_to_menu_returns_menu_select():
    ev = detect_transition(_state("monster"), _state("menu"))
    assert isinstance(ev, MenuSelectNeededEvent)


def test_detect_transition_to_actionable_returns_vote():
    ev = detect_transition(_state("monster"), _state("card_reward"))
    assert isinstance(ev, VoteNeededEvent)


def test_detect_transition_to_idle_non_overlay_returns_none():
    # non-combat → unknown (idle): not game_over, prev not combat, no input needed
    ev = detect_transition(_state("map"), _state("unknown"))
    assert ev is None


# --- _mid_turn_change_reason ---

def test_mid_turn_reason_none_when_no_change():
    prev = _state("monster", hand_size=3, playable_card_indices=[0, 1], player_potions=[], player_energy=3)
    curr = _state("monster", hand_size=3, playable_card_indices=[0, 1], player_potions=[], player_energy=3)
    assert _mid_turn_change_reason(prev, curr, None) is None


def test_mid_turn_reason_action_signal():
    prev = _state("monster", hand_size=3, player_energy=3)
    curr = _state("monster", hand_size=3, player_energy=3)
    sig = asyncio.Event()
    sig.set()
    assert _mid_turn_change_reason(prev, curr, sig) == "action_signal"


def test_mid_turn_reason_hand_size():
    prev = _state("monster", hand_size=3, player_energy=3)
    curr = _state("monster", hand_size=2, player_energy=3)
    assert _mid_turn_change_reason(prev, curr, None) == "hand_size"


def test_mid_turn_reason_playable():
    prev = _state("monster", hand_size=3, playable_card_indices=[0, 1], player_energy=3)
    curr = _state("monster", hand_size=3, playable_card_indices=[0], player_energy=3)
    assert _mid_turn_change_reason(prev, curr, None) == "playable"


def test_mid_turn_reason_potions():
    prev = _state("monster", hand_size=3, player_potions=[{"slot": 0}], player_energy=3)
    curr = _state("monster", hand_size=3, player_potions=[], player_energy=3)
    assert _mid_turn_change_reason(prev, curr, None) == "potions"


def test_mid_turn_reason_energy():
    prev = _state("monster", hand_size=3, player_energy=3)
    curr = _state("monster", hand_size=3, player_energy=1)
    assert _mid_turn_change_reason(prev, curr, None) == "energy"


# --- recheck_after_action ---

async def test_recheck_after_action_state_unchanged_returns_vote():
    prev = _state("monster", hand_size=3, player_potions=[{"slot": 0}])
    curr = _state("monster", hand_size=2, player_potions=[])
    # Recheck polls return the same state_type
    client = MagicMock()
    client.get_state = AsyncMock(return_value={"state_type": "monster"})
    final, event = await recheck_after_action(client, prev, curr, attempts=2, interval=0)
    assert final.state_type == "monster"
    assert isinstance(event, VoteNeededEvent)


async def test_recheck_after_action_state_changed_to_overlay_returns_game_ended():
    prev = _state("monster", hand_size=3)
    curr = _state("monster", hand_size=2)
    client = MagicMock()
    client.get_state = AsyncMock(return_value={"state_type": "overlay"})
    final, event = await recheck_after_action(client, prev, curr, attempts=2, interval=0)
    assert final.state_type == "overlay"
    assert isinstance(event, GameEndedEvent)


async def test_recheck_after_action_state_changed_to_actionable_returns_vote():
    prev = _state("monster", hand_size=3)
    curr = _state("monster", hand_size=2)
    client = MagicMock()
    client.get_state = AsyncMock(return_value={"state_type": "card_reward"})
    final, event = await recheck_after_action(client, prev, curr, attempts=2, interval=0)
    assert final.state_type == "card_reward"
    assert isinstance(event, VoteNeededEvent)


async def test_combat_to_overlay_during_mid_turn_recheck_emits_game_ended():
    """Death detected via mid-turn recheck path (card played → recheck → overlay)."""
    q: asyncio.Queue = asyncio.Queue()
    # r1: initial monster state with 2 cards in hand
    r1 = _api_response("monster", battle={"is_play_phase": True, "round": 1, "enemies": [], "hand": ["a", "b"]})
    # r2: same state but hand shrunk → triggers mid-turn recheck loop
    r2 = _api_response("monster", battle={"is_play_phase": True, "round": 1, "enemies": [], "hand": ["a"]})
    # r3: overlay — player died; detected during recheck
    r3 = _api_response("overlay")
    client = _make_client([r1, r2, r3])
    events = await _drain(client, q)
    assert any(isinstance(e, GameEndedEvent) for e in events)
