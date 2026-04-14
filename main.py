import asyncio
import logging
import sys

from bot.client import TwitchBot
from config.loader import load_config
from game.api_client import STS2Client

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


async def terminal_recheck_loop(game_client: STS2Client) -> None:
    """Read terminal input. Type 'recheck' to ping the STS2MCP API again."""
    loop = asyncio.get_event_loop()
    while True:
        line = await loop.run_in_executor(None, sys.stdin.readline)
        if line.strip().lower() == "recheck":
            await game_client.ping()


async def main() -> None:
    try:
        config = load_config()
    except RuntimeError as e:
        logger.error("Startup failed: %s", e)
        sys.exit(1)

    game_client = STS2Client(config["api"]["sts2mcp_base_url"])
    await game_client.ping()

    # Quieten TwitchIO's verbose loggers
    logging.getLogger("twitchio").setLevel(logging.WARNING)

    async with TwitchBot(config) as bot:
        recheck_task = asyncio.create_task(terminal_recheck_loop(game_client))
        try:
            await bot.start()
        finally:
            recheck_task.cancel()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Shutting down. Goodbye!")
