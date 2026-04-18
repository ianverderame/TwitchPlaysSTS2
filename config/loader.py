import logging
import os
from pathlib import Path

import yaml
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

REQUIRED_ENV_VARS = [
    "TWITCH_CLIENT_ID",
    "TWITCH_CLIENT_SECRET",
    "TWITCH_BOT_TOKEN",
    "TWITCH_BOT_REFRESH_TOKEN",
    "TWITCH_BOT_ID",
    "TWITCH_OWNER_ID",
    "TWITCH_OWNER_TOKEN",
    "TWITCH_OWNER_REFRESH_TOKEN",
    "TWITCH_CHANNEL",
    "STS2MCP_BASE_URL",
    "STS2_MENU_BASE_URL",
]


def load_config() -> dict:
    """Load environment variables and settings.yaml. Raises on missing required values."""
    env_path = Path(__file__).parent.parent / ".env"
    load_dotenv(dotenv_path=env_path)

    missing = [key for key in REQUIRED_ENV_VARS if not os.getenv(key)]
    if missing:
        raise RuntimeError(f"Missing required environment variables: {', '.join(missing)}")

    settings_path = Path(__file__).parent / "settings.yaml"
    with open(settings_path) as f:
        settings = yaml.safe_load(f)

    return {
        "twitch": {
            "client_id": os.environ["TWITCH_CLIENT_ID"],
            "client_secret": os.environ["TWITCH_CLIENT_SECRET"],
            "bot_token": os.environ["TWITCH_BOT_TOKEN"],
            "bot_refresh_token": os.environ["TWITCH_BOT_REFRESH_TOKEN"],
            "owner_token": os.environ["TWITCH_OWNER_TOKEN"],
            "owner_refresh_token": os.environ["TWITCH_OWNER_REFRESH_TOKEN"],
            "bot_id": os.environ["TWITCH_BOT_ID"],
            "owner_id": os.environ["TWITCH_OWNER_ID"],
            "channel": os.environ["TWITCH_CHANNEL"],
        },
        "api": {
            "sts2mcp_base_url": os.environ["STS2MCP_BASE_URL"],
            "sts2_menu_base_url": os.environ["STS2_MENU_BASE_URL"],
            **settings.get("api", {}),
        },
        "vote": settings.get("vote", {}),
        "game": settings.get("game", {}),
        "menu": settings.get("menu", {}),
        "potions": settings.get("potions", {}),
    }
