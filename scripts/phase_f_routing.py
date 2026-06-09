#!/usr/bin/env python3
"""Phase F — Cron routing template.

Lists existing Hermes cron jobs on the VPS and applies a default routing
template. Auto-pauses jobs that don't match any template bucket. Never
deletes — uninstall is a separate command.
"""

from __future__ import annotations

import json
import shlex
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
from lib import ansi, state, ssh  # type: ignore

PHASE = "f_routing"

VENV_PY = "/root/.hermes/hermes-agent/venv/bin/python"
HERMES_CLI = f"{VENV_PY} -m hermes_cli.main"

DEFAULT_ROUTING = {
    # name fragment (case-insensitive) → bucket.
    # "dashboard" = the visible scheduled-brief topic. "local" = read on demand.
    # Nothing auto-routes to the Decisions topic: that surface is reserved for
    # the proposal mint/execute loop (the watchers phase H creates point there
    # directly), so every card in Decisions stays something you actually act on.
    "morning-brief": "dashboard",
    "nightly-accomplishment": "dashboard",
    "midday-check": "dashboard",
    "evening-wrap": "dashboard",
    "remind ": "dashboard",
    "relationships-pulse": "dashboard",
    "mood-mirror": "dashboard",
    "learning-loop": "dashboard",
    "soul-refinement": "dashboard",
    "imessage-opportunity-scout": "local",
    "decisions-tracker": "local",
    "daily-money-opportunity-scout": "local",
    "operator-pulse": "local",
    "daily-living-crm": "local",
    "message feed watchdog": "local",
    "instagram-thumbnail-import": "local",
    "alive-operator-watch": "local",
    "journal-pipeline": "local",
    "dream-pass": "local",
    "health-pulse": "local",
    "weekly-brain-crm-hygiene": "local",
    "daily-code-tavern-system-pulse": "local",
}


def _list_jobs(host: str, key: str) -> list[dict]:
    r = ssh.run(host, "cat /root/.hermes/cron/jobs.json 2>/dev/null", ssh_key=key, timeout=15)
    if r.returncode != 0 or not r.stdout.strip():
        return []
    try:
        data = json.loads(r.stdout)
    except json.JSONDecodeError:
        return []
    return data.get("jobs", []) if isinstance(data, dict) else data


def _bucket_for(name: str) -> str | None:
    lower = name.lower()
    for fragment, bucket in DEFAULT_ROUTING.items():
        if fragment in lower:
            return bucket
    return None


def _deliver_for(bucket: str, dashboard: int, decisions: int, chat: int) -> str:
    if bucket == "dashboard":
        return f"telegram:{chat}:{dashboard}"
    if bucket == "decisions":
        return f"telegram:{chat}:{decisions}"
    return "local"


def run() -> int:
    if state.is_complete(PHASE):
        ansi.ok(f"phase {PHASE} already complete")
        return 0

    state.mark_phase(PHASE, "in_progress")
    ansi.header("Phase F — Cron routing")

    data = state.read()
    host = data.get("vps", {}).get("host")
    key = data.get("vps", {}).get("ssh_key")
    tg = data.get("telegram", {})
    chat = tg.get("supergroup_chat_id")
    dashboard = tg.get("dashboard_thread_id")
    decisions = tg.get("decisions_thread_id")
    if not (chat and dashboard and decisions):
        state.mark_phase(PHASE, "blocked", blocker="phase E incomplete (no chat/thread ids)")
        return 1

    jobs = _list_jobs(host, key)
    if not jobs:
        ansi.warn("no cron jobs found on VPS — nothing to route. proceeding.")
        state.mark_phase(PHASE, "complete")
        return 0

    actions: list[tuple[str, str, str]] = []  # (job_id, name, action)
    for j in jobs:
        name = j.get("name", "")
        job_id = j.get("id")
        bucket = _bucket_for(name)
        if not bucket:
            actions.append((job_id, name, "pause"))
            continue
        target = _deliver_for(bucket, dashboard, decisions, chat)
        if j.get("deliver") != target:
            actions.append((job_id, name, f"edit→{target}"))
        else:
            actions.append((job_id, name, "ok"))

    ansi.info("planned actions:")
    for jid, name, action in actions:
        marker = ansi.ok if action == "ok" else ansi.info
        marker(f"  {action:30s}  {name}")

    print("\nApply these changes? [y/N] ", end="")
    try:
        confirm = input().strip().lower()
    except (EOFError, KeyboardInterrupt):
        confirm = ""
    if confirm != "y":
        state.mark_phase(PHASE, "blocked", blocker="user did not confirm routing apply")
        return 1

    failures: list[str] = []
    for jid, name, action in actions:
        if action == "ok":
            continue
        if not jid:
            failures.append(f"{name}: missing job id")
            continue
        if action == "pause":
            r = ssh.run(
                host,
                f"cd /root/.hermes/hermes-agent && {HERMES_CLI} cron pause {shlex.quote(str(jid))}",
                ssh_key=key,
                timeout=15,
            )
        elif action.startswith("edit→"):
            target = action.removeprefix("edit→")
            r = ssh.run(
                host,
                f"cd /root/.hermes/hermes-agent && {HERMES_CLI} cron edit {shlex.quote(str(jid))} --deliver {shlex.quote(target)}",
                ssh_key=key,
                timeout=15,
            )
        else:
            failures.append(f"{name}: unknown action {action}")
            continue
        if r.returncode != 0:
            failures.append(f"{name}: {action} failed: {(r.stderr or r.stdout).strip()[:300]}")

    if failures:
        for failure in failures:
            ansi.fail(failure)
        state.mark_phase(PHASE, "blocked", blocker=f"{len(failures)} cron routing command(s) failed")
        return 1

    ansi.ok(f"applied {sum(1 for _,_,a in actions if a != 'ok')} changes")
    state.mark_phase(PHASE, "complete")
    return 0


if __name__ == "__main__":
    sys.exit(run())
