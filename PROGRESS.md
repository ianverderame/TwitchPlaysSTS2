# Progress

## Current Milestone
`PoC`

## Recently Completed
- #77 — fake_merchant: Foul Potion allowed at shop/fake_merchant (no target vote; API auto-infers merchant); 191 tests
- #76 — Remove max_belt_size config: deleted `potions:` from settings/loader, dropped belt-full pre-check in `shop_item_available`, rewards now attempt-then-react; live-tested shop with full belt; 191 tests
- #71 — Belt-full live test: fixed infinite-retry bug; `attempted_potion_indices` detects silent failure; live-tested discard-to-claim and skip paths; 191 tests
- #75 — Pre-ship hardening & code cleanup: all 11 Part B hygiene items + 5 additional findings fixed; httpx retry with exponential backoff (configurable); TwitchIO reconnect guard; 195 tests; closes #9 and #61

## Active Issue
None

## Up Next
1. #54 — Potion edge cases: combat-only filter for non-AnyEnemy potions
2. #44 — Feature: end the run via supermajority chat vote
3. #36 — Viewer info commands: deck/pile/relics/status lookup

## Key Decisions
- Bot and game run on same PC (localhost API)
- All API URLs required via .env — no hardcoded defaults in committed files
- Fail loud on missing config at startup
- Logging at INFO level to terminal + `logs/bot.log` (truncated each run, gitignored)
- Test suite: `python -m pytest` from project root; 195 tests, no live deps; `bot/client.py` not tested (twitchio mocking complexity)
- GitHub Issues for all task tracking; Claude can create/label/prioritize autonomously
- `PROGRESS.md` stays capped at ~20-30 lines; full history lives in GitHub Issues
- STS2MCP API on `localhost:15526`; enemy `entity_id` lives at `battle.enemies[i].entity_id`
- `game/actions.py` is the translation layer: (state_type, vote_option) → API request body
- Vote options use actual 1-indexed hand positions (matching in-game card numbers); `can_play` field determines what's offered
