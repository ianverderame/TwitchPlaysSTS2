"""Async-hardening tests for game.polling (issue #91).

Covers:
- poll_game_state re-raises asyncio.CancelledError instead of swallowing it.
- poll_game_state escalates (raises) after POLL_MAX_CONSECUTIVE_FAILURES
  consecutive unexpected exceptions, rather than logging silently forever.
- A single intermittent failure does NOT escalate (consecutive counter resets
  on the next successful poll).
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from game import polling
from game.events import VoteNeededEvent
from game.polling import POLL_MAX_CONSECUTIVE_FAILURES, poll_game_state


async def test_poll_game_state_reraises_cancelled_error():
    """CancelledError from get_state must propagate, not be caught by except Exception."""
    client = MagicMock()
    client.get_state = AsyncMock(side_effect=asyncio.CancelledError())
    queue: asyncio.Queue = asyncio.Queue()

    with pytest.raises(asyncio.CancelledError):
        await poll_game_state(client, 0, queue)


async def test_poll_game_state_escalates_after_max_consecutive_failures():
    """After POLL_MAX_CONSECUTIVE_FAILURES consecutive exceptions, the loop re-raises."""
    client = MagicMock()
    boom = RuntimeError("boom")
    # Every call raises — should escalate on the Nth call.
    client.get_state = AsyncMock(side_effect=boom)
    queue: asyncio.Queue = asyncio.Queue()

    with pytest.raises(RuntimeError, match="boom"):
        await poll_game_state(client, 0, queue)

    # Should have been called exactly POLL_MAX_CONSECUTIVE_FAILURES times before
    # escalating (the Nth call's exception is the one re-raised).
    assert client.get_state.call_count == POLL_MAX_CONSECUTIVE_FAILURES


async def test_poll_game_state_resets_consecutive_failures_on_success():
    """A single transient failure followed by success should NOT escalate."""
    client = MagicMock()
    # One failure, then successful polls forever (until CancelledError ends it).
    successes_then_cancel = (
        [RuntimeError("transient")]
        + [{"state_type": "monster"}] * (POLL_MAX_CONSECUTIVE_FAILURES + 2)
        + [asyncio.CancelledError()]
    )
    client.get_state = AsyncMock(side_effect=successes_then_cancel)
    queue: asyncio.Queue = asyncio.Queue()

    # Must raise CancelledError, NOT RuntimeError — counter reset after success.
    with pytest.raises(asyncio.CancelledError):
        await poll_game_state(client, 0, queue)

    # A vote event should have been queued on the first successful poll.
    assert not queue.empty()
    first = queue.get_nowait()
    assert isinstance(first, VoteNeededEvent)
