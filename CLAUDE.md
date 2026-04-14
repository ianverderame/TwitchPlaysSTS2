# TwitchPlaysSTS2

A "Twitch Plays" bot for Slay the Spire 2. The streamer plays STS2 on PC and streams via OBS to Twitch. Viewers type commands in chat; the bot collects votes over a timed window and executes the winning action in-game.

## How it works

1. STS2 runs on PC with the STS2MCP mod installed, which exposes a local REST API
2. The bot polls game state from that API (~1s intervals)
3. When the game needs player input, the bot opens a vote window in Twitch chat
4. Viewers vote with `!` commands (e.g. `!1`, `!end`, `!left`)
5. After the vote window closes, the most-voted action is sent back to the game API
6. The game executes the move; chat is notified of the result

## Tech Stack

| Layer         | Tool                   |
|---------------|------------------------|
| Language      | Python                 |
| Twitch chat   | TwitchIO 3.x           |
| Game API      | STS2MCP mod (REST)     |
| Menu API      | STS2-MenuControl (REST)|
| HTTP client   | httpx (async)          |
| Config        | PyYAML + python-dotenv |
| Database      | SQLite + aiosqlite     |

## External Mods (must be installed in STS2 before running)

- **STS2MCP**: https://github.com/Gennadiyev/STS2MCP — full game state + actions via REST on `localhost:8080`
- **STS2-MenuControl**: https://github.com/L4ntern0/STS2-MenuControl — menu interactions via REST on `localhost:8081`

## Project Structure

```
TwitchPlaysSTS2/
├── .claude/           # Claude Code config and custom commands
├── bot/               # Twitch client, vote manager, command parser
├── game/              # STS2 API client, game state models, game loop
├── db/                # SQLite logging
├── config/            # settings.yaml (safe to commit)
├── .env               # secrets — never commit (see .env.example)
├── main.py            # entry point
└── requirements.txt
```

## Session Rules

- **One issue at a time.** Each session works on exactly one active GitHub Issue. Do not start, plan, or implement work outside that issue's scope.
- **No scope creep.** If related work is identified that falls outside the active issue, create a new GitHub Issue for it and stop there. Do not implement it in the current session.
- **Check `PROGRESS.md` first.** At the start of every session, read `PROGRESS.md` to identify the active issue before doing anything else.
- **No commits without explicit user request.** Never run `git commit` or `git push` unless the user explicitly asks.

## Coding Conventions

- Python 3.11+
- Async throughout (asyncio) — TwitchIO and httpx are both async
- Type hints on all function signatures
- No print statements in production code — use Python `logging`
- Secrets only via environment variables (never hardcoded)
