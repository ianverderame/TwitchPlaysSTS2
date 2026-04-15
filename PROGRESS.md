# Progress

## Current Milestone
`PoC`

## Recently Completed
- #11 — State map catalog + within-state detection: full state_type map, `is_play_phase` vote trigger, dynamic playable-card options, within-turn re-queue, stale checks for combat; live-tested full run
- #21 — Stale vote queue: pre-window + post-window state checks in `_event_runner`; stale votes discarded with WARNING log; live-tested through event→map→monster transition
- #19 — Combat: target entity_id for play_card: enemies captured in GameState, auto-target first enemy, fresh state re-fetched at action time, live-tested (Strike targeting Nibbit)

## Active Issue
None — #11 complete

## Up Next
1. #6 — STS2-MenuControl Integration (pre-run menu/character selection only; all in-run states handled by STS2MCP)
2. #7 — Database Logging
3. #9 — Production Hardening

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
- Vote options use actual 1-indexed hand positions (matching in-game card numbers); `can_play` field determines what's offered
