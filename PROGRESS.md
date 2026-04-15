# Progress

## Current Milestone
`PoC`

## Recently Completed
- #21 — Stale vote queue: pre/post-window state checks in `_event_runner`; live-tested
- #26 — Mid-event option change detection: `event_options` in `GameState`, within-state re-queue, auto-proceed for single proceed option, dynamic event/hand_select/card_select options, auto-confirm for hand_select+card_select, rewards auto-handling (gold/potion auto-claim, card opens for vote, auto-proceed); live-tested full flow

## Active Issue
None

## Up Next
1. #7 — Database Logging
2. #9 — Production Hardening
3. #28 — Descriptive vote option labels in chat announcements

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
