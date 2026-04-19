"""Tests for TwitchBot._handle_game_ended, _navigate_timeline_screen, and _navigate_main_menu_timeline."""
import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.client import TwitchBot
from game.events import GameEndedEvent
from game.state import GameState


def _api_response(state_type: str) -> dict:
    return {"state_type": state_type}


def _menu_state(
    screen: str = "GAME_OVER",
    epochs: list | None = None,
    available_actions: list | None = None,
) -> dict:
    data: dict = {"screen": screen, "available_actions": available_actions or []}
    if epochs is not None:
        data["epochs"] = epochs
    return data


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    """Patch asyncio.sleep in bot.client so tests never actually sleep."""
    monkeypatch.setattr("bot.client.asyncio.sleep", AsyncMock())


def _make_bot_self(
    get_state_responses: list,
    get_menu_state_responses: list | None = None,
    new_game_countdown: float = 0.0,
) -> MagicMock:
    """Build a mock TwitchBot instance for _handle_game_ended tests.

    get_menu_state call counts per loop iteration:
      - Non-GAME_OVER / non-TIMELINE screens: 1 call
      - GAME_OVER screen: 1 call (then return_to_main_menu via menu_client)
      - TIMELINE screen: 1 call (then _navigate_timeline_screen)
      - Post-break (menu reached): 1 call (+ 1 more if open_timeline is called)

    If get_menu_state_responses is None, return_value=GAME_OVER is used (never exhausts).
    """
    bot = MagicMock(spec=TwitchBot)
    bot._end_game_screen_pause = 0.0
    bot._new_game_countdown = new_game_countdown
    bot._timeline_epoch_claim_delay = 0.0

    bot._chat = AsyncMock()

    bot._game_client = MagicMock()
    bot._game_client.get_state = AsyncMock(side_effect=get_state_responses)
    bot._game_client.post_action = AsyncMock(return_value={"status": "ok"})

    bot._menu_client = MagicMock()
    if get_menu_state_responses is not None:
        bot._menu_client.get_menu_state = AsyncMock(side_effect=get_menu_state_responses)
    else:
        bot._menu_client.get_menu_state = AsyncMock(return_value=_menu_state("GAME_OVER"))
    bot._menu_client.post_menu_action = AsyncMock(return_value={"status": "ok"})

    # Wire _navigate_timeline_screen and _navigate_main_menu_timeline to the real
    # implementations so integration tests exercise the actual action sequences.
    async def _real_navigate_timeline(menu_data: dict) -> None:
        await TwitchBot._navigate_timeline_screen(bot, menu_data)

    async def _real_navigate_main_menu_timeline(menu_data: dict) -> None:
        await TwitchBot._navigate_main_menu_timeline(bot, menu_data)

    bot._navigate_timeline_screen = _real_navigate_timeline
    bot._navigate_main_menu_timeline = _real_navigate_main_menu_timeline

    return bot


def _game_ended_event() -> GameEndedEvent:
    state = GameState(state_type="overlay", act=1, floor=5, player_hp=0, player_max_hp=70)
    return GameEndedEvent(state=state)


# ---------------------------------------------------------------------------
# _handle_game_ended — basic navigation
# ---------------------------------------------------------------------------

async def test_game_over_screen_calls_return_to_main_menu():
    """GAME_OVER screen → return_to_main_menu via MenuControl to exit the death screen."""
    # Call sequence: 1 initial get_menu_state (GAME_OVER) + 1 post-break (MAIN_MENU)
    bot = _make_bot_self(
        get_state_responses=[_api_response("overlay"), _api_response("menu")],
        get_menu_state_responses=[_menu_state("GAME_OVER"), _menu_state("MAIN_MENU")],
    )
    await TwitchBot._handle_game_ended(bot, _game_ended_event())

    return_calls = [
        c for c in bot._menu_client.post_menu_action.call_args_list
        if c.args[0] == "return_to_main_menu"
    ]
    assert len(return_calls) == 1
    bot._game_client.post_action.assert_not_called()


async def test_menu_immediately_skips_navigation():
    """If STS2MCP already reports menu, no actions are posted."""
    bot = _make_bot_self(
        get_state_responses=[_api_response("menu")],
        get_menu_state_responses=[_menu_state("MAIN_MENU")],
    )
    await TwitchBot._handle_game_ended(bot, _game_ended_event())

    bot._game_client.post_action.assert_not_called()
    bot._menu_client.post_menu_action.assert_not_called()


