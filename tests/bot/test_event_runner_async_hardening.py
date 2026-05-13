"""Async-hardening tests for bot.client event-runner (issue #91).

Covers:
- _log_event_runner_exit surfaces unhandled exceptions via the logger
  (replacing the old fire-and-forget create_task that silently swallowed them).
- _log_event_runner_exit does NOT log an error for a CancelledError exit.
- task_done() is NOT called when queue.get() raises (CancelledError during
  shutdown must not double-mark the queue).
- task_done() IS called exactly once per successfully-dequeued event,
  including when handler code raises.
"""
import asyncio
import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bot.client import _log_event_runner_exit


# --- _log_event_runner_exit callback ---

def test_log_event_runner_exit_logs_unhandled_exception(caplog):
    """An event-runner task that raised should be logged at ERROR."""
    loop = asyncio.new_event_loop()
    try:
        async def boom() -> None:
            raise RuntimeError("event-runner died early")

        task = loop.create_task(boom())
        # Drive the task to completion so it captures the exception.
        with pytest.raises(RuntimeError):
            loop.run_until_complete(task)

        with caplog.at_level(logging.ERROR, logger="bot.client"):
            _log_event_runner_exit(task)

        assert any(
            "Event runner task exited with unhandled exception" in rec.message
            for rec in caplog.records
        )
    finally:
        loop.close()


def test_log_event_runner_exit_silent_on_cancellation(caplog):
    """Cancellation is a normal shutdown path — must NOT log at ERROR."""
    loop = asyncio.new_event_loop()
    try:
        async def forever() -> None:
            await asyncio.sleep(3600)

        task = loop.create_task(forever())
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            loop.run_until_complete(task)

        with caplog.at_level(logging.DEBUG, logger="bot.client"):
            _log_event_runner_exit(task)

        error_records = [r for r in caplog.records if r.levelno >= logging.ERROR]
        assert error_records == []
    finally:
        loop.close()


# --- task_done semantics in the event-runner consumer loop ---

class _GetRaisesQueue:
    """Minimal asyncio.Queue stand-in whose get() always raises CancelledError
    and which records every task_done() call so we can assert it was NOT called.
    """

    def __init__(self) -> None:
        self.task_done_calls: int = 0

    async def get(self):
        raise asyncio.CancelledError()

    def task_done(self) -> None:
        self.task_done_calls += 1

    def qsize(self) -> int:
        return 0


async def test_event_runner_does_not_call_task_done_when_get_raises():
    """If queue.get() raises CancelledError, task_done() must NOT fire."""
    from bot import client as bot_client

    queue = _GetRaisesQueue()

    # Build a bare object that satisfies the attributes _event_runner reads.
    obj = MagicMock()
    obj._event_queue = queue
    obj._ready = asyncio.Event()
    obj._ready.set()
    obj.broadcaster = MagicMock()

    coro = bot_client.TwitchBot._event_runner(obj)
    with pytest.raises(asyncio.CancelledError):
        await coro

    assert queue.task_done_calls == 0, (
        "task_done() must not be called when get() raised — "
        "would double-mark the queue on shutdown."
    )


async def test_event_runner_calls_task_done_once_per_successful_get():
    """A successfully-dequeued event must yield exactly one task_done() call,
    even if the handler raises."""
    from bot import client as bot_client
    from game.events import VoteNeededEvent

    # Use a real queue with one event, then a CancelledError to terminate.
    real_queue: asyncio.Queue = asyncio.Queue()
    state = MagicMock()
    state.state_type = "monster"
    state.card_select_screen_type = None
    event = VoteNeededEvent(state)
    real_queue.put_nowait(event)

    task_done_calls = []
    original_task_done = real_queue.task_done

    def counting_task_done() -> None:
        task_done_calls.append(1)
        original_task_done()

    original_get = real_queue.get
    get_call_count = {"n": 0}

    async def get_then_cancel():
        get_call_count["n"] += 1
        if get_call_count["n"] == 1:
            return await original_get()
        raise asyncio.CancelledError()

    real_queue.get = get_then_cancel  # type: ignore[assignment]
    real_queue.task_done = counting_task_done  # type: ignore[assignment]

    obj = MagicMock()
    obj._event_queue = real_queue
    obj._ready = asyncio.Event()
    obj._ready.set()
    obj.broadcaster = MagicMock()
    # Make the handler raise so we exercise the except-then-finally path.
    obj._check_vote_dispatch = AsyncMock(side_effect=RuntimeError("handler boom"))

    coro = bot_client.TwitchBot._event_runner(obj)
    with pytest.raises(asyncio.CancelledError):
        await coro

    assert len(task_done_calls) == 1, (
        f"Expected exactly one task_done() (one successful get), got {len(task_done_calls)}"
    )
