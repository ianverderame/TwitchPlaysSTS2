import random
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from bot.vote_manager import VoteManager


# --- run_window helpers ---

def _broadcaster() -> MagicMock:
    b = MagicMock()
    b.send_message = AsyncMock()
    return b


async def _run(vm: VoteManager, options: list[str], votes: dict[str, str] | None = None, **kwargs) -> tuple[str, MagicMock]:
    """Run a vote window, injecting votes during the sleep, return (winner, broadcaster).

    Votes are injected by patching asyncio.sleep so they arrive after the window
    opens (and _votes is cleared) but before _tally runs.
    """
    broadcaster = _broadcaster()

    async def _sleep_and_inject(_duration):
        if votes:
            for uid, choice in votes.items():
                vm._votes[uid] = choice  # bypass record_vote — window is "open" during sleep

    with patch("bot.vote_manager.asyncio.sleep", side_effect=_sleep_and_inject):
        result = await vm.run_window(
            broadcaster=broadcaster,
            bot_id="bot-123",
            options=options,
            state_summary="test state",
            duration=0,
            **kwargs,
        )
    return result, broadcaster


def _manager() -> VoteManager:
    return VoteManager(duration=10.0)


def _open_manager(options: list[str]) -> VoteManager:
    vm = _manager()
    vm._open = True
    vm._options = frozenset(options)
    return vm


# --- _tally ---

def test_single_voter_wins():
    vm = _open_manager(["1", "2", "end"])
    vm.record_vote("user1", "2")
    winner, was_random, was_tie = vm._tally(["1", "2", "end"])
    assert winner == "2"
    assert not was_random
    assert not was_tie


def test_majority_wins():
    vm = _open_manager(["1", "2", "end"])
    vm.record_vote("u1", "1")
    vm.record_vote("u2", "1")
    vm.record_vote("u3", "2")
    winner, was_random, was_tie = vm._tally(["1", "2", "end"])
    assert winner == "1"
    assert not was_random
    assert not was_tie


def test_no_votes_picks_from_numeric_not_terminal():
    vm = _open_manager(["1", "2", "end"])
    results = set()
    for _ in range(50):
        winner, was_random, was_tie = vm._tally(["1", "2", "end"])
        results.add(winner)
        assert was_random
        assert not was_tie
    assert "end" not in results
    assert results.issubset({"1", "2"})


def test_no_votes_falls_back_to_all_when_no_numerics():
    vm = _open_manager(["end", "skip"])
    results = set()
    for _ in range(50):
        winner, was_random, _ = vm._tally(["end", "skip"])
        results.add(winner)
    assert results.issubset({"end", "skip"})


def test_tie_prefers_numeric_over_terminal():
    vm = _open_manager(["1", "end"])
    vm.record_vote("u1", "1")
    vm.record_vote("u2", "end")
    results = set()
    for _ in range(50):
        vm._votes = {"u1": "1", "u2": "end"}
        winner, was_random, was_tie = vm._tally(["1", "end"])
        results.add(winner)
        assert was_tie
        assert not was_random
    assert results == {"1"}  # tie-break should always pick "1" (only numeric tied)


def test_tie_among_numerics_picks_one_of_them():
    vm = _open_manager(["1", "2", "end"])
    vm.record_vote("u1", "1")
    vm.record_vote("u2", "2")
    results = set()
    for _ in range(50):
        vm._votes = {"u1": "1", "u2": "2"}
        winner, _, was_tie = vm._tally(["1", "2", "end"])
        results.add(winner)
        assert was_tie
    assert results.issubset({"1", "2"})
    assert "end" not in results


# --- record_vote ---

def test_record_vote_no_op_when_closed():
    vm = _manager()
    vm._open = False
    vm._options = frozenset(["1", "2"])
    vm.record_vote("user1", "1")
    assert vm._votes == {}


def test_record_vote_no_op_for_invalid_choice():
    vm = _open_manager(["1", "2"])
    vm.record_vote("user1", "99")
    assert vm._votes == {}


def test_record_vote_registers_valid_choice():
    vm = _open_manager(["1", "2"])
    vm.record_vote("user1", "1")
    assert vm._votes["user1"] == "1"


def test_record_vote_overwrites_previous():
    vm = _open_manager(["1", "2"])
    vm.record_vote("user1", "1")
    vm.record_vote("user1", "2")
    assert vm._votes["user1"] == "2"
    assert len(vm._votes) == 1


def test_record_vote_different_users_independent():
    vm = _open_manager(["1", "2"])
    vm.record_vote("user1", "1")
    vm.record_vote("user2", "2")
    assert vm._votes["user1"] == "1"
    assert vm._votes["user2"] == "2"


# --- run_window ---

async def test_run_window_returns_winner_string():
    vm = _manager()
    winner, _ = await _run(vm, ["1", "2", "end"], votes={"u1": "2", "u2": "2"})
    assert winner == "2"
    assert isinstance(winner, str)


async def test_run_window_announces_options_on_open():
    vm = _manager()
    _, broadcaster = await _run(vm, ["1", "2", "end"])
    first_call_msg = broadcaster.send_message.call_args_list[0].kwargs["message"]
    assert "!1" in first_call_msg
    assert "!2" in first_call_msg
    assert "!end" in first_call_msg


async def test_run_window_winner_message_sent():
    vm = _manager()
    _, broadcaster = await _run(vm, ["1", "2"], votes={"u1": "1", "u2": "1"})
    close_msg = broadcaster.send_message.call_args_list[-1].kwargs["message"]
    assert "Winner" in close_msg
    assert "!1" in close_msg


async def test_run_window_no_votes_random_message():
    vm = _manager()
    _, broadcaster = await _run(vm, ["1", "2"])
    close_msg = broadcaster.send_message.call_args_list[-1].kwargs["message"]
    assert "no votes" in close_msg.lower() or "random" in close_msg.lower()


async def test_run_window_tie_message():
    vm = _manager()
    _, broadcaster = await _run(vm, ["1", "2"], votes={"u1": "1", "u2": "2"})
    close_msg = broadcaster.send_message.call_args_list[-1].kwargs["message"]
    assert "Tie" in close_msg or "tie" in close_msg


async def test_run_window_silent_skips_opening_message():
    vm = _manager()
    _, broadcaster = await _run(vm, ["1", "2"], silent=True)
    assert broadcaster.send_message.call_count == 1  # only the close message


async def test_run_window_labels_shown_in_opening():
    vm = _manager()
    labels = {"1": "Strike", "2": "Defend"}
    _, broadcaster = await _run(vm, ["1", "2"], labels=labels)
    first_msg = broadcaster.send_message.call_args_list[0].kwargs["message"]
    assert "Strike" in first_msg
    assert "Defend" in first_msg


async def test_run_window_bot_id_passed_to_send_message():
    vm = _manager()
    _, broadcaster = await _run(vm, ["1"])
    for c in broadcaster.send_message.call_args_list:
        assert c.kwargs["sender"] == "bot-123"
        assert c.kwargs["token_for"] == "bot-123"
