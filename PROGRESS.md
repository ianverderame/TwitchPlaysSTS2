# Progress

## Current Milestone
`PoC`

## Recently Completed
- #38 (partial) — hand_select multi-select (can_confirm); treasure auto-claim + 3s pause; shop gold preamble, auto-leave, Remove Card grouped vote; rest site auto-proceed retry loop; Ancient relic vote (event state); single map node auto-select (5s); all 8 map node types confirmed
- #31 — ?map command: text preview of upcoming map nodes (up to 8 floors); `?` info command convention; self-message guard; live-tested
- #47 — Silent stops: auto-proceed treasure/rest_site; shop re-queue + leave-only fallback; playable_card_indices change detection (relic card draw); diagnostic DEBUG logging; live-tested
- #33 — Smith upgrade: deck-wide card vote; dedup identical copies (e.g. `Defend (x5)`); numbered `!N` voting; 30s window; green announcement header; select_card + confirm_selection flow; live-tested
- #28 — Descriptive vote labels: `!N=Label` for all in-run states; `game/labels.py`; map left→right preamble; dynamic rest_site/map/shop options; shop shows name+price, filters unaffordable+full-belt potions

## Active Issue
None

## Up Next
1. #38 — Rest site extended options (Recall/Toke/Lift/Dig) — verify live when relic acquired
2. #51 — Potions: belt filter verification, use/discard voting (medium priority, pre-1.0)
3. #7 — Database Logging
4. #9 — Production Hardening

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
