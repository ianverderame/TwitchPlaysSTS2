---
name: end-session
description: Close out a working session by updating PROGRESS.md, closing the GitHub Issue, and ensuring the branch is committed and pushed. Use when the active issue's acceptance criteria are met.
---

1. Read `PROGRESS.md` to confirm the active issue.

2. Check the active GitHub Issue with `gh issue view {number}` and do a **thorough** verification of all acceptance criteria. For each criterion, assign exactly one label:
   - **CONFIRMED** — directly observed during a live test in this session
   - **INFERRED** — code looks correct but not directly observed
   - **UNVERIFIED** — not checked at all

   **Hard stop:** If ANY criterion is INFERRED or UNVERIFIED, stop and ask the user: "The following criteria were not directly observed during live testing: [list]. Spot-check before closing, or accept the risk and close anyway?" Do NOT close until you receive an explicit reply. "Code looks correct" never counts as CONFIRMED.

   **Re-test gate:** If a bug was discovered and fixed during live testing this session, it cannot be labeled CONFIRMED unless it was re-tested live *after* the fix. A code-only review of a fix is INFERRED.

   Do not close the issue until the user explicitly confirms all criteria are satisfied.

3. Update `PROGRESS.md` **before asking the user to commit**:
   - Move the active issue to Recently Completed
   - Clear the Active Issue field
   - Update Up Next based on open GitHub Issues
   - Keep the file capped at ~20-30 lines

4. Check git state with `git status`:
   - If there are uncommitted changes (including the PROGRESS.md update), flag them and stop — remind the user to commit before closing out.
   - If there are unpushed commits, flag them and suggest pushing.

5. Show the user a summary of what will be closed and ask for explicit confirmation before proceeding.

6. After confirmation:
   - Close the GitHub Issue with `gh issue close {number} --comment "Completed in session."`
   - Do NOT commit, push, or merge branches — wait for explicit user instruction.
