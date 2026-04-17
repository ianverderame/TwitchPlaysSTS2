import asyncio
import logging
import re

import twitchio
from twitchio import eventsub
from twitchio.ext import commands

from bot.vote_manager import VoteManager
from game.actions import build_api_body
from game.api_client import STS2Client
from game.events import GameEndedEvent, GameEvent, GameStartedEvent, MenuSelectNeededEvent, VoteNeededEvent
from game.menu_client import MenuClient
from game.labels import MAP_ROOM_LABELS, labels_for_state, preamble_for_state, target_labels_for_enemies
from game.options import options_for_state
from game.state import GameState

logger = logging.getLogger(__name__)

_WIKI_BASE = "https://slaythespire.wiki.gg/wiki/Slay_the_Spire_2:"


def _chunk_card_list(
    entries: list[str], max_len: int = 490, separator: str = " | "
) -> list[list[str]]:
    """Split a list of card-entry strings into chunks that fit within max_len characters.

    Each chunk will be joined with ``separator`` when sent as a chat message.
    Entries are never split mid-word; each chunk contains complete entries.
    """
    chunks: list[list[str]] = []
    current: list[str] = []
    current_len = 0
    sep_len = len(separator)
    for entry in entries:
        # Account for the separator that will be added between entries
        entry_len = len(entry) + (sep_len if current else 0)
        if current and current_len + entry_len > max_len:
            chunks.append(current)
            current = [entry]
            current_len = len(entry)
        else:
            current.append(entry)
            current_len += entry_len
    if current:
        chunks.append(current)
    return chunks


def _wiki_url(card_name: str) -> str:
    return _WIKI_BASE + card_name.title().replace(" ", "_")


def _format_card_message(card_data: dict) -> str:
    """Format a card dict into a chat-ready string: name | cost | description | wiki url."""
    name: str = card_data.get("name", "Unknown")
    cost = card_data.get("cost")
    description: str = card_data.get("description", "")
    url = _wiki_url(name)

    parts = [name]
    if cost is not None:
        parts.append(f"{cost} energy")
    if description:
        parts.append(description)
    parts.append(url)
    message = " | ".join(parts)

    if len(message) > 500:
        # Drop description if it pushes past Twitch's 500-char limit
        parts = [name]
        if cost is not None:
            parts.append(f"{cost} energy")
        parts.append(url)
        message = " | ".join(parts)

    return message



