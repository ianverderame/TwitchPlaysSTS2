# TwitchPlaysSTS2

A "Twitch Plays" bot for Slay the Spire 2. The streamer plays on PC while viewers vote on every decision via chat commands.

## How it works

1. **STS2** runs on the streamer's PC with two mods installed (see below)
2. The bot polls game state every ~1 second via the STS2MCP REST API
3. When the game needs input, a **vote window** opens in chat
4. Viewers type `!N` (or other commands) to cast votes
5. After the window closes, the winning action is sent to the game
6. Chat is notified of the result

## Requirements

- Python 3.11+
- A Twitch bot account + OAuth tokens (bot + broadcaster)
- **[STS2MCP](https://github.com/Gennadiyev/STS2MCP)** mod installed in STS2 (REST API on `localhost:15526`)
- **[STS2-MenuControl](https://github.com/L4ntern0/STS2-MenuControl)** mod installed in STS2 (REST API on `localhost:8081`)

## Setup

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure secrets

Copy `.env.example` to `.env` and fill in your values:

```bash
cp .env.example .env
```

Required variables:

| Variable | Description |
|---|---|
| `TWITCH_CLIENT_ID` | Twitch app client ID |
| `TWITCH_CLIENT_SECRET` | Twitch app client secret |
| `TWITCH_BOT_TOKEN` | Bot user access token |
| `TWITCH_BOT_REFRESH_TOKEN` | Bot refresh token |
| `TWITCH_BOT_ID` | Numeric Twitch user ID of the bot account |
| `TWITCH_OWNER_ID` | Numeric Twitch user ID of the channel owner |
| `TWITCH_OWNER_TOKEN` | Owner user access token (scope: `channel:bot`) |
| `TWITCH_OWNER_REFRESH_TOKEN` | Owner refresh token |
| `TWITCH_CHANNEL` | Channel username (lowercase) |
| `STS2MCP_BASE_URL` | Default: `http://localhost:15526` |
| `STS2_MENU_BASE_URL` | Default: `http://localhost:8081` |

Bot token required scopes: `user:read:chat user:write:chat user:bot moderator:manage:announcements`

### 3. Configure settings

Edit `config/settings.yaml` to adjust vote durations, poll interval, etc. The defaults are reasonable for most setups.

### 4. Install STS2 mods

Install both mods in your STS2 mod folder and launch the game before starting the bot.

## Running

```bash
python3 main.py
```

The bot connects to Twitch, starts polling the game, and announces in chat when ready. Press `Ctrl+C` to stop.

**Dry-run mode** (votes run but no actions sent to the game):

```yaml
# config/settings.yaml
game:
  dry_run: true
```

## Viewer commands

Type `!help` in chat for a quick reference. Full list:

| Command | When | Description |
|---|---|---|
| `!help` | Any time | Show this command list in chat |
| `!N` | Vote open | Vote for option N (e.g. `!1`, `!3`) |
| `!end` | Combat vote | Vote to end your turn |
| `!pN` | Vote open | Vote to use potion in slot N (e.g. `!p1`) |
| `!dN` | Vote open | Vote to discard potion in slot N (e.g. `!d2`) |
| `?map` | Any time | Preview upcoming map nodes |
| `?p` / `?potions` | Any time | Show current potion belt |
| `?N` | Any time | Show info for card in hand slot N (e.g. `?2`) |
| `((card name))` | Any time | Look up a card by name with wiki link |

## Logs

Logs are written to `logs/bot.log` (truncated each run) and the terminal. Check this file after a session for debugging.
