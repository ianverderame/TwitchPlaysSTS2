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
        labels: dict[str, str] | None = None,
        preamble: str = "Vote open!",
        duration: float | None = None,
        silent: bool = False,
    ) -> str:
        """Open a vote window, collect votes, tally, announce winner.

        Always returns a winning choice string. If no votes were cast or votes
        are tied, a winner is chosen randomly and chat is notified.

        When ``silent=True`` the opening options message is suppressed. Use this
        when the caller has already announced the vote (e.g. smith upgrade posts
        a card list before calling run_window).
        """
        self._votes = {}
        self._options = frozenset(options)
        self._open = True
        logger.info("Vote window opened for state: %s", state_summary)

        effective_duration = duration if duration is not None else self._duration

        if not silent:
            parts = [
                f"!{o}={labels[o]}" if (labels and o in labels) else f"!{o}"
                for o in options
            ]
            options_str = "  ".join(parts)
            await broadcaster.send_message(
                message=f"{preamble} {options_str}  ({effective_duration:.0f}s)",
                sender=bot_id,
                token_for=bot_id,
            )

        await asyncio.sleep(effective_duration)

        self._open = False
        logger.info("Vote window closed. %d vote(s) cast.", len(self._votes))

        winner, was_random, was_tie = self._tally(options)

        winner_label = labels.get(winner) if labels else None
        winner_str = f"!{winner}={winner_label}" if winner_label else f"!{winner}"

        if was_random:
            await broadcaster.send_message(
                message=f"Vote closed — no votes, random pick: {winner_str}",
                sender=bot_id,
                token_for=bot_id,
            )
        elif was_tie:
            await broadcaster.send_message(
                message=f"Vote closed! Tie broken randomly: {winner_str}",
                sender=bot_id,
                token_for=bot_id,
            )
        else:
            count = sum(1 for v in self._votes.values() if v == winner)
            await broadcaster.send_message(
                message=f"Vote closed! Winner: {winner_str} ({count} vote(s)).",
                sender=bot_id,
                token_for=bot_id,
            )

        return winner

    def _tally(self, options: list[str]) -> tuple[str, bool, bool]:
        """Return (winner, was_random, was_tie).

        was_random: True when no votes were cast (winner chosen from random pool).
        was_tie: True when multiple options share the top vote count (winner chosen randomly among tied).

        Random fallback and tie-breaking only pick from numeric options (e.g. "1", "2") so
        terminal actions like "end", "skip", "cancel" are never chosen without an explicit vote.
        Falls back to the full options list only if there are no numeric options at all.
        """
        numeric_options = [o for o in options if o.isdigit()]
        random_pool = numeric_options if numeric_options else options

        if not self._votes:
            winner = random.choice(random_pool)
            logger.info("No votes cast — random fallback: %s", winner)
            return winner, True, False

        counts = Counter(self._votes.values())
        max_count = counts.most_common(1)[0][1]
        tied = [choice for choice, count in counts.items() if count == max_count]

        if len(tied) > 1:
            # Break ties using only numeric options that were among the tied choices
            numeric_tied = [c for c in tied if c.isdigit()]
            winner = random.choice(numeric_tied if numeric_tied else tied)
            logger.info("Tie between %s — random winner: %s", tied, winner)
            return winner, False, True

        return tied[0], False, False
