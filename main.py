import asyncio
import logging
import os
import sys

from bot.client import TwitchBot
from config.loader import load_config
from game.api_client import STS2Client
from game.events import GameEvent
from game.menu_client import MenuClient
from game.polling import poll_game_state

os.makedirs("logs", exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("logs/bot.log", mode="w", encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)


async def main() -> None:
    try:
        config = load_config()
    except RuntimeError as e:
        logger.error("Startup failed: %s", e)
        sys.exit(1)

    dry_run = bool(config["game"].get("dry_run", False))
    if dry_run:
        logger.warning("DRY RUN MODE — actions will be logged but NOT sent to the game API")

    http_timeout = config["api"].get("http_timeout_seconds", 5.0)
    game_client = STS2Client(config["api"]["sts2mcp_base_url"], dry_run=dry_run, http_timeout=http_timeout)
    menu_client = MenuClient(config["api"]["sts2_menu_base_url"], http_timeout=http_timeout)

    state = await game_client.get_state()
    if state is not None:
        logger.info("STS2MCP API reachable at %s", config["api"]["sts2mcp_base_url"])
    else:
        logger.warning("STS2MCP API not reachable at startup — polling will retry")

    menu_state = await menu_client.get_menu_state()
    if menu_state is not None:
        logger.info("MenuControl API reachable at %s", config["api"]["sts2_menu_base_url"])
    else:
        logger.warning("MenuControl API not reachable at startup — character select will retry when needed")

    # Quieten verbose third-party loggers
    logging.getLogger("twitchio").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)

    interval = config["game"]["poll_interval_seconds"]
    recheck_attempts = config["game"].get("mid_turn_recheck_attempts", 5)
    recheck_interval = config["game"].get("mid_turn_recheck_interval_seconds", 0.5)
    event_queue: asyncio.Queue[GameEvent] = asyncio.Queue()

    async with TwitchBot(config, event_queue, game_client, menu_client) as bot:
        poll_task = asyncio.create_task(
            poll_game_state(game_client, interval, event_queue,
                            recheck_attempts=recheck_attempts, recheck_interval=recheck_interval)
        )
        try:
            await bot.start()
        finally:
            poll_task.cancel()
            await game_client.close()
            await menu_client.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Shutting down. Goodbye!")
