import asyncio
import logging
import random
from collections import Counter

import twitchio

logger = logging.getLogger(__name__)


class VoteManager:
    """Manages a single timed vote window in Twitch chat.

    One window runs at a time. `record_vote` is a no-op when no window is open
    or when the choice is not in the current options set.
    """

    def __init__(self, duration: float) -> None:
        self._duration = duration
        self._open: bool = False
        self._votes: dict[str, str] = {}        # user_id → choice
        self._options: frozenset[str] = frozenset()

    @property
    def is_open(self) -> bool:
        return self._open

    def record_vote(self, user_id: str, choice: str) -> None:
        """Record or overwrite a vote. No-op if window is closed or choice is invalid."""
        if not self._open:
            return
        if choice not in self._options:
            return
        prev = self._votes.get(user_id)
        self._votes[user_id] = choice
        if prev and prev != choice:
            logger.debug("User %s changed vote: %s → %s", user_id, prev, choice)
        else:
            logger.debug("User %s voted: %s", user_id, choice)

    async def run_window(
        self,
        broadcaster: twitchio.PartialUser,
        bot_id: str,
        options: list[str],
        state_summary: str,
    ) -> str:
        """Open a vote window, collect votes, tally, announce winner.

        Always returns a winning choice string. If no votes were cast or votes
        are tied, a winner is chosen randomly and chat is notified.
        """
        self._votes = {}
        self._options = frozenset(options)
        self._open = True
        logger.info("Vote window opened for state: %s", state_summary)

        options_str = " | ".join(f"!{o}" for o in options)
        await broadcaster.send_message(
            message=f"Vote open! Type: {options_str}  ({self._duration:.0f}s)",
            sender=bot_id,
            token_for=bot_id,
        )

        await asyncio.sleep(self._duration)

        self._open = False
        logger.info("Vote window closed. %d vote(s) cast.", len(self._votes))

        winner, was_random, was_tie = self._tally(options)

        if was_random:
            await broadcaster.send_message(
                message=f"Vote closed — no votes, random pick: !{winner}",
                sender=bot_id,
                token_for=bot_id,
            )
        elif was_tie:
            await broadcaster.send_message(
                message=f"Vote closed! Tie broken randomly: !{winner}",
                sender=bot_id,
                token_for=bot_id,
            )
        else:
            count = sum(1 for v in self._votes.values() if v == winner)
            await broadcaster.send_message(
                message=f"Vote closed! Winner: !{winner} ({count} vote(s)).",
                sender=bot_id,
                token_for=bot_id,
            )

        return winner

    def _tally(self, options: list[str]) -> tuple[str, bool, bool]:
        """Return (winner, was_random, was_tie).

        was_random: True when no votes were cast (winner chosen from full options list).
        was_tie: True when multiple options share the top vote count (winner chosen randomly among them).
        """
        if not self._votes:
            winner = random.choice(options)
            logger.info("No votes cast — random fallback: %s", winner)
            return winner, True, False

        counts = Counter(self._votes.values())
        max_count = counts.most_common(1)[0][1]
        tied = [choice for choice, count in counts.items() if count == max_count]

        if len(tied) > 1:
            winner = random.choice(tied)
            logger.info("Tie between %s — random winner: %s", tied, winner)
            return winner, False, True

        return tied[0], False, False
