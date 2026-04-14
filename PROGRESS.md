# Progress

## Current Milestone
`PoC`

## Recently Completed
- #5 — PoC: First Game Action Execution: vote winner sent to STS2MCP API, random fallback on no votes/tie, retry on API failure, live-tested end-to-end
- #16 — Vote window random fallback: absorbed into #5
- #4 — PoC: Basic Vote Window: typed event queue, 10s vote window, KNOWN_STATES registry, game start/end announcements
- #3 — PoC: Game State Polling Loop: 1s poll of STS2MCP, state_type transitions logged, clean Ctrl+C shutdown

## Active Issue
None — #5 complete, ready for #19 or #6

## Up Next
1. #19 — Combat: resolve target entity_id for play_card actions (blocker for combat)
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
- STS2 API returns lowercase state_types (e.g. `menu`, `monster`, `card_reward`)
- `game/actions.py` is the translation layer: (state_type, vote_option) → API request body
- All state_type→API mappings need live verification; map options especially unverified
