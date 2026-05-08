# Progress

## Current Milestone
`PoC`

## Recently Completed
- #88 — UX polish: run-start welcome at character-select (voting intro + command reference, fires once per run); per-state-entry announcements for combat/boss/shop/treasure/relic/rest/event; act-transition lines; suppressed on mid-state re-queues; 234 tests
- #86 — Vote stream-sync rework: chat prompt for first-detection votes now sleeps `stream_latency_seconds` before announcing, so the prompt arrives in sync with what stream-watchers see (chat is real-time; video is CDN-buffered). Sleep + stale-check centralized at `_event_runner` dispatcher (`_check_vote_dispatch`); sub-votes (target select, belt-full discard) bypass naturally. Replaced 5 scattered sleep sites (incl. 2 chat-leak bugs at smith and character-select where chat fired before the sleep). 207 tests
- #84 — max_potion_slots: `player_max_potion_slots` parsed from STS2MCP API into `GameState`; `is_potion_belt_full()` helper on state; proactive belt-full pre-check in `_handle_rewards` skips claim attempt when belt known-full; fallback to attempt-then-react when field absent; 201 tests
- #77 — fake_merchant: Foul Potion allowed at shop/fake_merchant (no target vote; API auto-infers merchant); 191 tests

## Active Issue
None

## Up Next
1. #87 — OBS browser-source overlay for vote prompts (CDN-synced visual sync, no flat delay needed)
2. #54 — Potion edge cases: combat-only filter for non-AnyEnemy potions
3. #44 — Feature: end the run via supermajority chat vote
4. #36 — Viewer info commands: deck/pile/relics/status lookup

## Key Decisions
- Bot and game run on same PC (localhost API)
- All API URLs required via .env — no hardcoded defaults in committed files
- Fail loud on missing config at startup
- Logging at INFO level to terminal + `logs/bot.log` (truncated each run, gitignored)
- Test suite: `python -m pytest` from project root; 234 tests, no live deps; `bot/client.py` not tested (twitchio mocking complexity)
- GitHub Issues for all task tracking; Claude can create/label/prioritize autonomously
- `PROGRESS.md` stays capped at ~20-30 lines; full history lives in GitHub Issues
- STS2MCP API on `localhost:15526`; enemy `entity_id` lives at `battle.enemies[i].entity_id`
- `game/actions.py` is the translation layer: (state_type, vote_option) → API request body
- Vote options use actual 1-indexed hand positions (matching in-game card numbers); `can_play` field determines what's offered
