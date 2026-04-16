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
from game.labels import labels_for_state, preamble_for_state, target_labels_for_enemies
from game.options import options_for_state
from game.state import GameState

logger = logging.getLogger(__name__)

_WIKI_BASE = "https://slay-the-spire.fandom.com/wiki/"


def _wiki_url(card_name: str) -> str:
    return _WIKI_BASE + card_name.replace(" ", "_")


class ChatComponent(commands.Component):
    def __init__(self, bot: "TwitchBot", vote_manager: VoteManager, game_client: STS2Client) -> None:
        self.bot = bot
        self.vote_manager = vote_manager
        self._game_client = game_client

    @commands.Component.listener()
    async def event_message(self, payload: twitchio.ChatMessage) -> None:
        text = payload.text.strip()
        if not text.startswith("!") or not self.vote_manager.is_open:
            return
        choice = text[1:].split()[0].lower()
        if choice:
            self.vote_manager.record_vote(payload.chatter.id, choice)

    @commands.command()
    async def lookup(self, ctx: commands.Context) -> None:
        """Look up any card by name. Shows cost + description + wiki link."""
        parts = ctx.message.text.strip().split(None, 1)
        if len(parts) < 2 or not parts[1].strip():
            await ctx.channel.send_message(
                sender=self.bot.bot_id,
                message="Usage: !lookup <card name>",
                token_for=self.bot.bot_id,
            )
            return

        query = parts[1].strip()
        card_data: dict | None = None

        # Search all card piles so the command works regardless of game state
        raw_data = await self._game_client.get_state()
        if raw_data:
            player = raw_data.get("player") or {}
            all_cards: list[dict] = (
                list(player.get("hand") or [])
                + list(player.get("draw_pile") or [])
                + list(player.get("discard_pile") or [])
                + list(player.get("exhaust_pile") or [])
            )
            q_lower = query.lower()
            card_data = next((c for c in all_cards if q_lower in c.get("name", "").lower()), None)

        if card_data:
            name: str = card_data.get("name", query)
            cost = card_data.get("cost")
            description: str = card_data.get("description", "")
            url = _wiki_url(name)

            msg_parts = [name]
            if cost is not None:
                msg_parts.append(f"{cost} energy")
            if description:
                msg_parts.append(description)
            msg_parts.append(url)
            message = " | ".join(msg_parts)

            if len(message) > 500:
                # Drop description if it pushes past Twitch's 500-char limit
                msg_parts = [name]
                if cost is not None:
                    msg_parts.append(f"{cost} energy")
                msg_parts.append(url)
                message = " | ".join(msg_parts)
        else:
            # Game not running or card not in any pile — provide wiki link for the name as typed
            message = f"{query} | {_wiki_url(query)}"

        await ctx.channel.send_message(
            sender=self.bot.bot_id,
            message=message,
            token_for=self.bot.bot_id,
        )

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
        self._target_vote_duration: float = config["vote"]["target_duration_seconds"]
        self._ready = asyncio.Event()  # set in event_ready; gates _event_runner

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
        await self.add_component(ChatComponent(self, self.vote_manager, self._game_client))

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
        self._ready.set()

    async def event_command_error(self, payload: commands.CommandErrorPayload) -> None:
        # !1, !end, !left, etc. are not registered commands — silence the noise.
        if isinstance(payload.exception, commands.CommandNotFound):
            return
        await super().event_command_error(payload)

    async def _event_runner(self) -> None:
        """Background task: dequeue GameEvents and handle each in chat."""
        logger.info("Event runner started")
        await self._ready.wait()  # ensure event_ready has fired before sending to chat
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

                elif isinstance(event, VoteNeededEvent) and event.state.state_type == "rewards":
                    await self._handle_rewards()

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
                            # Auto-proceed: single is_proceed option — no vote needed
                            if (
                                pre_vote_state.state_type == "event"
                                and len(pre_vote_state.event_options) == 1
                                and pre_vote_state.event_options[0].get("is_proceed")
                            ):
                                proceed_index = pre_vote_state.event_options[0]["index"]
                                body = {"action": "choose_event_option", "index": proceed_index}
                                result = await self._game_client.post_action(body)
                                logger.info("Auto-proceeding event (single proceed option) → %s", result)
                                self._event_queue.task_done()
                                continue
                            # Auto-proceed: rest_site after choosing an option (e.g. after Resting)
                            if (
                                pre_vote_state.state_type == "rest_site"
                                and pre_vote_state.rest_site_can_proceed
                                and not any(
                                    o.get("is_enabled", True)
                                    for o in pre_vote_state.rest_site_options
                                    if not o.get("is_proceed")
                                )
                            ):
                                result = await self._game_client.post_action({"action": "proceed"})
                                logger.info("Auto-proceeding rest_site → %s", result)
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
                        labels=labels_for_state(event.state) or None,
                        preamble=preamble_for_state(event.state),
                    )

                    # AnyEnemy cards require a follow-up target vote when multiple enemies
                    # are alive. resolved_target is passed through to build_api_body.
                    resolved_target: str | None = None
                    if winner.isdigit() and event.state.is_combat_state():
                        card_index = int(winner) - 1
                        target_type = event.state.hand_card_target_types.get(card_index, "")
                        if target_type == "AnyEnemy":
                            resolved_target = await self._run_target_vote(
                                broadcaster, winner, event.state
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
                        body = build_api_body(action_state, winner, target_entity_id=resolved_target)
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

                    # hand_select: auto-confirm after card selection — no second vote needed
                    if action_state.state_type == "hand_select" and body.get("action") == "combat_select_card":
                        confirm_result = await self._game_client.post_action({"action": "combat_confirm_selection"})
                        logger.info("Auto-confirmed hand_select → %s", confirm_result)

                    # card_select: re-queue if more selections needed, auto-confirm when ready
                    elif action_state.state_type == "card_select" and body.get("action") == "select_card":
                        fresh_data = await self._game_client.get_state()
                        if fresh_data:
                            try:
                                post_select_state = GameState.from_api_response(fresh_data)
                                if post_select_state.state_type == "card_select":
                                    if post_select_state.card_select_can_confirm:
                                        confirm_result = await self._game_client.post_action({"action": "confirm_selection"})
                                        logger.info("Auto-confirmed card_select → %s", confirm_result)
                                    else:
                                        logger.info("card_select: more selections needed — re-queuing vote")
                                        self._event_queue.put_nowait(VoteNeededEvent(post_select_state))
                            except ValueError:
                                pass

                self._event_queue.task_done()

            except asyncio.CancelledError:
                logger.info("Event runner cancelled")
                raise
            except Exception:
                logger.error("Unexpected error in event runner", exc_info=True)

    async def _run_target_vote(
        self,
        broadcaster: twitchio.PartialUser,
        card_winner: str,
        event_state: GameState,
    ) -> str | None:
        """Run a follow-up target-selection vote for an AnyEnemy card.

        Returns the chosen entity_id, or None if the enemy list is empty
        (combat ended — the stale-vote guard downstream will handle it).
        Auto-targets when only one enemy is alive (no vote needed).
        """
        card_index = int(card_winner) - 1
        card_name = event_state.hand_card_names.get(card_index, f"Card {card_winner}")
        enemies = event_state.enemies

        if len(enemies) == 1:
            logger.info("AnyEnemy card '%s' — single enemy, auto-targeting %s", card_name, enemies[0]["name"])
            return enemies[0]["entity_id"]

        if not enemies:
            return None

        target_options = [str(i + 1) for i in range(len(enemies))]
        target_labels = target_labels_for_enemies(enemies)

        target_winner = await self.vote_manager.run_window(
            broadcaster=broadcaster,
            bot_id=self.bot_id,
            options=target_options,
            state_summary=f"target select for {card_name}",
            labels=target_labels,
            preamble=f"{card_name} \u2014 choose target:",
            duration=self._target_vote_duration,
        )

        # Guard: re-check enemy list after vote (theoretically impossible to change in SP)
        guard_data = await self._game_client.get_state()
        current_enemies = enemies
        if guard_data:
            try:
                guard_state = GameState.from_api_response(guard_data)
                if guard_state.enemies:
                    current_enemies = guard_state.enemies
            except ValueError:
                pass

        if len(current_enemies) == 1:
            logger.info("Enemy list changed to 1 after target vote — auto-targeting %s", current_enemies[0]["name"])
            return current_enemies[0]["entity_id"]

        if current_enemies:
            target_idx = int(target_winner) - 1
            if target_idx >= len(current_enemies):
                logger.warning(
                    "Target index %d out of range for %d enemies — defaulting to first",
                    target_idx, len(current_enemies),
                )
                target_idx = 0
            return current_enemies[target_idx]["entity_id"]

        return None  # combat ended; stale-vote guard handles it

    async def _handle_rewards(self) -> None:
        """Auto-claim all non-card rewards, open card rewards for a chat vote, then proceed.

        Claims one item per loop iteration and re-fetches state each time since
        claiming shifts reward indices. Card/special_card/card_removal rewards are
        opened last and return early — the resulting selection state is handled by
        the polling loop as a separate VoteNeededEvent.
        """
        # Types that open a selection screen for chat to vote on
        VOTE_TYPES = {"card", "special_card", "card_removal"}

        while True:
            fresh_data = await self._game_client.get_state()
            if not fresh_data:
                logger.warning("Rewards: could not fetch fresh state — skipping")
                return

            try:
                state = GameState.from_api_response(fresh_data)
            except ValueError:
                logger.warning("Rewards: malformed state response — skipping")
                return

            if state.state_type != "rewards":
                logger.info("Rewards: state moved to '%s' — done", state.state_type)
                return

            # Prefer non-vote items first; keep a card/selection item as fallback
            auto_item = None
            vote_item = None
            for item in state.rewards_items:
                item_type = item.get("type")
                if item_type in VOTE_TYPES:
                    if vote_item is None:
                        vote_item = item
                else:
                    auto_item = item
                    break  # claim one at a time, re-fetch after

            if auto_item:
                result = await self._game_client.post_action(
                    {"action": "claim_reward", "index": auto_item["index"]}
                )
                logger.info("Auto-claimed %s reward → %s", auto_item.get("type"), result)
                continue  # re-fetch and process remaining items

            if vote_item:
                result = await self._game_client.post_action(
                    {"action": "claim_reward", "index": vote_item["index"]}
                )
                logger.info(
                    "Auto-opened %s reward for vote → %s", vote_item.get("type"), result
                )
                return  # polling loop handles the resulting selection state

            # Nothing left to claim — proceed to map
            result = await self._game_client.post_action({"action": "proceed"})
            logger.info("Auto-proceeded from rewards → %s", result)
            return

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
