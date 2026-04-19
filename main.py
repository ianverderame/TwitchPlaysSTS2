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

    log_cfg = config.get("logging", {})
    logging.getLogger().setLevel(log_cfg.get("level", "INFO"))

    dry_run = bool(config["game"].get("dry_run", False))
    if dry_run:
        logger.warning("DRY RUN MODE — actions will be logged but NOT sent to the game API")

    api_cfg = config["api"]
    http_timeout = api_cfg.get("http_timeout_seconds", 5.0)
    http_retry_attempts = api_cfg.get("http_retry_attempts", 3)
    http_retry_backoff = api_cfg.get("http_retry_backoff_seconds", 0.5)
    game_client = STS2Client(
        api_cfg["sts2mcp_base_url"],
        dry_run=dry_run,
        http_timeout=http_timeout,
        http_retry_attempts=http_retry_attempts,
        http_retry_backoff_seconds=http_retry_backoff,
    )
    menu_client = MenuClient(
        api_cfg["sts2_menu_base_url"],
        http_timeout=http_timeout,
        http_retry_attempts=http_retry_attempts,
        http_retry_backoff_seconds=http_retry_backoff,
    )

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
    logging.getLogger("twitchio").setLevel(log_cfg.get("twitchio_level", "WARNING"))
    logging.getLogger("httpx").setLevel(log_cfg.get("httpx_level", "WARNING"))

    interval = config["game"]["poll_interval_seconds"]
    recheck_attempts = config["game"].get("mid_turn_recheck_attempts", 5)
    recheck_interval = config["game"].get("mid_turn_recheck_interval_seconds", 0.5)
    event_queue: asyncio.Queue[GameEvent] = asyncio.Queue()
    action_signal: asyncio.Event = asyncio.Event()

    async with TwitchBot(config, event_queue, game_client, menu_client, action_signal) as bot:
        poll_task = asyncio.create_task(
            poll_game_state(game_client, interval, event_queue,
                            recheck_attempts=recheck_attempts, recheck_interval=recheck_interval,
                            action_signal=action_signal)
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
