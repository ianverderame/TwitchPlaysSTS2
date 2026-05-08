"""Tests for state-entry announcements and run-welcome onboarding (#88)."""
from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.client import TwitchBot, _format_state_announcement
from game.events import GameEndedEvent
from game.state import GameState


def _state(state_type: str, **kwargs) -> GameState:
    """Build a GameState with sensible defaults for announcement tests."""
    defaults = dict(act=1, floor=1, player_hp=80, player_max_hp=80)
    defaults.update(kwargs)
    return GameState(state_type=state_type, **defaults)


# ---------------------------------------------------------------------------
# _format_state_announcement — pure formatter
# ---------------------------------------------------------------------------

def test_format_combat_monster_includes_enemy_hp():
    state = _state(
        "monster",
        enemies=[
            {"name": "Cultist", "hp": 20, "max_hp": 48, "entity_id": "e1"},
            {"name": "Acid Slime", "hp": 32, "max_hp": 32, "entity_id": "e2"},
        ],
    )
    msg = _format_state_announcement(state)
    assert msg is not None
    assert msg.startswith("⚔️ Combat")
    assert "Cultist (20/48)" in msg
    assert "Acid Slime (32/32)" in msg


def test_format_combat_elite_uses_combat_header():
    state = _state(
        "elite",
        enemies=[{"name": "Sentry", "hp": 40, "max_hp": 40, "entity_id": "e1"}],
    )
    msg = _format_state_announcement(state)
    assert msg is not None
    assert msg.startswith("⚔️ Combat")


def test_format_boss_uses_boss_header():
    state = _state(
        "boss",
        enemies=[{"name": "Hexaghost", "hp": 250, "max_hp": 250, "entity_id": "e1"}],
    )
    msg = _format_state_announcement(state)
    assert msg is not None
    assert msg.startswith("👑 BOSS")
    assert "Hexaghost (250/250)" in msg


def test_format_combat_with_no_enemies_falls_back_to_header_only():
    state = _state("monster", enemies=[])
    msg = _format_state_announcement(state)
    assert msg == "⚔️ Combat"


def test_format_shop_includes_player_gold():
    state = _state("shop", player_gold=137)
    msg = _format_state_announcement(state)
    assert msg == "🛒 Shop — Gold: 137"


def test_format_fake_merchant_uses_shop_header():
    state = _state("fake_merchant", player_gold=42)
    msg = _format_state_announcement(state)
    assert msg is not None
    assert msg.startswith("🛒 Shop")
    assert "42" in msg


def test_format_shop_handles_missing_gold():
    state = _state("shop", player_gold=None)
    msg = _format_state_announcement(state)
    assert msg == "🛒 Shop — Gold: ?"


def test_format_treasure_room():
    assert _format_state_announcement(_state("treasure")) == "💎 Treasure room"


def test_format_relic_select():
    assert _format_state_announcement(_state("relic_select")) == "🎁 Relic offered"


def test_format_rest_site():
    assert _format_state_announcement(_state("rest_site")) == "🛌 Rest site"


def test_format_event():
    assert _format_state_announcement(_state("event")) == "❓ Event"


def test_format_map_returns_none():
    assert _format_state_announcement(_state("map")) is None


def test_format_rewards_returns_none():
    assert _format_state_announcement(_state("rewards")) is None


def test_format_card_select_returns_none():
    assert _format_state_announcement(_state("card_select")) is None


# ---------------------------------------------------------------------------
# _announce_state_entry — bot-level dispatch + suppression
# ---------------------------------------------------------------------------

def _make_announcer_bot() -> MagicMock:
    bot = MagicMock(spec=TwitchBot)
    bot._chat = AsyncMock()
    bot._welcome_sent = False
    bot._last_announced_state_key = None
    bot._last_seen_act = None
    return bot


async def test_announce_state_entry_first_call_sends_chat():
    bot = _make_announcer_bot()
    state = _state("treasure", act=1, floor=3)

    await TwitchBot._announce_state_entry(bot, state)

    bot._chat.assert_awaited_once()
    assert "Treasure" in bot._chat.call_args.args[0]
    assert bot._last_announced_state_key == "treasure:1:3"


async def test_announce_state_entry_same_state_is_suppressed():
    """Within-state re-queues (e.g. mid-combat hand changes) must NOT re-announce."""
    bot = _make_announcer_bot()
    state = _state(
        "monster", act=1, floor=4,
        enemies=[{"name": "Jaw Worm", "hp": 42, "max_hp": 42, "entity_id": "e1"}],
    )

    await TwitchBot._announce_state_entry(bot, state)
    await TwitchBot._announce_state_entry(bot, state)

    assert bot._chat.await_count == 1


async def test_announce_state_entry_different_floor_re_announces():
    bot = _make_announcer_bot()
    s1 = _state("treasure", act=1, floor=3)
    s2 = _state("treasure", act=1, floor=9)

    await TwitchBot._announce_state_entry(bot, s1)
    await TwitchBot._announce_state_entry(bot, s2)

    assert bot._chat.await_count == 2


async def test_announce_state_entry_first_act_does_not_send_act_line():
    """Initial state of run records act=1 silently — welcome handles run-start framing."""
    bot = _make_announcer_bot()
    state = _state("treasure", act=1, floor=1)

    await TwitchBot._announce_state_entry(bot, state)

    texts = [c.args[0] for c in bot._chat.call_args_list]
    assert not any("Entering Act" in t for t in texts)
    assert bot._last_seen_act == 1


