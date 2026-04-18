# Progress

## Current Milestone
`PoC`

## Recently Completed
- #60 — DRY chat-send: `_chat()` helper, `self.broadcaster` cached once, all send sites unified, `ChatComponent` no longer fetches users or touches private attrs; live-tested
- #69 — Polling fix: draw-card effects (e.g. Soul) now always trigger re-vote via `asyncio.Event` signal from action POST + `hand_size != previous` condition
- #59 — All 7 hardcoded timings/retries promoted to settings.yaml; threaded through loader, clients, polling, options, bot
- #62 — 165-test suite: state/actions/options/labels/polling/api_client/vote_manager; runs via `python -m pytest`, no live deps

## Active Issue
None

## Up Next
1. #53 — Full belt + potion reward: discard-to-claim flow
2. #63 — End-game screen navigation (victory, defeat, unlocks)
3. #7 — Database Logging
4. #61 — Bundled minor code-hygiene cleanups
5. #68 — Streaming setup & run logistics: OBS config, STS2 mod wiring, launch checklist

## Key Decisions
- Bot and game run on same PC (localhost API)
- All API URLs required via .env — no hardcoded defaults in committed files
- Fail loud on missing config at startup
- Logging at INFO level to terminal + `logs/bot.log` (truncated each run, gitignored)
- Test suite: `python -m pytest` from project root; 165 tests, no live deps; `bot/client.py` not tested (twitchio mocking complexity)
- GitHub Issues for all task tracking; Claude can create/label/prioritize autonomously
- `PROGRESS.md` stays capped at ~20-30 lines; full history lives in GitHub Issues
- STS2MCP API on `localhost:15526`; enemy `entity_id` lives at `battle.enemies[i].entity_id`
- `game/actions.py` is the translation layer: (state_type, vote_option) → API request body
- Vote options use actual 1-indexed hand positions (matching in-game card numbers); `can_play` field determines what's offered
