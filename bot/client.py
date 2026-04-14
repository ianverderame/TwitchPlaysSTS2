import asyncio
import logging

import twitchio
from twitchio import eventsub
from twitchio.ext import commands

from bot.vote_manager import VoteManager
from game.actions import build_api_body
from game.api_client import STS2Client
from game.events import GameEndedEvent, GameEvent, GameStartedEvent, VoteNeededEvent
from game.options import options_for_state
from game.state import GameState

logger = logging.getLogger(__name__)


class ChatComponent(commands.Component):
    def __init__(self, bot: "TwitchBot", vote_manager: VoteManager) -> None:
        self.bot = bot
        self.vote_manager = vote_manager

    @commands.Component.listener()
    async def event_message(self, payload: twitchio.ChatMessage) -> None:
        text = payload.text.strip()
        if not text.startswith("!") or not self.vote_manager.is_open:
            return
        choice = text[1:].split()[0].lower()
        if choice:
            self.vote_manager.record_vote(payload.chatter.id, choice)

    @commands.command()
    async def test(self, ctx: commands.Context) -> None:
        await ctx.channel.send_message(
            sender=self.bot.bot_id,
            message=f"!test received from {ctx.author.name}",
            token_for=self.bot.bot_id,
        )


class TwitchBot(commands.Bot):
    def __init__(
        self,
        config: dict,
        event_queue: asyncio.Queue[GameEvent],
        game_client: STS2Client,
    ) -> None:
        self._channel = config["twitch"]["channel"]
        self._owner_id = config["twitch"]["owner_id"]
        self._bot_token = config["twitch"]["bot_token"]
        self._bot_refresh_token = config["twitch"]["bot_refresh_token"]
        self._owner_token = config["twitch"]["owner_token"]
        self._owner_refresh_token = config["twitch"]["owner_refresh_token"]

        self._event_queue = event_queue
        self._game_client = game_client
        self.vote_manager = VoteManager(config["vote"]["duration_seconds"])

        super().__init__(
            client_id=config["twitch"]["client_id"],
            client_secret=config["twitch"]["client_secret"],
            bot_id=config["twitch"]["bot_id"],
            owner_id=self._owner_id,
            prefix="!",
        )

    async def load_tokens(self, path: str | None = None) -> None:
        # Register the bot's user access token. The broadcaster's channel:bot grant
        # is a persistent Twitch-side authorization and does not need to be registered here.
        await self.add_token(self._bot_token, self._bot_refresh_token)

    async def setup_hook(self) -> None:
        await self.add_component(ChatComponent(self, self.vote_manager))

        payload = eventsub.ChatMessageSubscription(
            broadcaster_user_id=self._owner_id,
            user_id=self.bot_id,
        )
        await self.subscribe_websocket(payload=payload, as_bot=True)

        asyncio.create_task(self._event_runner(), name="event-runner")

    async def event_ready(self) -> None:
        logger.info("Connected to Twitch as %s", self.user)
        users = await self.fetch_users(ids=[self._owner_id])
        broadcaster = users[0]
        await broadcaster.send_message(
            message="Bot is online!",
            sender=self.bot_id,
            token_for=self.bot_id,
        )

    async def event_command_error(self, payload: commands.CommandErrorPayload) -> None:
        # !1, !end, !left, etc. are not registered commands — silence the noise.
        if isinstance(payload.exception, commands.CommandNotFound):
            return
        await super().event_command_error(payload)

    async def _event_runner(self) -> None:
        """Background task: dequeue GameEvents and handle each in chat."""
        logger.info("Event runner started")
        users = await self.fetch_users(ids=[self._owner_id])
        broadcaster: twitchio.PartialUser = users[0]

        while True:
            try:
                event: GameEvent = await self._event_queue.get()

                if isinstance(event, GameStartedEvent):
                    logger.info("Game started: %s", event.state.summary())
                    await broadcaster.send_message(
                        message="A new run has started! Type !<choice> to vote when prompted.",
                        sender=self.bot_id,
                        token_for=self.bot_id,
                    )

                elif isinstance(event, GameEndedEvent):
                    logger.info("Game ended: %s", event.state.summary())
                    await broadcaster.send_message(
                        message="Run over! Thanks for playing.",
                        sender=self.bot_id,
                        token_for=self.bot_id,
                    )

                elif isinstance(event, VoteNeededEvent):
                    options = options_for_state(event.state)
                    winner = await self.vote_manager.run_window(
                        broadcaster=broadcaster,
                        bot_id=self.bot_id,
                        options=options,
                        state_summary=event.state.summary(),
                    )

                    # Re-fetch state so action uses fresh data (e.g. enemies list
                    # may be empty on the first monster poll that queued the vote).
                    fresh_data = await self._game_client.get_state()
                    if fresh_data:
                        try:
                            action_state = GameState.from_api_response(fresh_data)
                        except ValueError:
                            action_state = event.state
                    else:
                        action_state = event.state

                    try:
                        body = build_api_body(action_state, winner)
                    except ValueError:
                        logger.error(
                            "No API mapping for state=%s winner=%s — skipping action",
                            event.state.state_type,
                            winner,
                        )
                        self._event_queue.task_done()
                        continue

                    result = await self._game_client.post_action(body)
                    if result is None:
                        logger.warning("Action POST failed, retrying once...")
                        result = await self._game_client.post_action(body)
                        if result is None:
                            logger.error(
                                "Action POST failed twice for body=%s — system may be stuck",
                                body,
                            )
                        else:
                            logger.info("Action executed (retry): %s → %s", winner, result)
                    else:
                        logger.info("Action executed: %s → %s", winner, result)

                self._event_queue.task_done()

            except asyncio.CancelledError:
                logger.info("Event runner cancelled")
                raise
            except Exception:
                logger.error("Unexpected error in event runner", exc_info=True)
