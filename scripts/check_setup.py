#!/usr/bin/env python3
"""Master orchestrator for hermes-proactive.

Reads state, decides next pending phase, and points the calling agent
at the right phase script. Does NOT execute phase scripts itself —
the agent runs each one based on output from this gate.

Usage:
  check_setup.py            # report current state, name next action
  check_setup.py status     # alias
  check_setup.py reset <phase_letter>   # reset one phase to pending
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "lib"))

from lib import ansi, state  # type: ignore

PHASE_LABELS = {
    "a_mac_prereqs": "Mac prerequisites (Python, SSH key, FDA, VPS hostname)",
    "b_vps":         "Hermes Agent install on VPS",
    "c_telegram":    "Telegram bot (BotFather) registered + connected to Hermes",
    "d_imessage":    "Mac iMessage bridge installed + launchd loaded",
    "e_supergroup":  "Telegram supergroup 'Hermes Ops' with Dashboard + Decisions topics",
    "f_routing":     "Cron routing template applied",
    "g_oauth":       "Google Cloud project + OAuth client + Workspace token",
    "h_libs":        "Helper libs + watchers deployed to VPS",
    "i_user_md":     "Proposal-handler section appended to /root/.hermes/USER.md",
    "j_smoke":       "End-to-end smoke test (Telegram yes <id> approval + Calendar verify)",
}

PHASE_SCRIPTS = {p: f"scripts/phase_{p}.py" for p in state.PHASES}


def show_status() -> None:
    data = state.read()
    ansi.header("hermes-proactive status")
    for phase in state.PHASES:
        status = data["phases"].get(phase, "pending")
        label = PHASE_LABELS[phase]
        marker = {
            "complete": ansi.ok,
            "in_progress": ansi.info,
            "blocked": ansi.fail,
            "pending": lambda m: print(" ", ansi.dim("○"), m),
        }.get(status, lambda m: print(" ", "?", m))
        marker(f"{phase} — {label}")
        if status == "blocked":
            blocker = data.get("blockers", {}).get(phase)
            if blocker:
                print("    ", ansi.dim(f"blocker: {blocker}"))


def next_action() -> int:
    data = state.read()
    if state.all_complete():
        ansi.ok("hermes-proactive is fully set up.")
        ansi.info("Try replying 'yes <id>' to any pending proposal in Decisions to test the loop.")
        return 0

    pending = state.next_pending()
    assert pending is not None
    status = data["phases"][pending]

    skill_dir = Path(__file__).resolve().parent.parent
    script_path = skill_dir / PHASE_SCRIPTS[pending]

    if status == "blocked":
        ansi.fail(f"Phase {pending} ({PHASE_LABELS[pending]}) is blocked.")
        blocker = data.get("blockers", {}).get(pending, "")
        if blocker:
            print(f"  reason: {blocker}")
        ansi.info(f"resolve, then re-run: python3 {script_path}")
        return 1

    ansi.header(f"Next phase: {pending}")
    ansi.info(PHASE_LABELS[pending])
    ansi.info(f"run: python3 {script_path}")
    return 0


def reset(phase_letter: str) -> int:
    full = next((p for p in state.PHASES if p.startswith(f"{phase_letter}_")), None)
    if not full:
        ansi.fail(f"no phase starts with '{phase_letter}_'. valid: {[p[0] for p in state.PHASES]}")
        return 1
    state.reset_phase(full)
    ansi.ok(f"reset phase {full} to pending")
    return 0


def main(argv: list[str]) -> int:
    if len(argv) >= 2 and argv[1] in ("status", "show"):
        show_status()
        return 0
    if len(argv) >= 3 and argv[1] == "reset":
        return reset(argv[2].lower())

    show_status()
    print()
    return next_action()


if __name__ == "__main__":
    sys.exit(main(sys.argv))