async def test_chat_messages_sent():
    """Both 'Run over' and 'New game starting' announcements are made."""
    bot = _make_bot_self(
        get_state_responses=[_api_response("menu")],
        get_menu_state_responses=[_menu_state("MAIN_MENU")],
    )
    await TwitchBot._handle_game_ended(bot, _game_ended_event())

    texts = [c.args[0] for c in bot._chat.call_args_list]
    assert any("Run over" in t for t in texts)
    assert any("New game starting" in t for t in texts)


async def test_countdown_value_in_announcement():
    """Countdown seconds come from _new_game_countdown, not hardcoded."""
    bot = _make_bot_self(
        get_state_responses=[_api_response("menu")],
        get_menu_state_responses=[_menu_state("MAIN_MENU")],
        new_game_countdown=42.0,
    )
    await TwitchBot._handle_game_ended(bot, _game_ended_event())

    texts = [c.args[0] for c in bot._chat.call_args_list]
    assert any("42s" in t for t in texts)


async def test_game_api_down_exits_without_countdown():
    """If get_state returns None, exit cleanly — no countdown announcement."""
    bot = _make_bot_self(get_state_responses=[None])
    await TwitchBot._handle_game_ended(bot, _game_ended_event())

    texts = [c.args[0] for c in bot._chat.call_args_list]
    assert not any("New game" in t for t in texts)


async def test_max_attempts_exceeded_exits_without_countdown():
    """If menu is never reached after 20 attempts, give up — no countdown."""
    # Default return_value=GAME_OVER never exhausts across 20 iterations
    bot = _make_bot_self(get_state_responses=[_api_response("overlay")] * 25)
    await TwitchBot._handle_game_ended(bot, _game_ended_event())

    texts = [c.args[0] for c in bot._chat.call_args_list]
    assert not any("New game" in t for t in texts)
    return_calls = [
        c for c in bot._menu_client.post_menu_action.call_args_list
        if c.args[0] == "return_to_main_menu"
    ]
    assert len(return_calls) == 20


async def test_unknown_menu_screen_waits_without_action():
    """An unexpected MenuControl screen takes no action that iteration."""
    # Call sequence:
    #   Iter 1 (overlay): IN_GAME → no action
    #   Iter 2 (overlay): GAME_OVER → return_to_main_menu
    #   Post-break (menu): MAIN_MENU
    bot = _make_bot_self(
        get_state_responses=[_api_response("overlay"), _api_response("overlay"), _api_response("menu")],
        get_menu_state_responses=[
            _menu_state("IN_GAME"),
            _menu_state("GAME_OVER"),
            _menu_state("MAIN_MENU"),
        ],
    )
    await TwitchBot._handle_game_ended(bot, _game_ended_event())

    return_calls = [
        c for c in bot._menu_client.post_menu_action.call_args_list
        if c.args[0] == "return_to_main_menu"
    ]
    assert len(return_calls) == 1  # only the GAME_OVER iteration, not IN_GAME


# ---------------------------------------------------------------------------
# _handle_game_ended — timeline path (post-game overlay)
# ---------------------------------------------------------------------------

async def test_timeline_in_main_loop_is_navigated():
    """TIMELINE in the main loop (state never changes to menu mid-loop) is navigated."""
    # Call sequence: TIMELINE → navigate, then menu → post-break: MAIN_MENU
    two_epochs = [{"index": 0, "state": "NotObtained"}, {"index": 1, "state": "NotObtained"}]
    bot = _make_bot_self(
        get_state_responses=[_api_response("overlay"), _api_response("menu")],
        get_menu_state_responses=[
            _menu_state("TIMELINE", epochs=two_epochs),
            _menu_state("MAIN_MENU"),
        ],
    )
    await TwitchBot._handle_game_ended(bot, _game_ended_event())

    actions = [c.args[0] for c in bot._menu_client.post_menu_action.call_args_list]
    assert "choose_timeline_epoch" in actions
    assert "confirm_timeline_overlay" in actions
    bot._game_client.post_action.assert_not_called()


