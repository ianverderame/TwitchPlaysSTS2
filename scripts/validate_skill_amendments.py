"""
Dry-run validation for skill-improvements/auto-v1.

Simulates the two new skill gates against the historical failure scenarios
from the /insights 50-session analysis. Each scenario shows what the old
skill would have done (silent pass) vs what the new step catches (hard stop).

Run with: python3 scripts/validate_skill_amendments.py
"""

import subprocess
import sys


PASS = "\033[32mPASS\033[0m"
FAIL = "\033[31mFAIL\033[0m"
CATCH = "\033[33mCATCHES\033[0m"


# ---------------------------------------------------------------------------
# start-session Step 0: branch hygiene gate
# ---------------------------------------------------------------------------

def _current_branch() -> str:
    return subprocess.check_output(
        ["git", "branch", "--show-current"], text=True
    ).strip()


def simulate_start_session_branch_check(branch: str) -> dict:
    """
    Simulate the new Step 0 logic against a given branch name.
    Returns {"caught": bool, "message": str}.
    """
    if branch != "main":
        return {
            "caught": True,
            "message": (
                f"[Step 0 HARD STOP] Current branch is '{branch}', not 'main'. "
                "Run `git checkout main && git pull origin main` before proceeding."
            ),
        }
    return {"caught": False, "message": "[Step 0] On main — proceeding."}


# ---------------------------------------------------------------------------
# end-session Step 2: CONFIRMED / INFERRED / UNVERIFIED gate
# ---------------------------------------------------------------------------

def simulate_end_session_criteria_check(criteria: list[dict]) -> dict:
    """
    Simulate the new Step 2 hard-stop logic.
    criteria: list of {"label": str, "description": str, "label": "CONFIRMED"|"INFERRED"|"UNVERIFIED"}
    Returns {"caught": bool, "flagged": list, "message": str}.
    """
    flagged = [c for c in criteria if c["status"] in ("INFERRED", "UNVERIFIED")]
    if flagged:
        names = [c["description"] for c in flagged]
        return {
            "caught": True,
            "flagged": flagged,
            "message": (
                "[Step 2 HARD STOP] The following criteria were not directly observed "
                f"during live testing: {names}. "
                "Spot-check before closing, or accept the risk and close anyway?"
            ),
        }
    return {"caught": False, "flagged": [], "message": "[Step 2] All criteria CONFIRMED — safe to close."}


# ---------------------------------------------------------------------------
# Scenarios
# ---------------------------------------------------------------------------

def run_scenarios() -> int:
    failures = 0

    print("=" * 65)
    print("start-session Step 0 — branch hygiene gate")
    print("=" * 65)

    scenarios_start = [
        # Historical failure: Claude started on a non-main feature branch
        # (user had to interrupt mid-session — noted twice in insights)
        {
            "name": "Non-main branch (historical: branched from wrong commit)",
            "branch": "issue-77/fake-merchant-s1",
            "expect_caught": True,
        },
        # Historical failure: Claude started on a detached HEAD / stale branch
        {
            "name": "Stale session branch (historical: session started before pull)",
            "branch": "issue-84/potion-slots-s2",
            "expect_caught": True,
        },
        # Happy path: already on main
        {
            "name": "Already on main (should pass through)",
            "branch": "main",
            "expect_caught": False,
        },
    ]

    for s in scenarios_start:
        result = simulate_start_session_branch_check(s["branch"])
        ok = result["caught"] == s["expect_caught"]
        status = PASS if ok else FAIL
        marker = CATCH if result["caught"] else "pass"
        print(f"  [{status}] {s['name']}")
        print(f"         -> {marker}: {result['message']}")
        if not ok:
            failures += 1
    print()

    print("=" * 65)
    print("end-session Step 2 — CONFIRMED / INFERRED / UNVERIFIED gate")
    print("=" * 65)

    scenarios_end = [
        # Historical failure: PR #26 — Claude self-confirmed criteria as "code
        # looks correct" without live test. Insights flagged this by name.
        {
            "name": "PR #26 pattern — criteria inferred, not live-tested",
            "criteria": [
                {"description": "Vote window opens on first card detection", "status": "CONFIRMED"},
                {"description": "Winning vote sent to game API", "status": "INFERRED"},
                {"description": "Chat notified of result", "status": "INFERRED"},
            ],
            "expect_caught": True,
        },
        # Historical failure: polling bug / OAuth issue — fix was shipped
        # after code review only, without re-live-testing the fix.
        {
            "name": "Post-fix re-test gap (historical: fix shipped after code review only)",
            "criteria": [
                {"description": "Polling resumes after Soul card", "status": "INFERRED"},
                {"description": "No stale-vote capture on retry", "status": "UNVERIFIED"},
            ],
            "expect_caught": True,
        },
        # Historical failure: oauth issue — criteria partially confirmed but one missed
        {
            "name": "Partial confirmation (one unverified criterion slips through)",
            "criteria": [
                {"description": "OAuth token refreshes correctly", "status": "CONFIRMED"},
                {"description": "Reconnects on token expiry", "status": "UNVERIFIED"},
            ],
            "expect_caught": True,
        },
        # Happy path: all CONFIRMED
        {
            "name": "All criteria confirmed live (should close cleanly)",
            "criteria": [
                {"description": "Combat vote opens on enemy detection", "status": "CONFIRMED"},
                {"description": "Target selection sub-vote fires", "status": "CONFIRMED"},
            ],
            "expect_caught": False,
        },
    ]

    for s in scenarios_end:
        result = simulate_end_session_criteria_check(s["criteria"])
        ok = result["caught"] == s["expect_caught"]
        status = PASS if ok else FAIL
        marker = CATCH if result["caught"] else "pass"
        print(f"  [{status}] {s['name']}")
        print(f"         -> {marker}: {result['message']}")
        if not ok:
            failures += 1
    print()

    print("=" * 65)
    total = len(scenarios_start) + len(scenarios_end)
    passed = total - failures
    print(f"Results: {passed}/{total} scenarios behave as expected")
    if failures:
        print(f"  {failures} scenario(s) did not match expected gate behaviour — review logic above.")
    print("=" * 65)

    return failures


if __name__ == "__main__":
    sys.exit(run_scenarios())
