import logging

from twitchio import eventsub
from twitchio.ext import commands

logger = logging.getLogger(__name__)


class ChatComponent(commands.Component):
    def __init__(self, bot: "TwitchBot") -> None:
        self.bot = bot

    @commands.command()
    async def test(self, ctx: commands.Context) -> None:
        await ctx.channel.send_message(
            sender=self.bot.bot_id,
            message=f"!test received from {ctx.author.name}",
            token_for=self.bot.bot_id,
        )


class TwitchBot(commands.Bot):
    def __init__(self, config: dict) -> None:
        self._channel = config["twitch"]["channel"]
        self._owner_id = config["twitch"]["owner_id"]
        self._bot_token = config["twitch"]["bot_token"]
        self._bot_refresh_token = config["twitch"]["bot_refresh_token"]
        self._owner_token = config["twitch"]["owner_token"]
        self._owner_refresh_token = config["twitch"]["owner_refresh_token"]

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
        await self.add_component(ChatComponent(self))

        payload = eventsub.ChatMessageSubscription(
            broadcaster_user_id=self._owner_id,
            user_id=self.bot_id,
        )
        await self.subscribe_websocket(payload=payload, as_bot=True)

    async def event_ready(self) -> None:
        logger.info("Connected to Twitch as %s", self.user)
        users = await self.fetch_users(ids=[self._owner_id])
        broadcaster = users[0]
        await broadcaster.send_message(
            message="Bot is online!",
            sender=self.bot_id,
            token_for=self.bot_id,
        )
