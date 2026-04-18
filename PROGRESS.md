# Progress

## Current Milestone
`PoC`

## Recently Completed
- #59 — All 7 hardcoded timings/retries promoted to settings.yaml; threaded through loader, clients, polling, options, bot
- #62 — 165-test suite: state/actions/options/labels/polling/api_client/vote_manager; runs via `python -m pytest`, no live deps
- #58 — Refactor _event_runner (379 lines) into 9 focused methods; _event_runner now 45 lines; fixed polling bug for draw-on-play cards
- #56 — !help command (any time, not vote-gated) + README (setup, .env, mods, commands cheat sheet); live-tested

## Active Issue
None

## Up Next
1. #60 — Chat-send DRY + broadcaster caching
2. #53 — Full belt + potion reward: discard-to-claim flow
3. #63 — End-game screen navigation (victory, defeat, unlocks)
4. #7 — Database Logging
5. #61 — Bundled minor code-hygiene cleanups

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