async def test_announce_state_entry_act_change_sends_act_line():
    bot = _make_announcer_bot()
    bot._last_seen_act = 1
    bot._last_announced_state_key = "treasure:1:9"
    state = _state("monster", act=2, floor=10,
                   enemies=[{"name": "Slime", "hp": 10, "max_hp": 10, "entity_id": "e1"}])

    await TwitchBot._announce_state_entry(bot, state)

    texts = [c.args[0] for c in bot._chat.call_args_list]
    assert any("Entering Act 2" in t for t in texts)
    assert any("⚔️ Combat" in t for t in texts)
    assert bot._last_seen_act == 2


async def test_announce_state_entry_skips_chat_for_unannounced_types_but_records_key():
    """map state has no announcement copy, but the key is still recorded so
    the next true state-entry isn't blocked."""
    bot = _make_announcer_bot()
    state = _state("map", act=1, floor=2)

    await TwitchBot._announce_state_entry(bot, state)

    bot._chat.assert_not_awaited()
    assert bot._last_announced_state_key == "map:1:2"


async def test_announce_state_entry_returns_to_same_state_after_intervening_does_re_announce():
    """treasure → map → treasure (different floor) re-fires; suppression is by exact key, not type."""
    bot = _make_announcer_bot()

    await TwitchBot._announce_state_entry(bot, _state("treasure", act=1, floor=3))
    await TwitchBot._announce_state_entry(bot, _state("map", act=1, floor=3))
    await TwitchBot._announce_state_entry(bot, _state("treasure", act=1, floor=6))

    treasure_msgs = [
        c for c in bot._chat.call_args_list if "Treasure" in c.args[0]
    ]
    assert len(treasure_msgs) == 2


# ---------------------------------------------------------------------------
# _send_run_welcome — character-select onboarding
# ---------------------------------------------------------------------------

def _make_welcome_bot() -> MagicMock:
    bot = MagicMock(spec=TwitchBot)
    bot._chat = AsyncMock()
    bot._welcome_sent = False
    bot.vote_manager = MagicMock()
    bot.vote_manager.duration = 60.0
    return bot


async def test_send_run_welcome_fires_three_messages():
    bot = _make_welcome_bot()

    await TwitchBot._send_run_welcome(bot)

    assert bot._chat.await_count == 3
    texts = [c.args[0] for c in bot._chat.call_args_list]
    assert any("new run is starting" in t for t in texts)
    assert any("How to vote" in t for t in texts)
    assert any("Info commands" in t for t in texts)


async def test_send_run_welcome_clarifies_potion_play_and_discard():
    """User feedback: !pN and !dN must be obviously play/discard, not generic 'use'."""
    bot = _make_welcome_bot()

    await TwitchBot._send_run_welcome(bot)

    texts = " ".join(c.args[0] for c in bot._chat.call_args_list)
    assert "play potion" in texts.lower()
    assert "discard potion" in texts.lower()


async def test_send_run_welcome_includes_vote_window_seconds():
    bot = _make_welcome_bot()
    bot.vote_manager.duration = 45.0

    await TwitchBot._send_run_welcome(bot)

    texts = " ".join(c.args[0] for c in bot._chat.call_args_list)
    assert "45s" in texts


async def test_send_run_welcome_only_fires_once_per_run():
    bot = _make_welcome_bot()

    await TwitchBot._send_run_welcome(bot)
    await TwitchBot._send_run_welcome(bot)

    assert bot._chat.await_count == 3  # first call only; second is no-op
    assert bot._welcome_sent is True


# ---------------------------------------------------------------------------
# _handle_game_ended — flag reset
# ---------------------------------------------------------------------------

@pytest.fixture
def no_sleep(monkeypatch):
    monkeypatch.setattr("bot.client.asyncio.sleep", AsyncMock())


async def test_handle_game_ended_resets_announcement_flags(no_sleep):
    """End-of-run must reset welcome + state-entry tracking so next run is fresh."""
    bot = MagicMock(spec=TwitchBot)
    bot._chat = AsyncMock()
    bot._end_game_screen_pause = 0.0
    bot._end_game_screen_max_nav_attempts = 0  # short-circuit nav loop
    bot._new_game_countdown = 0.0
    bot._timeline_epoch_claim_delay = 0.0
    bot._game_client = MagicMock()
    bot._game_client.get_state = AsyncMock(return_value=None)
    bot._menu_client = MagicMock()
    bot._menu_client.get_menu_state = AsyncMock(return_value={"screen": "MAIN_MENU"})

    bot._welcome_sent = True
    bot._last_announced_state_key = "treasure:2:14"
    bot._last_seen_act = 2

    end_event = GameEndedEvent(state=GameState(
        state_type="overlay", act=2, floor=14, player_hp=0, player_max_hp=70
    ))
    await TwitchBot._handle_game_ended(bot, end_event)

    assert bot._welcome_sent is False
    assert bot._last_announced_state_key is None
    assert bot._last_seen_act is None


# ---------------------------------------------------------------------------
# _handle_vote_needed — announcement runs before auto_proceed / vote
# ---------------------------------------------------------------------------

async def test_handle_vote_needed_announces_state_entry_before_auto_proceed():
    """Treasure auto-proceeds, but the entry announcement must still fire so chat
    isn't left silent on rooms that resolve without a vote."""
    from game.events import VoteNeededEvent

    bot = MagicMock(spec=TwitchBot)
    bot._announce_state_entry = AsyncMock()
    bot._try_auto_proceed = AsyncMock(return_value=True)

    state = _state(
        "treasure", act=1, floor=3,
        treasure_relics=[{"index": 0, "name": "Burning Blood"}],
    )
    broadcaster = MagicMock()

    await TwitchBot._handle_vote_needed(bot, VoteNeededEvent(state), broadcaster)

    bot._announce_state_entry.assert_awaited_once_with(state)
    bot._try_auto_proceed.assert_awaited_once()
