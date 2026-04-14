import asyncio
import logging
import sys

from bot.client import TwitchBot
from config.loader import load_config
from game.api_client import STS2Client
from game.polling import poll_game_state

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


async def main() -> None:
    try:
        config = load_config()
    except RuntimeError as e:
        logger.error("Startup failed: %s", e)
        sys.exit(1)

    game_client = STS2Client(config["api"]["sts2mcp_base_url"])

    state = await game_client.get_state()
    if state is not None:
        logger.info("STS2MCP API reachable at %s", config["api"]["sts2mcp_base_url"])
    else:
        logger.warning("STS2MCP API not reachable at startup — polling will retry")

    # Quieten verbose third-party loggers
    logging.getLogger("twitchio").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)

    interval = config["game"]["poll_interval_seconds"]

    async with TwitchBot(config) as bot:
        poll_task = asyncio.create_task(poll_game_state(game_client, interval))
        try:
            await bot.start()
        finally:
            poll_task.cancel()
            await game_client.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Shutting down. Goodbye!")
