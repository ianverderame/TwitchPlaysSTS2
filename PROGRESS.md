# Progress

## Current Milestone
`PoC`

## Recently Completed
- #4 — PoC: Basic Vote Window: typed event queue, 10s vote window, KNOWN_STATES registry, game start/end announcements, live-tested state_types
- #3 — PoC: Game State Polling Loop: 1s poll of STS2MCP, state_type transitions logged, clean Ctrl+C shutdown
- #2 — PoC Bot Implementation: bot connects to Twitch, posts "Bot is online!", pings STS2MCP API, responds to `!test`

## Active Issue
None — #4 complete, ready for #5

## Up Next
1. #5 — PoC: First Game Action Execution
2. #16 — Vote window: random fallback when no votes / tied (needed before #5)
3. #6 — STS2-MenuControl Integration

## Key Decisions
- Bot and game run on same PC (localhost API)
- All API URLs required via .env — no hardcoded defaults in committed files
- Fail loud on missing config at startup
- Terminal logging at INFO level only; no log files
- No automated tests for PoC
- GitHub Issues for all task tracking; Claude can create/label/prioritize autonomously
- `PROGRESS.md` stays capped at ~20-30 lines; full history lives in GitHub Issues
- STS2 API returns lowercase state_types (e.g. `menu`, `monster`, `card_reward`)
- `game/events.py` typed event union is the extension point for new game notifications
- `game/options.py` KNOWN_STATES is the living registry for state_type → vote options
