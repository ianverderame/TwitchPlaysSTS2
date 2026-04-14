# Progress

## Current Milestone
`PoC`

## Recently Completed
- #21 — Stale vote queue: pre-window + post-window state checks in `_event_runner`; stale votes discarded with WARNING log; live-tested through event→map→monster transition
- #19 — Combat: target entity_id for play_card: enemies captured in GameState, auto-target first enemy, fresh state re-fetched at action time, live-tested (Strike targeting Nibbit)
- #5 — PoC: First Game Action Execution: vote winner sent to STS2MCP API, random fallback on no votes/tie, retry on API failure, live-tested end-to-end

## Active Issue
None — #21 complete

## Up Next
1. #11 — Detect within-state game changes (re-queue vote after each card play)
2. #6 — STS2-MenuControl Integration
3. #17 — Catalog full game state_type map and handle post-run states

## Key Decisions
- Bot and game run on same PC (localhost API)
- All API URLs required via .env — no hardcoded defaults in committed files
- Fail loud on missing config at startup
- Terminal logging at INFO level only; no log files
- No automated tests for PoC
- GitHub Issues for all task tracking; Claude can create/label/prioritize autonomously
- `PROGRESS.md` stays capped at ~20-30 lines; full history lives in GitHub Issues
- STS2MCP API on `localhost:15526`; enemy `entity_id` lives at `battle.enemies[i].entity_id`
- `game/actions.py` is the translation layer: (state_type, vote_option) → API request body
- Re-fetch fresh state after vote closes to avoid stale enemy data at action time
