# Progress

## Current Milestone
`PoC`

## Recently Completed
- Backlog cleanup + senior code review — consolidated #12/#13 into #14, merged #40 into #29, expanded #36 scope; opened #58 (refactor _event_runner), #59 (timings → settings.yaml), #60 (chat-send DRY), #61 (minor cleanups)
- #56 — !help command (any time, not vote-gated) + README (setup, .env, mods, commands cheat sheet); live-tested
- #51 — Potions: use/discard voting (!pN/!dN), belt filter in shop, AnyEnemy target vote, ?potions/?p command, dry-run mode, file logging, auto_proceed_delay config; live-tested
- #38 (partial) — hand_select multi-select (can_confirm); treasure auto-claim + 3s pause; shop gold preamble, auto-leave, Remove Card grouped vote; rest site auto-proceed retry loop; Ancient relic vote (event state); single map node auto-select (5s); all 8 map node types confirmed
- #31 — ?map command: text preview of upcoming map nodes (up to 8 floors); `?` info command convention; self-message guard; live-tested

## Active Issue
None

## Up Next
1. #58 — Refactor _event_runner into focused handlers
2. #59 — Move hardcoded timings/retries to settings.yaml
3. #60 — Chat-send DRY + broadcaster caching
4. #53 — Full belt + potion reward: discard-to-claim flow
5. #7 — Database Logging
6. #61 — Bundled minor code-hygiene cleanups

## Key Decisions
- Bot and game run on same PC (localhost API)
- All API URLs required via .env — no hardcoded defaults in committed files
- Fail loud on missing config at startup
- Logging at INFO level to terminal + `logs/bot.log` (truncated each run, gitignored)
- No automated tests for PoC
- GitHub Issues for all task tracking; Claude can create/label/prioritize autonomously
- `PROGRESS.md` stays capped at ~20-30 lines; full history lives in GitHub Issues
- STS2MCP API on `localhost:15526`; enemy `entity_id` lives at `battle.enemies[i].entity_id`
- `game/actions.py` is the translation layer: (state_type, vote_option) → API request body
- Vote options use actual 1-indexed hand positions (matching in-game card numbers); `can_play` field determines what's offered
