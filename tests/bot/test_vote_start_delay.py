"""Tests for the centralized vote-dispatch flow: pre-announce sleep + staleness check."""
from unittest.mock import AsyncMock, MagicMock, patch

from bot.client import TwitchBot
from game.state import GameState


def _make_bot_for_dispatch_check(
    fresh_state: GameState | None, stream_latency: float = 0.0
) -> MagicMock:
    bot = MagicMock(spec=TwitchBot)
    bot._stream_latency = stream_latency
    bot._fetch_parsed_state = AsyncMock(return_value=fresh_state)
    bot._is_stale_state = lambda current, expected, ctx="vote": (
        TwitchBot._is_stale_state(bot, current, expected, ctx)
    )
    return bot


async def test_check_vote_dispatch_returns_fresh_state_when_stable():
    event_state = GameState(state_type="event", act=1, floor=1, player_hp=80, player_max_hp=80)
    fresh = GameState(state_type="event", act=1, floor=1, player_hp=75, player_max_hp=80)
    bot = _make_bot_for_dispatch_check(fresh)

    result = await TwitchBot._check_vote_dispatch(bot, event_state)

    assert result is fresh
    bot._fetch_parsed_state.assert_awaited_once()


async def test_check_vote_dispatch_returns_none_on_state_type_mismatch():
    event_state = GameState(state_type="event", act=1, floor=1, player_hp=80, player_max_hp=80)
    fresh = GameState(state_type="map", act=1, floor=2, player_hp=80, player_max_hp=80)
    bot = _make_bot_for_dispatch_check(fresh)

    result = await TwitchBot._check_vote_dispatch(bot, event_state)

    assert result is None


async def test_check_vote_dispatch_returns_none_on_combat_enemy_turn():
    event_state = GameState(state_type="monster", act=1, floor=2, player_hp=80, player_max_hp=80, is_play_phase=True)
    fresh = GameState(state_type="monster", act=1, floor=2, player_hp=78, player_max_hp=80, is_play_phase=False)
    bot = _make_bot_for_dispatch_check(fresh)

    result = await TwitchBot._check_vote_dispatch(bot, event_state)

    assert result is None


async def test_check_vote_dispatch_fail_open_when_fetch_returns_none():
    event_state = GameState(state_type="event", act=1, floor=1, player_hp=80, player_max_hp=80)
    bot = _make_bot_for_dispatch_check(None)

    result = await TwitchBot._check_vote_dispatch(bot, event_state)

    assert result is event_state


async def test_check_vote_dispatch_sleeps_stream_latency_before_fetch():
    """Pre-announce sleep keeps the chat prompt synced with what stream-watchers see."""
    event_state = GameState(state_type="event", act=1, floor=1, player_hp=80, player_max_hp=80)
    fresh = GameState(state_type="event", act=1, floor=1, player_hp=75, player_max_hp=80)
    bot = _make_bot_for_dispatch_check(fresh, stream_latency=5.0)

    with patch("bot.client.asyncio.sleep", new_callable=AsyncMock) as sleep_mock:
        result = await TwitchBot._check_vote_dispatch(bot, event_state)

    assert result is fresh
    sleep_mock.assert_awaited_once_with(5.0)


async def test_check_vote_dispatch_zero_latency_skips_sleep():
    event_state = GameState(state_type="event", act=1, floor=1, player_hp=80, player_max_hp=80)
    fresh = GameState(state_type="event", act=1, floor=1, player_hp=75, player_max_hp=80)
    bot = _make_bot_for_dispatch_check(fresh, stream_latency=0.0)

    with patch("bot.client.asyncio.sleep", new_callable=AsyncMock) as sleep_mock:
        await TwitchBot._check_vote_dispatch(bot, event_state)

    sleep_mock.assert_not_awaited()
