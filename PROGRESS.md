# Progress

## Current Milestone
`PoC`

## Recently Completed
- #3 — PoC: Game State Polling Loop: 1s poll of STS2MCP, state_type transitions logged, clean Ctrl+C shutdown
- #2 — PoC Bot Implementation: bot connects to Twitch, posts "Bot is online!", pings STS2MCP API, responds to `!test`

## Active Issue
None — #3 complete, ready for #4

## Up Next
1. #4 — PoC: Basic Vote Window
2. #5 — PoC: First Game Action Execution
3. #6 — STS2-MenuControl Integration

## Key Decisions
- Bot and game run on same PC (localhost API)
- All API URLs required via .env — no hardcoded defaults in committed files
- Fail loud on missing config at startup
- Terminal logging at INFO level only; no log files
- No automated tests for PoC
- GitHub Issues for all task tracking; Claude can create/label/prioritize autonomously
- `PROGRESS.md` stays capped at ~20-30 lines; full history lives in GitHub Issues
