import asyncio
import logging

import twitchio
from twitchio import eventsub
from twitchio.ext import commands

from bot.vote_manager import VoteManager
from game.actions import build_api_body
from game.api_client import STS2Client
from game.events import GameEndedEvent, GameEvent, GameStartedEvent, MenuSelectNeededEvent, VoteNeededEvent
from game.menu_client import MenuClient
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
        menu_client: MenuClient,
    ) -> None:
        self._channel = config["twitch"]["channel"]
        self._owner_id = config["twitch"]["owner_id"]
        self._bot_token = config["twitch"]["bot_token"]
        self._bot_refresh_token = config["twitch"]["bot_refresh_token"]
        self._owner_token = config["twitch"]["owner_token"]
        self._owner_refresh_token = config["twitch"]["owner_refresh_token"]

        self._event_queue = event_queue
        self._game_client = game_client
        self._menu_client = menu_client
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

                elif isinstance(event, MenuSelectNeededEvent):
                    await self._handle_menu_select(broadcaster)

                elif isinstance(event, VoteNeededEvent):
                    # Check 1: discard if the game has already moved on since this
                    # event was queued (common during rapid floor-0 transitions).
                    pre_vote_data = await self._game_client.get_state()
                    if pre_vote_data:
                        try:
                            pre_vote_state = GameState.from_api_response(pre_vote_data)
                            if pre_vote_state.state_type != event.state.state_type:
                                logger.warning(
                                    "Discarding stale vote: queued for '%s' but game is now '%s'",
                                    event.state.state_type,
                                    pre_vote_state.state_type,
                                )
                                self._event_queue.task_done()
                                continue
                            # For combat states, also discard if it's now the enemy's turn
                            if (
                                pre_vote_state.is_combat_state()
                                and pre_vote_state.is_play_phase is False
                            ):
                                logger.warning(
                                    "Discarding stale vote: combat state '%s' but is_play_phase=False (enemy turn)",
                                    event.state.state_type,
                                )
                                self._event_queue.task_done()
                                continue
                        except ValueError:
                            pass  # Can't parse fresh state — proceed with the vote anyway

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

                    # Check 2: discard if the game moved on while the vote window
                    # was open (e.g. state changed during the vote duration).
                    if action_state.state_type != event.state.state_type:
                        logger.warning(
                            "Discarding stale vote result: queued for '%s' but game is now '%s'",
                            event.state.state_type,
                            action_state.state_type,
                        )
                        self._event_queue.task_done()
                        continue
                    if (
                        action_state.is_combat_state()
                        and action_state.is_play_phase is False
                    ):
                        logger.warning(
                            "Discarding stale vote result: combat state '%s' but is_play_phase=False (enemy turn)",
                            action_state.state_type,
                        )
                        self._event_queue.task_done()
                        continue

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

    async def _handle_menu_select(self, broadcaster: twitchio.PartialUser) -> None:
        """Handle a MenuSelectNeededEvent: navigate to character select, run vote, embark."""
        # Retry initial query — MenuControl may still be initializing when STS2MCP first reports menu
        menu_data = None
        for _ in range(5):
            menu_data = await self._menu_client.get_menu_state()
            if menu_data and menu_data.get("screen") not in (None, "UNKNOWN", "IN_GAME"):
                break
            await asyncio.sleep(1.0)
        if not menu_data:
            logger.warning("MenuControl API unreachable — skipping character select vote")
            return

        screen = menu_data.get("screen", "UNKNOWN")
        available_actions = menu_data.get("available_actions", [])

        if screen == "MAIN_MENU":
            if "open_character_select" not in available_actions:
                logger.warning(
                    "MenuControl: open_character_select unavailable; screen=%s available_actions=%s",
                    screen,
                    available_actions,
                )
                return
            result = await self._menu_client.post_menu_action("open_character_select")
            if result is None:
                logger.warning("MenuControl: open_character_select POST failed")
                return

            # Re-query with retries — open_character_select may need a moment to transition
            for _ in range(3):
                await asyncio.sleep(0.5)
                menu_data = await self._menu_client.get_menu_state()
                if menu_data and menu_data.get("screen") == "CHARACTER_SELECT":
                    screen = "CHARACTER_SELECT"
                    break
            else:
                logger.warning(
                    "MenuControl: expected CHARACTER_SELECT after open_character_select, "
                    "got screen=%s available_actions=%s — skipping",
                    menu_data.get("screen") if menu_data else None,
                    menu_data.get("available_actions") if menu_data else None,
                )
                return

        if screen != "CHARACTER_SELECT":
            logger.warning(
                "MenuControl: unexpected screen=%s — skipping character select vote",
                screen,
            )
            return

        characters = menu_data.get("characters", [])
        enabled = [c for c in characters if c.get("enabled", False)]
        if not enabled:
            logger.warning("MenuControl: no enabled characters found — skipping vote")
            return

        options = [str(i + 1) for i in range(len(enabled))]
        ascension: int | None = menu_data.get("ascension")

        def _fmt(char_id: str) -> str:
            return char_id.replace("_", " ").title()

        char_list = "  ".join(
            f"!{opt}={_fmt(enabled[int(opt) - 1]['character_id'])}" for opt in options
        )
        asc_str = f" | Ascension {ascension}" if ascension else ""
        await broadcaster.send_message(
            message=f"Choose your character{asc_str}: {char_list}",
            sender=self.bot_id,
            token_for=self.bot_id,
        )

        winner = await self.vote_manager.run_window(
            broadcaster=broadcaster,
            bot_id=self.bot_id,
            options=options,
            state_summary=f"character select{asc_str}",
        )

        winning_pos = int(winner) - 1
        winning_char_data = enabled[winning_pos]
        winning_char = _fmt(winning_char_data["character_id"])
        winning_index = winning_char_data["index"]  # absolute index in full button array

        result = await self._menu_client.post_menu_action(
            "select_character", option_index=winning_index
        )
        if result is None:
            logger.warning("MenuControl: select_character POST failed")
            return
        result = await self._menu_client.post_menu_action("embark")
        if result is None:
            logger.warning("MenuControl: embark POST failed")
            return

        asc_display = f" (Ascension {ascension})" if ascension else ""
        logger.info("Embarking as %s%s", winning_char, asc_display)
        await broadcaster.send_message(
            message=f"Starting run as {winning_char}{asc_display}!",
            sender=self.bot_id,
            token_for=self.bot_id,
        )