async def test_timeline_detected_at_post_break_check():
    """TIMELINE pending when STS2MCP first reports menu is caught by the post-break check."""
    # Call sequence:
    #   Iter 1 (overlay): GAME_OVER → return_to_main_menu
    #   Post-break (menu): TIMELINE → navigate
    one_epoch = [{"index": 0, "state": "NotObtained"}]
    bot = _make_bot_self(
        get_state_responses=[_api_response("overlay"), _api_response("menu")],
        get_menu_state_responses=[
            _menu_state("GAME_OVER"),
            _menu_state("TIMELINE", epochs=one_epoch),
        ],
    )
    await TwitchBot._handle_game_ended(bot, _game_ended_event())

    actions = [c.args[0] for c in bot._menu_client.post_menu_action.call_args_list]
    assert "choose_timeline_epoch" in actions
    texts = [c.args[0] for c in bot._chat.call_args_list]
    assert any("New game starting" in t for t in texts)


async def test_full_flow_death_report_timeline_countdown():
    """Full post-run flow: GAME_OVER × 2 → TIMELINE → menu → countdown."""
    one_epoch = [{"index": 0, "state": "NotObtained"}]
    bot = _make_bot_self(
        get_state_responses=[_api_response("overlay"), _api_response("overlay"), _api_response("menu")],
        get_menu_state_responses=[
            _menu_state("GAME_OVER"),   # death screen → return_to_main_menu
            _menu_state("GAME_OVER"),   # post-game report → return_to_main_menu
            _menu_state("TIMELINE", epochs=one_epoch),  # post-break: timeline
        ],
    )
    await TwitchBot._handle_game_ended(bot, _game_ended_event())

    return_calls = [
        c for c in bot._menu_client.post_menu_action.call_args_list
        if c.args[0] == "return_to_main_menu"
    ]
    assert len(return_calls) == 2

    timeline_actions = [c.args[0] for c in bot._menu_client.post_menu_action.call_args_list]
    assert "choose_timeline_epoch" in timeline_actions

    texts = [c.args[0] for c in bot._chat.call_args_list]
    assert any("New game starting" in t for t in texts)


# ---------------------------------------------------------------------------
# _handle_game_ended — main menu timeline path
# ---------------------------------------------------------------------------

async def test_main_menu_open_timeline_claims_obtained_epochs():
    """MAIN_MENU with open_timeline available → open timeline, claim Obtained epochs, close."""
    # Call sequence:
    #   Iter 1 (overlay): GAME_OVER → return_to_main_menu
    #   Post-break (menu): MAIN_MENU with open_timeline → open_timeline call
    #   After open_timeline: TIMELINE with one Obtained epoch
    one_epoch = [{"index": 2, "state": "Obtained"}]
    bot = _make_bot_self(
        get_state_responses=[_api_response("overlay"), _api_response("menu")],
        get_menu_state_responses=[
            _menu_state("GAME_OVER"),
            _menu_state("MAIN_MENU", available_actions=["open_timeline"]),
            _menu_state("TIMELINE", epochs=one_epoch),
        ],
    )
    await TwitchBot._handle_game_ended(bot, _game_ended_event())

    actions = [c.args[0] for c in bot._menu_client.post_menu_action.call_args_list]
    assert "open_timeline" in actions
    assert "choose_timeline_epoch" in actions
    assert "close_main_menu_submenu" in actions


async def test_main_menu_no_open_timeline_skips_timeline():
    """MAIN_MENU without open_timeline in available_actions skips timeline navigation."""
    bot = _make_bot_self(
        get_state_responses=[_api_response("menu")],
        get_menu_state_responses=[_menu_state("MAIN_MENU")],
    )
    await TwitchBot._handle_game_ended(bot, _game_ended_event())

    actions = [c.args[0] for c in bot._menu_client.post_menu_action.call_args_list]
    assert "open_timeline" not in actions
    assert "close_main_menu_submenu" not in actions


# ---------------------------------------------------------------------------
# _navigate_timeline_screen — unit tests (post-game overlay path)
# ---------------------------------------------------------------------------

def _make_bot_for_timeline() -> MagicMock:
    bot = MagicMock(spec=TwitchBot)
    bot._timeline_epoch_claim_delay = 0.0
    bot._menu_client = MagicMock()
    bot._menu_client.post_menu_action = AsyncMock(return_value={"status": "ok"})
    return bot


async def test_navigate_timeline_clicks_each_epoch():
    """Each epoch gets a choose_timeline_epoch call with the correct index."""
    epochs = [
        {"index": 0, "state": "NotObtained"},
        {"index": 1, "state": "NotObtained"},
        {"index": 2, "state": "Obtained"},
    ]
    bot = _make_bot_for_timeline()
    await TwitchBot._navigate_timeline_screen(bot, {"epochs": epochs})

    choose_calls = [
        c for c in bot._menu_client.post_menu_action.call_args_list
        if c.args[0] == "choose_timeline_epoch"
    ]
    assert len(choose_calls) == 3
    indices = [c.kwargs["option_index"] for c in choose_calls]
    assert indices == [0, 1, 2]