class ChatComponent(commands.Component):
    def __init__(self, bot: "TwitchBot", vote_manager: VoteManager, game_client: STS2Client) -> None:
        self.bot = bot
        self.vote_manager = vote_manager
        self._game_client = game_client

    async def _send_chat(self, message: str) -> None:
        """Send a message to the broadcaster's channel."""
        users = await self.bot.fetch_users(ids=[self.bot._owner_id])
        if users:
            await users[0].send_message(
                message=message,
                sender=self.bot.bot_id,
                token_for=self.bot.bot_id,
            )

    @commands.Component.listener()
    async def event_message(self, payload: twitchio.ChatMessage) -> None:
        if payload.chatter.id == self.bot.bot_id:
            return
        text = payload.text.strip()

        # ? commands — informational lookups (never affect votes)
        if text.startswith("?"):
            arg = text[1:].strip().split()[0] if text[1:].strip() else ""
            if arg.isdigit():
                await self._handle_slot_lookup(arg)
            elif arg.lower() == "map":
                await self._handle_map_preview()
            return

        # ((name)) — card lookup, one response per match in the message
        matches = re.findall(r'\(\((.+?)\)\)', text)
        if matches:
            for query in matches:
                query = query.strip()
                if query:
                    await self._handle_name_lookup(query)
            return

        if not text.startswith("!") or not self.vote_manager.is_open:
            return
        choice = text[1:].split()[0].lower()
        if choice:
            self.vote_manager.record_vote(payload.chatter.id, choice)

    async def _handle_slot_lookup(self, arg: str) -> None:
        """Respond to ?N with card info for vote slot N from the current hand."""
        slot = int(arg) - 1  # 1-indexed vote slot → 0-indexed hand index
        raw_data = await self._game_client.get_state()
        if not raw_data:
            return  # game not running — silently ignore

        hand: list[dict] = (raw_data.get("player") or {}).get("hand") or []
        card_data = next((c for c in hand if c.get("index") == slot), None)

        if card_data:
            await self._send_chat(_format_card_message(card_data))
        else:
            await self._send_chat(f"No card at slot {arg}.")

    async def _handle_name_lookup(self, query: str) -> None:
        """Respond to ((name)) with card info + wiki.gg link.

        If the card is in the current piles, includes cost and description from
        the game API. Always falls back to a wiki link using the queried name.
        """
        resolved_name = query.title()
        card_data: dict | None = None

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
            card_data = next(
                (c for c in all_cards if c.get("name", "").lower() in q_lower), None
            )
            if card_data:
                resolved_name = card_data["name"]

        if card_data:
            await self._send_chat(_format_card_message(card_data))
        else:
            await self._send_chat(f"{resolved_name} | {_wiki_url(resolved_name)}")

    async def _handle_map_preview(self) -> None:
        """Respond to ?map with a text preview of upcoming map nodes."""
        raw_data = await self._game_client.get_state()
        if not raw_data:
            return

        map_data = raw_data.get("map") or {}
        if not map_data:
            state_type = raw_data.get("state_type", "")
            if state_type == "menu":
                await self._send_chat("No run in progress.")
            else:
                await self._send_chat("?map command is only available on the map screen.")
            return

        nodes: list[dict] = map_data.get("nodes") or []
        current_pos: dict = map_data.get("current_position") or {}
        current_row: int = current_pos.get("row", -1)

        run = raw_data.get("run") or {}
        act = run.get("act")
        floor_num = run.get("floor")

        rows_by_row: dict[int, list[str]] = {}
        for node in nodes:
            node_row = node.get("row")
            if node_row is None or node_row <= current_row:
                continue
            label = MAP_ROOM_LABELS.get((node.get("type") or "").upper(), node.get("type") or "?")
            if node_row not in rows_by_row:
                rows_by_row[node_row] = []
            if label not in rows_by_row[node_row]:
                rows_by_row[node_row].append(label)

        if not rows_by_row:
            await self._send_chat("No upcoming nodes.")
            return

        sorted_rows = sorted(rows_by_row.keys())[:8]
        header = f"[Act {act} F{floor_num}] " if act and floor_num else "[Map] "
        parts = [f"F{r}: {'/'.join(rows_by_row[r])}" for r in sorted_rows]

        sep = " → "
        message = header + sep.join(parts)
        while len(message) > 490 and parts:
            parts.pop()
            message = header + sep.join(parts)

        await self._send_chat(message)

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
        self._smith_vote_duration: float = config["vote"].get("smith_vote_duration_seconds", 30.0)
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
                logger.debug("Event runner: waiting for event (queue size=%d)", self._event_queue.qsize())
                event: GameEvent = await self._event_queue.get()
                logger.info("Event runner: processing %s", type(event).__name__)

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

                elif isinstance(event, VoteNeededEvent) and event.state.card_select_screen_type == "select":
                    # Shop card removal — grouped deck list, same deduplication as smith upgrade.
                    remove_data = await self._game_client.get_state()
                    if remove_data:
                        try:
                            remove_state = GameState.from_api_response(remove_data)
                            if remove_state.card_select_screen_type == "select":
                                await self._handle_card_remove(broadcaster, remove_state)
                            else:
                                logger.warning(
                                    "Card remove: state moved to '%s' before vote started — discarding",
                                    remove_state.state_type,
                                )
                        except ValueError:
                            logger.warning("Card remove: could not parse fresh state — discarding")
                    else:
                        logger.warning("Card remove: could not fetch fresh state — discarding")

                elif isinstance(event, VoteNeededEvent) and event.state.card_select_screen_type == "upgrade":
                    # Smith upgrade — special handling: full deck, deduplication, 30s vote.
                    # Re-fetch to get the latest card list (avoids acting on stale card data).
                    smith_data = await self._game_client.get_state()
                    if smith_data:
                        try:
                            smith_state = GameState.from_api_response(smith_data)
                            if smith_state.card_select_screen_type == "upgrade":
                                await self._handle_smith_upgrade(broadcaster, smith_state)
                            else:
                                logger.warning(
                                    "Smith upgrade: state moved to '%s' before vote started — discarding",
                                    smith_state.state_type,
                                )
                        except ValueError:
                            logger.warning("Smith upgrade: could not parse fresh state — discarding")
                    else:
                        logger.warning("Smith upgrade: could not fetch fresh state — discarding")

                elif isinstance(event, VoteNeededEvent):
                    # Check 1: discard if the game has already moved on since this
                    # event was queued (common during rapid floor-0 transitions).
                    pre_vote_state: GameState | None = None
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
                            # Auto-proceed: rest_site when can_proceed=True and no options remain
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
                            # Auto-select: single map node — no vote needed, short delay for readability
                            if (
                                pre_vote_state.state_type == "map"
                                and len(pre_vote_state.map_next_options) == 1
                            ):
                                await asyncio.sleep(5.0)
                                result = await self._game_client.post_action(
                                    {"action": "choose_map_node", "index": 0}
                                )
                                logger.info("Auto-selected single map node → %s", result)
                                self._event_queue.task_done()
                                continue
                            # Auto-claim: treasure always contains exactly one relic — no vote needed
                            if pre_vote_state.state_type == "treasure" and pre_vote_state.treasure_relics:
                                relic = pre_vote_state.treasure_relics[0]
                                relic_name = relic.get("name") or "a relic"
                                relic_index = relic["index"]
                                await asyncio.sleep(3.0)
                                result = await self._game_client.post_action(
                                    {"action": "claim_treasure_relic", "index": relic_index}
                                )
                                logger.info("Auto-claimed treasure relic '%s' → %s", relic_name, result)
                                await broadcaster.send_message(
                                    message=f"Claimed {relic_name}!",
                                    sender=self.bot_id,
                                    token_for=self.bot_id,
                                )
                                proceed_result = await self._game_client.post_action({"action": "proceed"})
                                logger.info("Auto-proceeded from treasure → %s", proceed_result)
                                self._event_queue.task_done()
                                continue
                        except ValueError:
                            pass  # Can't parse fresh state — proceed with the vote anyway

                    # Auto-leave: shop with nothing purchasable — no vote needed
                    if pre_vote_data and pre_vote_state and pre_vote_state.state_type in ("shop", "fake_merchant"):
                        if options_for_state(pre_vote_state) == ["end"]:
                            result = await self._game_client.post_action({"action": "proceed"})
                            logger.info("Auto-left shop — nothing purchasable → %s", result)
                            self._event_queue.task_done()
                            continue

                    vote_state = pre_vote_state if pre_vote_state is not None else event.state
                    options = options_for_state(vote_state)
                    winner = await self.vote_manager.run_window(
                        broadcaster=broadcaster,
                        bot_id=self.bot_id,
                        options=options,
                        state_summary=vote_state.summary(),
                        labels=labels_for_state(vote_state) or None,
                        preamble=preamble_for_state(vote_state),
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

                    # shop/fake_merchant: re-queue vote after successful purchase — player may want to buy more
                    if action_state.state_type in ("shop", "fake_merchant") and body.get("action") == "shop_purchase" and result is not None:
                        post_shop_data = await self._game_client.get_state()
                        if post_shop_data:
                            try:
                                post_shop_state = GameState.from_api_response(post_shop_data)
                                if post_shop_state.state_type == action_state.state_type:
                                    logger.info("Shop purchase complete — re-queuing vote")
                                    self._event_queue.put_nowait(VoteNeededEvent(post_shop_state))
                            except ValueError:
                                pass

                    # rest_site: after choosing an option, poll until can_proceed=True then decide
                    if action_state.state_type == "rest_site" and body.get("action") == "choose_rest_option":
                        for _ in range(10):
                            await asyncio.sleep(1.0)
                            post_rest_data = await self._game_client.get_state()
                            if not post_rest_data:
                                break
                            try:
                                post_rest_state = GameState.from_api_response(post_rest_data)
                            except ValueError:
                                break
                            if post_rest_state.state_type != "rest_site":
                                logger.info("rest_site: state moved to '%s' — done", post_rest_state.state_type)
                                break
                            if post_rest_state.rest_site_can_proceed:
                                enabled = [
                                    o for o in post_rest_state.rest_site_options
                                    if o.get("is_enabled", True) and not o.get("is_proceed")
                                ]
                                if enabled:
                                    # Miniature Tent: more options still available — re-queue vote
                                    logger.info("rest_site: can_proceed but options remain — re-queuing vote")
                                    self._event_queue.put_nowait(VoteNeededEvent(post_rest_state))
                                else:
                                    proceed_result = await self._game_client.post_action({"action": "proceed"})
                                    logger.info("Auto-proceeded after rest_site option → %s", proceed_result)
                                break
                        else:
                            logger.warning("rest_site: can_proceed never became True after 10s — may be stuck")

                    # hand_select: confirm when can_confirm=True, re-queue if more selections needed
                    elif action_state.state_type == "hand_select" and body.get("action") == "combat_select_card":
                        post_hs_data = await self._game_client.get_state()
                        if post_hs_data:
                            try:
                                post_hs_state = GameState.from_api_response(post_hs_data)
                                if post_hs_state.state_type == "hand_select":
                                    if post_hs_state.hand_select_can_confirm:
                                        confirm_result = await self._game_client.post_action({"action": "combat_confirm_selection"})
                                        logger.info("Auto-confirmed hand_select → %s", confirm_result)
                                    else:
                                        logger.info("hand_select: more selections needed — re-queuing vote")
                                        self._event_queue.put_nowait(VoteNeededEvent(post_hs_state))
                            except ValueError:
                                confirm_result = await self._game_client.post_action({"action": "combat_confirm_selection"})
                                logger.info("Auto-confirmed hand_select (state parse failed) → %s", confirm_result)
                        else:
                            confirm_result = await self._game_client.post_action({"action": "combat_confirm_selection"})
                            logger.info("Auto-confirmed hand_select (no fresh state) → %s", confirm_result)

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

    @staticmethod
    def _dedup_cards(cards: list[dict]) -> list[tuple[str, int]]:
        """Return deduplicated (display_label, api_index) pairs from a card list.

        Cards identical in all fields except 'index' are merged; the first card's
        index is used. Merged entries are labelled 'Name (xN)'.
        """
        def key(card: dict) -> tuple:
            return tuple(sorted((k, str(v)) for k, v in card.items() if k != "index"))

        counts: dict[tuple, int] = {}
        for card in cards:
            k = key(card)
            counts[k] = counts.get(k, 0) + 1

        seen: set[tuple] = set()
        groups: list[tuple[str, int]] = []
        for card in cards:
            k = key(card)
            if k not in seen:
                seen.add(k)
                name = card.get("name") or f"Card {card.get('index', '?')}"
                label = f"{name} (x{counts[k]})" if counts[k] > 1 else name
                groups.append((label, card["index"]))
        return groups

    async def _handle_deck_select_vote(
        self,
        broadcaster: twitchio.PartialUser,
        state: GameState,
        *,
        header: str,
        color: str,
        state_summary: str,
        duration: float,
    ) -> None:
        """Run a deduplicated card-selection vote for any card_select overlay.

        Covers: announce header → numbered card list → silent vote → select_card
        → confirm_selection. Used by smith upgrade, shop card removal, and any
        future card_select screen_type that follows the same pattern.
        """
        cards = state.card_select_cards
        if not cards:
            logger.warning("Deck select (%s): card_select.cards is empty — skipping", state_summary)
            return

        groups = self._dedup_cards(cards)
        options = [str(i + 1) for i in range(len(groups))]
        option_to_api_index = {str(i + 1): groups[i][1] for i in range(len(groups))}
        labels = {str(i + 1): groups[i][0] for i in range(len(groups))}

        try:
            await broadcaster.send_announcement(moderator=self.bot_id, message=header, color=color)
        except twitchio.HTTPException as exc:
            logger.warning(
                "Deck select (%s): send_announcement failed (%s) — falling back to chat message. "
                "Grant the bot 'moderator:manage:announcements' for highlighted announcements.",
                state_summary, exc,
            )
            await broadcaster.send_message(message=header, sender=self.bot_id, token_for=self.bot_id)

        entries = [f"{i + 1}. {groups[i][0]}" for i in range(len(groups))]
        for chunk in _chunk_card_list(entries, separator=" | "):
            await broadcaster.send_message(
                message=" | ".join(chunk), sender=self.bot_id, token_for=self.bot_id
            )

        winner = await self.vote_manager.run_window(
            broadcaster=broadcaster,
            bot_id=self.bot_id,
            options=options,
            state_summary=state_summary,
            labels=labels,
            duration=duration,
            silent=True,
        )

        api_index = option_to_api_index[winner]
        winner_label = groups[int(winner) - 1][0]
        result = await self._game_client.post_action({"action": "select_card", "index": api_index})
        logger.info("Deck select (%s): '%s' (api_index=%d) → %s", state_summary, winner_label, api_index, result)

        post_data = await self._game_client.get_state()
        if post_data:
            try:
                post_state = GameState.from_api_response(post_data)
            except ValueError:
                post_state = None
            if post_state is not None and post_state.state_type == "card_select":
                if post_state.card_select_can_confirm:
                    confirm_result = await self._game_client.post_action({"action": "confirm_selection"})
                    logger.info("Deck select (%s): confirmed → %s", state_summary, confirm_result)
                else:
                    logger.warning(
                        "Deck select (%s): still in card_select but can_confirm=False — "
                        "selection may not be committed",
                        state_summary,
                    )

    async def _handle_card_remove(
        self,
        broadcaster: twitchio.PartialUser,
        state: GameState,
    ) -> None:
        duration = self._smith_vote_duration
        await self._handle_deck_select_vote(
            broadcaster, state,
            header=f"REMOVE A CARD ({duration:.0f}s) — Pick a card to remove! Type !N for your choice:",
            color="red",
            state_summary="card remove",
            duration=duration,
        )

    async def _handle_smith_upgrade(
        self,
        broadcaster: twitchio.PartialUser,
        state: GameState,
    ) -> None:
        duration = self._smith_vote_duration
        await self._handle_deck_select_vote(
            broadcaster, state,
            header=f"SMITH UPGRADE ({duration:.0f}s) — Pick a card to upgrade! Type !N for your choice:",
            color="green",
            state_summary="smith upgrade",
            duration=duration,
        )

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
