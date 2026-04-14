# Progress

## Current Milestone
`PoC`

## Recently Completed
- #2 — PoC Bot Implementation: bot connects to Twitch, posts "Bot is online!", pings STS2MCP API, responds to `!test`

## Active Issue
None — #2 merged (PR #10), ready for #3

## Up Next
1. #3 — PoC: Game State Polling Loop
2. #4 — PoC: Basic Vote Window
3. #5 — PoC: First Game Action Execution

## Key Decisions
- Bot and game run on same PC (localhost API)
- Single API ping on startup; no polling loop for PoC
- Manual API recheck via terminal command
- Fail loud on missing config at startup
- Terminal logging at INFO level only; no log files
- No automated tests for PoC
- GitHub Issues for all task tracking; Claude can create/label/prioritize autonomously
- `PROGRESS.md` stays capped at ~20-30 lines; full history lives in GitHub Issues
