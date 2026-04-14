# Progress

## Current Milestone
`PoC`

## Recently Completed
- PRD written and posted as GitHub issue #1
- GitHub labels, milestones, and issue template created

## Active Issue
None

## Up Next
1. Set up Twitch bot account and credentials
2. Implement PoC bot (issue to be created)

## Key Decisions
- Bot and game run on same PC (localhost API)
- Single API ping on startup; no polling loop for PoC
- Manual API recheck via terminal command
- Fail loud on missing config at startup
- Terminal logging at INFO level only; no log files
- No automated tests for PoC
- GitHub Issues for all task tracking; Claude can create/label/prioritize autonomously
- `PROGRESS.md` stays capped at ~20-30 lines; full history lives in GitHub Issues