async def test_navigate_timeline_confirms_after_each_epoch():
    """confirm_timeline_overlay is called after each epoch and once more at the end."""
    epochs = [{"index": 0, "state": "NotObtained"}, {"index": 1, "state": "NotObtained"}]
    bot = _make_bot_for_timeline()
    await TwitchBot._navigate_timeline_screen(bot, {"epochs": epochs})

    confirm_calls = [
        c for c in bot._menu_client.post_menu_action.call_args_list
        if c.args[0] == "confirm_timeline_overlay"
    ]
    assert len(confirm_calls) == len(epochs) + 1


async def test_navigate_timeline_empty_epochs_only_final_confirm():
    """With no epochs, only the final confirm_timeline_overlay is sent."""
    bot = _make_bot_for_timeline()
    await TwitchBot._navigate_timeline_screen(bot, {"epochs": []})

    actions = [c.args[0] for c in bot._menu_client.post_menu_action.call_args_list]
    assert actions == ["confirm_timeline_overlay"]


async def test_navigate_timeline_no_epochs_key():
    """Missing 'epochs' key is treated as empty — only final confirm sent."""
    bot = _make_bot_for_timeline()
    await TwitchBot._navigate_timeline_screen(bot, {})

    actions = [c.args[0] for c in bot._menu_client.post_menu_action.call_args_list]
    assert actions == ["confirm_timeline_overlay"]


# ---------------------------------------------------------------------------
# _navigate_main_menu_timeline — unit tests (main menu path)
# ---------------------------------------------------------------------------

async def test_navigate_main_menu_timeline_claims_obtained_epochs():
    """Obtained epochs are claimed; close_main_menu_submenu is called at the end."""
    epochs = [
        {"index": 0, "state": "Complete"},
        {"index": 1, "state": "Obtained"},
        {"index": 2, "state": "Complete"},
    ]
    bot = _make_bot_for_timeline()
    await TwitchBot._navigate_main_menu_timeline(bot, {"epochs": epochs})

    choose_calls = [
        c for c in bot._menu_client.post_menu_action.call_args_list
        if c.args[0] == "choose_timeline_epoch"
    ]
    assert len(choose_calls) == 1
    assert choose_calls[0].kwargs["option_index"] == 1

    actions = [c.args[0] for c in bot._menu_client.post_menu_action.call_args_list]
    assert "close_main_menu_submenu" in actions


async def test_navigate_main_menu_timeline_skips_complete_epochs():
    """Complete epochs are not clicked."""
    epochs = [{"index": 0, "state": "Complete"}, {"index": 1, "state": "Complete"}]
    bot = _make_bot_for_timeline()
    await TwitchBot._navigate_main_menu_timeline(bot, {"epochs": epochs})

    choose_calls = [
        c for c in bot._menu_client.post_menu_action.call_args_list
        if c.args[0] == "choose_timeline_epoch"
    ]
    assert len(choose_calls) == 0

    actions = [c.args[0] for c in bot._menu_client.post_menu_action.call_args_list]
    assert actions == ["close_main_menu_submenu"]


async def test_navigate_main_menu_timeline_empty_epochs_closes_submenu():
    """With no epochs, only close_main_menu_submenu is sent."""
    bot = _make_bot_for_timeline()
    await TwitchBot._navigate_main_menu_timeline(bot, {"epochs": []})

    actions = [c.args[0] for c in bot._menu_client.post_menu_action.call_args_list]
    assert actions == ["close_main_menu_submenu"]


async def test_navigate_main_menu_timeline_multiple_obtained_all_claimed():
    """Multiple Obtained epochs are all claimed in index order."""
    epochs = [
        {"index": 0, "state": "Obtained"},
        {"index": 1, "state": "Complete"},
        {"index": 2, "state": "Obtained"},
    ]
    bot = _make_bot_for_timeline()
    await TwitchBot._navigate_main_menu_timeline(bot, {"epochs": epochs})

    choose_calls = [
        c for c in bot._menu_client.post_menu_action.call_args_list
        if c.args[0] == "choose_timeline_epoch"
    ]
    assert len(choose_calls) == 2
    assert [c.kwargs["option_index"] for c in choose_calls] == [0, 2]
