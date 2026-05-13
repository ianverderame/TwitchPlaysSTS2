---
name: start-session
description: Orient Claude at the start of a new session by reading project context and recommending next steps. Use at the beginning of every working session.
---

0. **Branch hygiene — do this before reading any files:**
   - Run `git branch --show-current`. If not on `main`, run `git checkout main` before anything else.
   - Run `git fetch origin && git pull origin main` to ensure you are on the latest commit.
   - Do not read `PROGRESS.md`, list issues, or explore the codebase until you have confirmed you are on an up-to-date `main`. This step cannot be skipped or deferred.

1. Read `PROGRESS.md` in the project root to understand current state.

2. Read `CLAUDE.md` in the project root to understand project conventions and structure.

3. Check open GitHub Issues with `gh issue list --state open` to see the current backlog.

4. Check git state:
   - Run `git status` and `git log origin/HEAD..HEAD` to check for uncommitted changes and unpushed commits.
   - Run `git log HEAD..origin/HEAD` to check if the current branch is behind remote.
   - If there are uncommitted changes, flag them — do not create a branch until resolved.
   - If there are unpushed commits, flag them and suggest pushing.
   - If the branch is behind remote, pull before proceeding: `git pull`.
   - List all existing branches matching `issue-{active-issue-number}/*` to determine the next session number (e.g., if `issue-2/poc-bot-s1` exists, next is `s2`). If no such branches exist, start at `s1`.
   - Do NOT create the branch yet — just determine the name.

5. Summarize in plain language and then ask the user to confirm before proceeding:
   - What milestone we're on
   - What was recently completed
   - What the recommended next action is and why
   - What branch will be created upon confirmation: `issue-{number}/{short-description}-s{n}`

6. After the user confirms the direction, create and switch to the session branch.

Do not ask for input before completing steps 0-4. Orient, report, and then ask for confirmation.

## Session constraints — enforce these for the entire session

- Work on exactly one active GitHub Issue per session. Do not implement anything outside its scope.
- If out-of-scope work is identified, create a GitHub Issue for it and stop — do not implement it.
- Never commit or push without explicit user request.
- When updating `PROGRESS.md`, keep it capped at ~20-30 lines. Drop older completed items as new ones are added. Full history lives in GitHub Issues.
