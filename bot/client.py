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
from game.options import options_for_state, parse_potion_winner, potion_display_name
from game.state import GameState, IDLE_STATES

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
            elif arg.lower() in ("p", "potions"):
                await self._handle_potions_list()
            return

        # !help — always available, not gated on vote state
        if text.lower() == "!help":
            await self._handle_help()
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

    async def _handle_help(self) -> None:
        """Respond to !help with a concise viewer command reference."""
        await self._send_chat(
            "Commands: !N=vote | !pN=use potion N | !dN=discard potion N"
            " | ?map=map preview | ?p/?potions=potion belt | ?N=card in slot N | ((name))=card lookup"
        )

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

    async def _handle_potions_list(self) -> None:
        """Respond to ?p / ?potions with a one-line summary of held potions."""
        raw_data = await self._game_client.get_state()
        if not raw_data:
            return

        if raw_data.get("state_type") in IDLE_STATES:
            await self._send_chat("No run in progress.")
            return

        potions: list[dict] = (raw_data.get("player") or {}).get("potions") or []
        if not potions:
            await self._send_chat("No potions in belt.")
            return

        entries = [(p.get("slot", 0) + 1, potion_display_name(p), p) for p in potions]
        full_parts = [
            f"{slot}: {name} | target={p.get('target_type') or 'None'} combat={p.get('can_use_in_combat')} | {p.get('description') or ''}"
            for slot, name, p in entries
        ]
        message = " | ".join(full_parts)
        if len(message) > 490:
            # Drop target_type + description if the full listing overflows Twitch's 500-char limit
            message = " | ".join(f"{slot}: {name}" for slot, name, _ in entries)
        await self._send_chat(message)

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
        self._auto_proceed_delay: float = config["game"].get("auto_proceed_delay_seconds", 3.0)

        game_cfg = config["game"]
        menu_cfg = config.get("menu", {})
        self._rest_site_poll_attempts: int = game_cfg.get("rest_site_poll_attempts", 10)
        self._rest_site_poll_interval: float = game_cfg.get("rest_site_poll_interval_seconds", 1.0)
        self._action_retry_count: int = game_cfg.get("action_retry_count", 1)
        self._max_belt_size: int = config.get("potions", {}).get("max_belt_size", 3)
        self._menu_initial_retry_attempts: int = menu_cfg.get("initial_query_retry_attempts", 5)
        self._menu_initial_retry_interval: float = menu_cfg.get("initial_query_retry_interval_seconds", 1.0)
        self._menu_transition_retry_attempts: int = menu_cfg.get("transition_retry_attempts", 3)
        self._menu_transition_retry_interval: float = menu_cfg.get("transition_retry_interval_seconds", 0.5)

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
        message = "[DRY RUN] Bot is online — votes run but actions are NOT sent to the game." if self._game_client.dry_run else "Bot is online!"
        await broadcaster.send_message(
            message=message,
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
                    await self._handle_card_remove_event(event, broadcaster)
                elif isinstance(event, VoteNeededEvent) and event.state.card_select_screen_type == "upgrade":
                    await self._handle_smith_upgrade_event(event, broadcaster)
                elif isinstance(event, VoteNeededEvent):
                    await self._handle_vote_needed(event, broadcaster)

            except asyncio.CancelledError:
                logger.info("Event runner cancelled")
                raise
            except Exception:
                logger.error("Unexpected error in event runner", exc_info=True)
            finally:
                self._event_queue.task_done()

    async def _fetch_parsed_state(self) -> GameState | None:
        """Fetch and parse current game state; return None on any failure."""
        data = await self._game_client.get_state()
        if not data:
            return None
        try:
            return GameState.from_api_response(data)
        except ValueError:
            return None

    def _is_stale_state(self, current: GameState, expected_type: str, context: str = "vote") -> bool:
        """Return True (and warn) if current state no longer matches expected_type.

        Covers both state_type mismatch and combat enemy-turn checks, eliminating
        the duplicate pre-vote / post-vote guard blocks that previously existed.
        """
        if current.state_type != expected_type:
            logger.warning(
                "Discarding stale %s: queued for '%s' but game is now '%s'",
                context,
                expected_type,
                current.state_type,
            )
            return True
        if current.is_combat_state() and current.is_play_phase is False:
            logger.warning(
                "Discarding stale %s: combat state '%s' but is_play_phase=False (enemy turn)",
                context,
                expected_type,
            )
            return True
        return False

    async def _try_auto_proceed(self, state: GameState, broadcaster: twitchio.PartialUser) -> bool:
        """Try the 5 single-option auto-proceed shortcuts; return True if handled."""
        # Single unlocked event option — no meaningful vote to hold
        if (
            state.state_type == "event"
            and len(state.event_options) == 1
            and not state.event_options[0].get("is_locked")
        ):
            option = state.event_options[0]
            label = option.get("title") or "Proceed"
            await broadcaster.send_message(
                message=f"One option available: {label}",
                sender=self.bot_id,
                token_for=self.bot_id,
            )
            await asyncio.sleep(self._auto_proceed_delay)
            result = await self._game_client.post_action({"action": "choose_event_option", "index": option["index"]})
            logger.info("Auto-proceeding event (single option '%s') → %s", label, result)
            return True

        # rest_site when can_proceed=True and no options remain
        if (
            state.state_type == "rest_site"
            and state.rest_site_can_proceed
            and not any(
                o.get("is_enabled", True)
                for o in state.rest_site_options
                if not o.get("is_proceed")
            )
        ):
            result = await self._game_client.post_action({"action": "proceed"})
            logger.info("Auto-proceeding rest_site → %s", result)
            return True

        # Single map node — no vote needed, short delay for readability
        if state.state_type == "map" and len(state.map_next_options) == 1:
            await broadcaster.send_message(
                message="One path available — proceeding",
                sender=self.bot_id,
                token_for=self.bot_id,
            )
            await asyncio.sleep(self._auto_proceed_delay)
            result = await self._game_client.post_action({"action": "choose_map_node", "index": 0})
            logger.info("Auto-selected single map node → %s", result)
            return True

        # Treasure always contains exactly one relic — no vote needed
        if state.state_type == "treasure" and state.treasure_relics:
            relic = state.treasure_relics[0]
            relic_name = relic.get("name") or "a relic"
            await asyncio.sleep(self._auto_proceed_delay)
            result = await self._game_client.post_action({"action": "claim_treasure_relic", "index": relic["index"]})
            logger.info("Auto-claimed treasure relic '%s' → %s", relic_name, result)
            await broadcaster.send_message(
                message=f"Claimed {relic_name}!",
                sender=self.bot_id,
                token_for=self.bot_id,
            )
            proceed_result = await self._game_client.post_action({"action": "proceed"})
            logger.info("Auto-proceeded from treasure → %s", proceed_result)
            return True

        # Shop/fake_merchant with nothing purchasable — no vote needed
        if state.state_type in ("shop", "fake_merchant") and options_for_state(state, max_belt_size=self._max_belt_size) == ["end"]:
            result = await self._game_client.post_action({"action": "proceed"})
            logger.info("Auto-left shop — nothing purchasable → %s", result)
            return True

        return False

    async def _handle_card_remove_event(self, event: VoteNeededEvent, broadcaster: twitchio.PartialUser) -> None:
        """Handle a card_select 'select' (shop card removal) event with fresh state."""
        remove_data = await self._game_client.get_state()
        if not remove_data:
            logger.warning("Card remove: could not fetch fresh state — discarding")
            return
        try:
            remove_state = GameState.from_api_response(remove_data)
        except ValueError:
            logger.warning("Card remove: could not parse fresh state — discarding")
            return
        if remove_state.card_select_screen_type == "select":
            await self._handle_card_remove(broadcaster, remove_state)
        else:
            logger.warning(
                "Card remove: state moved to '%s' before vote started — discarding",
                remove_state.state_type,
            )

    async def _handle_smith_upgrade_event(self, event: VoteNeededEvent, broadcaster: twitchio.PartialUser) -> None:
        """Handle a card_select 'upgrade' (smith upgrade) event with fresh state."""
        smith_data = await self._game_client.get_state()
        if not smith_data:
            logger.warning("Smith upgrade: could not fetch fresh state — discarding")
            return
        try:
            smith_state = GameState.from_api_response(smith_data)
        except ValueError:
            logger.warning("Smith upgrade: could not parse fresh state — discarding")
            return
        if smith_state.card_select_screen_type == "upgrade":
            await self._handle_smith_upgrade(broadcaster, smith_state)
        else:
            logger.warning(
                "Smith upgrade: state moved to '%s' before vote started — discarding",
                smith_state.state_type,
            )

    async def _handle_vote_needed(self, event: VoteNeededEvent, broadcaster: twitchio.PartialUser) -> None:
        """Handle a general VoteNeededEvent: stale-check, auto-proceed, vote, execute."""
        pre_vote_state = await self._fetch_parsed_state()

        if pre_vote_state is not None:
            if self._is_stale_state(pre_vote_state, event.state.state_type, "vote"):
                return
            if await self._try_auto_proceed(pre_vote_state, broadcaster):
                return

        vote_state = pre_vote_state if pre_vote_state is not None else event.state
        winner = await self.vote_manager.run_window(
            broadcaster=broadcaster,
            bot_id=self.bot_id,
            options=options_for_state(vote_state, max_belt_size=self._max_belt_size),
            state_summary=vote_state.summary(),
            labels=labels_for_state(vote_state) or None,
            preamble=preamble_for_state(vote_state),
        )

        resolved_target = await self._resolve_any_enemy_target(event.state, winner, broadcaster)

        # Re-fetch so action uses fresh data (e.g. enemies list may be empty on first poll)
        action_state = (await self._fetch_parsed_state()) or event.state
        if self._is_stale_state(action_state, event.state.state_type, "vote result"):
            return

        try:
            body = build_api_body(action_state, winner, target_entity_id=resolved_target)
        except ValueError:
            logger.error(
                "No API mapping for state=%s winner=%s — skipping action",
                event.state.state_type,
                winner,
            )
            return

        result = await self._post_action_with_retry(body, winner)
        await self._handle_post_action(action_state, body, result)

    async def _resolve_any_enemy_target(
        self,
        state: GameState,
        winner: str,
        broadcaster: twitchio.PartialUser,
    ) -> str | None:
        """Return entity_id for AnyEnemy cards or potions; None if not applicable."""
        if winner.isdigit() and state.is_combat_state():
            card_index = int(winner) - 1
            if state.hand_card_target_types.get(card_index, "") == "AnyEnemy":
                card_name = state.hand_card_names.get(card_index, f"Card {winner}")
                return await self._run_target_vote(broadcaster, card_name, state.enemies)
        else:
            potion_action = parse_potion_winner(winner)
            if potion_action is not None and potion_action[0] == "use":
                slot = potion_action[1]
                potion = next((p for p in state.player_potions if p.get("slot") == slot), None)
                if potion and potion.get("target_type") == "AnyEnemy":
                    return await self._run_target_vote(broadcaster, potion_display_name(potion), state.enemies)
        return None

    async def _post_action_with_retry(self, body: dict, winner: str) -> dict | None:
        """POST an action to the game API; retry up to action_retry_count times on failure."""
        result = await self._game_client.post_action(body)
        if result is not None:
            logger.info("Action executed: %s → %s", winner, result)
            return result
        for attempt in range(1, self._action_retry_count + 1):
            logger.warning("Action POST failed, retrying (attempt %d/%d)...", attempt, self._action_retry_count)
            result = await self._game_client.post_action(body)
            if result is not None:
                logger.info("Action executed (retry %d): %s → %s", attempt, winner, result)
                return result
        logger.error("Action POST failed after %d retries for body=%s — system may be stuck", self._action_retry_count, body)
        return None

    async def _handle_post_action(
        self,
        action_state: GameState,
        body: dict,
        result: dict | None,
    ) -> None:
        """Dispatch post-action follow-up logic based on state type and action."""
        action = body.get("action", "")

        # shop/fake_merchant: re-queue vote after purchase or potion use
        if action_state.state_type in ("shop", "fake_merchant") and action in ("shop_purchase", "use_potion") and result is not None:
            post_state = await self._fetch_parsed_state()
            if post_state and post_state.state_type == action_state.state_type:
                logger.info("Shop purchase complete — re-queuing vote")
                self._event_queue.put_nowait(VoteNeededEvent(post_state))

        # Any state: re-queue after discard so the vote reflects the updated belt
        if action == "discard_potion" and result is not None:
            post_state = await self._fetch_parsed_state()
            if post_state and post_state.requires_player_input():
                self._event_queue.put_nowait(VoteNeededEvent(post_state))

        # rest_site: after choosing an option, poll until can_proceed=True then decide
        if action_state.state_type == "rest_site" and action == "choose_rest_option":
            for _ in range(self._rest_site_poll_attempts):
                await asyncio.sleep(self._rest_site_poll_interval)
                post_rest_state = await self._fetch_parsed_state()
                if post_rest_state is None:
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
                logger.warning("rest_site: can_proceed never became True after %d polls — may be stuck", self._rest_site_poll_attempts)

        # hand_select: confirm when can_confirm=True, re-queue if more selections needed
        elif action_state.state_type == "hand_select" and action == "combat_select_card":
            hs_data = await self._game_client.get_state()
            if not hs_data:
                confirm_result = await self._game_client.post_action({"action": "combat_confirm_selection"})
                logger.info("Auto-confirmed hand_select (no fresh state) → %s", confirm_result)
            else:
                try:
                    hs_state = GameState.from_api_response(hs_data)
                except ValueError:
                    confirm_result = await self._game_client.post_action({"action": "combat_confirm_selection"})
                    logger.info("Auto-confirmed hand_select (state parse failed) → %s", confirm_result)
                else:
                    if hs_state.state_type == "hand_select":
                        if hs_state.hand_select_can_confirm:
                            confirm_result = await self._game_client.post_action({"action": "combat_confirm_selection"})
                            logger.info("Auto-confirmed hand_select → %s", confirm_result)
                        else:
                            logger.info("hand_select: more selections needed — re-queuing vote")
                            self._event_queue.put_nowait(VoteNeededEvent(hs_state))

        # card_select: re-queue if more selections needed, auto-confirm when ready
        elif action_state.state_type == "card_select" and action == "select_card":
            cs_data = await self._game_client.get_state()
            if cs_data:
                try:
                    cs_state = GameState.from_api_response(cs_data)
                except ValueError:
                    pass
                else:
                    if cs_state.state_type == "card_select":
                        if cs_state.card_select_can_confirm:
                            confirm_result = await self._game_client.post_action({"action": "confirm_selection"})
                            logger.info("Auto-confirmed card_select → %s", confirm_result)
                        else:
                            logger.info("card_select: more selections needed — re-queuing vote")
                            self._event_queue.put_nowait(VoteNeededEvent(cs_state))

        # Dry-run: game state never changes so the poller never fires a new event.
        # Re-queue manually so testing can continue without restarting the bot.
        if self._game_client.dry_run:
            dry_run_state = await self._fetch_parsed_state()
            if dry_run_state and dry_run_state.requires_player_input():
                self._event_queue.put_nowait(VoteNeededEvent(dry_run_state))

    async def _run_target_vote(
        self,
        broadcaster: twitchio.PartialUser,
        source_name: str,
        enemies: list[dict],
    ) -> str | None:
        """Run a follow-up target-selection vote for an AnyEnemy action.

        Returns the chosen entity_id, or None if the enemy list is empty
        (combat ended — the stale-vote guard downstream will handle it).
        Auto-targets when only one enemy is alive (no vote needed).
        Used for both AnyEnemy cards and AnyEnemy potions.
        """
        if len(enemies) == 1:
            logger.info("AnyEnemy '%s' — single enemy, auto-targeting %s", source_name, enemies[0]["name"])
            return enemies[0]["entity_id"]

        if not enemies:
            return None

        target_options = [str(i + 1) for i in range(len(enemies))]
        target_labels = target_labels_for_enemies(enemies)

        target_winner = await self.vote_manager.run_window(
            broadcaster=broadcaster,
            bot_id=self.bot_id,
            options=target_options,
            state_summary=f"target select for {source_name}",
            labels=target_labels,
            preamble=f"{source_name} \u2014 choose target:",
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
        """Auto-claim gold/relic/potion rewards, open card rewards for a chat vote, then proceed."""
        _VOTE_TYPES = {"card", "special_card", "card_removal"}

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

            auto_item = next((i for i in state.rewards_items if i.get("type") not in _VOTE_TYPES), None)
            vote_item = next((i for i in state.rewards_items if i.get("type") in _VOTE_TYPES), None)

            if auto_item:
                await asyncio.sleep(self._auto_proceed_delay)
                result = await self._game_client.post_action({"action": "claim_reward", "index": auto_item["index"]})
                logger.info("Auto-claimed %s reward → %s", auto_item.get("type"), result)
                continue

            if vote_item:
                await asyncio.sleep(self._auto_proceed_delay)
                result = await self._game_client.post_action({"action": "claim_reward", "index": vote_item["index"]})
                logger.info("Auto-opened %s reward for vote → %s", vote_item.get("type"), result)
                return

            await asyncio.sleep(self._auto_proceed_delay)
            result = await self._game_client.post_action({"action": "proceed"})
            logger.info("Auto-proceeded from rewards → %s", result)
            return

    async def _handle_menu_select(self, broadcaster: twitchio.PartialUser) -> None:
        """Handle a MenuSelectNeededEvent: navigate to character select, run vote, embark."""
        # Retry initial query — MenuControl may still be initializing when STS2MCP first reports menu
        menu_data = None
        for _ in range(self._menu_initial_retry_attempts):
            menu_data = await self._menu_client.get_menu_state()
            if menu_data and menu_data.get("screen") not in (None, "UNKNOWN", "IN_GAME"):
                break
            await asyncio.sleep(self._menu_initial_retry_interval)
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
            for _ in range(self._menu_transition_retry_attempts):
                await asyncio.sleep(self._menu_transition_retry_interval)
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
