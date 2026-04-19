# Progress

## Current Milestone
`PoC`

## Recently Completed
- #63 — End-game nav: combat→overlay detection, `_handle_game_ended`, return_to_main_menu, timeline epoch claiming, 30s countdown; live-tested win + loss + epoch unlock
- #53 — Belt-full potion reward: discard-to-claim vote (`_handle_belt_full_potion_discard`); skip tracking in rewards loop; `_tally` fix (skip never random); event vote retry fix; game-started as announcement
- #60 — DRY chat-send: `_chat()` helper, `self.broadcaster` cached once, all send sites unified; live-tested
- #59 — All 7 hardcoded timings/retries promoted to settings.yaml; threaded through loader, clients, polling, options, bot
- #62 — 165-test suite: state/actions/options/labels/polling/api_client/vote_manager; runs via `python -m pytest`, no live deps
- #77 — fake_merchant: Foul Potion allowed at shop/fake_merchant (no target vote; API auto-infers merchant); 191 tests

## Active Issue
None

## Up Next
1. #71 — Live test: belt-full potion discard-to-claim + session untested changes
2. #75 — Pre-ship hardening & code cleanup (consolidated from #9 + #61)
3. #54 — Potion edge cases: combat-only filter (Foul Potion at shop/fake_merchant now resolved in #77)

## Key Decisions
- Bot and game run on same PC (localhost API)
- All API URLs required via .env — no hardcoded defaults in committed files
- Fail loud on missing config at startup
- Logging at INFO level to terminal + `logs/bot.log` (truncated each run, gitignored)
- Test suite: `python -m pytest` from project root; 191 tests, no live deps; `bot/client.py` not tested (twitchio mocking complexity)
- GitHub Issues for all task tracking; Claude can create/label/prioritize autonomously
- `PROGRESS.md` stays capped at ~20-30 lines; full history lives in GitHub Issues
- STS2MCP API on `localhost:15526`; enemy `entity_id` lives at `battle.enemies[i].entity_id`
- `game/actions.py` is the translation layer: (state_type, vote_option) → API request body
- Vote options use actual 1-indexed hand positions (matching in-game card numbers); `can_play` field determines what's offered
