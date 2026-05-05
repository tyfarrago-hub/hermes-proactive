#!/usr/bin/env python3
"""Phase J — End-to-end smoke test.

Mints a synthetic calendar.add proposal on the VPS, executes it, confirms
the calendar event was created, deletes it, and sends a setup-complete
receipt to the Daily Briefs topic via the bundled _vps_send_telegram.py.

All VPS-side Python is shipped as files via SCP — no fragile inline -c
f-string nesting.
"""

from __future__ import annotations

import json
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
from lib import ansi, state, ssh  # type: ignore

PHASE = "j_smoke"
SKILL_DIR = Path(__file__).resolve().parent.parent
VENV_PY = "/root/.hermes/hermes-agent/venv/bin/python"
SEND_HELPER_LOCAL = SKILL_DIR / "scripts" / "_vps_send_telegram.py"
SEND_HELPER_REMOTE = "/tmp/_vps_send_telegram.py"
POLL_TIMEOUT_S = 300
POLL_INTERVAL_S = 5


SMOKE_PROGRAM = """
import json, sys, uuid
sys.path.insert(0, '/root/.hermes/lib')
import proposals

p = proposals.mint(
    type_='calendar.add',
    source='hermes-proactive smoke',
    title='hermes-proactive setup smoke test - delete me',
    datetime_iso='2099-01-01T12:00:00-05:00',
    datetime_human='2099-01-01 12:00 ET',
    contact='self',
    source_msg_id='smoke-' + uuid.uuid4().hex[:8],
)
out = {
    'minted_id': p['id'],
    'datetime_human': p['datetime_human'],
    'title': p['title'],
}
print(json.dumps(out))
"""


STATUS_PROGRAM = """
import json, sys
sys.path.insert(0, '/root/.hermes/lib')
import proposals

p = proposals.get(sys.argv[1])
print(json.dumps(p or {}))
"""


CLEANUP_PROGRAM = """
import sys
sys.path.insert(0, '/root/.hermes/lib')
import google_workspace as gws
event_id = sys.argv[1]
gws._calendar().events().delete(calendarId='primary', eventId=event_id).execute()
print('deleted', event_id)
"""


ABORT_PROGRAM = """
import sys
sys.path.insert(0, '/root/.hermes/lib')
import proposal_executor
proposal_executor.execute(sys.argv[1], 'no')
print('rejected', sys.argv[1])
"""


def _scp_text(host: str, key: str, body: str, remote_path: str) -> bool:
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as f:
        f.write(body)
        local = f.name
    r = ssh.scp(local, host, remote_path, ssh_key=key)
    return r.returncode == 0


def run() -> int:
    if state.is_complete(PHASE):
        ansi.ok(f"phase {PHASE} already complete")
        return 0

    state.mark_phase(PHASE, "in_progress")
    ansi.header("Phase J — End-to-end smoke test")

    data = state.read()
    host = data.get("vps", {}).get("host")
    key = data.get("vps", {}).get("ssh_key")
    chat = data.get("telegram", {}).get("supergroup_chat_id")
    daily = data.get("telegram", {}).get("daily_thread_id")
    proactive = data.get("telegram", {}).get("proactive_thread_id")
    if not all([host, key, chat, daily, proactive]):
        ansi.fail("missing VPS or Telegram chat/thread ids from setup state")
        state.mark_phase(PHASE, "blocked", blocker="missing prereqs (a/e)")
        return 1

    if not SEND_HELPER_LOCAL.exists():
        state.mark_phase(PHASE, "blocked", blocker=f"missing helper {SEND_HELPER_LOCAL}")
        return 1

    # Ship helper programs as files; no inline -c quoting.
    if not _scp_text(host, key, SMOKE_PROGRAM, "/tmp/_hp_smoke.py"):
        state.mark_phase(PHASE, "blocked", blocker="scp smoke program failed")
        return 1
    if not _scp_text(host, key, STATUS_PROGRAM, "/tmp/_hp_smoke_status.py"):
        state.mark_phase(PHASE, "blocked", blocker="scp status program failed")
        return 1
    if not _scp_text(host, key, CLEANUP_PROGRAM, "/tmp/_hp_smoke_cleanup.py"):
        state.mark_phase(PHASE, "blocked", blocker="scp cleanup program failed")
        return 1
    if not _scp_text(host, key, ABORT_PROGRAM, "/tmp/_hp_smoke_abort.py"):
        state.mark_phase(PHASE, "blocked", blocker="scp abort program failed")
        return 1
    r0 = ssh.scp(SEND_HELPER_LOCAL, host, SEND_HELPER_REMOTE, ssh_key=key)
    if r0.returncode != 0:
        state.mark_phase(PHASE, "blocked", blocker="scp send helper failed")
        return 1

    # Mint a real pending proposal. Do not execute it directly. The point of
    # this phase is to prove Hermes handles the Telegram approval reply.
    r = ssh.run(host, f"{VENV_PY} /tmp/_hp_smoke.py", ssh_key=key, timeout=90)
    if r.returncode != 0:
        ansi.fail(f"smoke program exited {r.returncode}: {r.stderr[:600]}")
        state.mark_phase(PHASE, "blocked", blocker="smoke program error")
        return 1

    # Take the LAST line of stdout — JSON. Earlier lines may be incidental prints.
    last_line = (r.stdout.strip().splitlines() or [""])[-1]
    try:
        result = json.loads(last_line)
    except json.JSONDecodeError:
        ansi.fail(f"smoke output not JSON: {last_line[:300]}")
        state.mark_phase(PHASE, "blocked", blocker="smoke output unparseable")
        return 1

    proposal_id = result.get("minted_id")
    if not proposal_id:
        ansi.fail(f"smoke did not mint a proposal id: {result}")
        state.mark_phase(PHASE, "blocked", blocker="smoke proposal mint failed")
        return 1

    proposal_msg = (
        "Calendar add?\\n"
        f"self - {result.get('title', 'hermes-proactive setup smoke test')}\\n"
        f"{result.get('datetime_human', '2099-01-01 12:00 ET')}\\n\\n"
        f"reply: yes {proposal_id} | no {proposal_id}\\n"
        "Smoke test: reply yes to prove Hermes executes Telegram approvals."
    )
    rs = ssh.run(
        host,
        f"python3 {SEND_HELPER_REMOTE} {chat} {proactive} {proposal_msg!r}",
        ssh_key=key,
        timeout=30,
    )
    if rs.returncode != 0:
        ansi.fail(f"could not post smoke proposal to Proactive Nudges: {(rs.stderr or rs.stdout)[:300]}")
        state.mark_phase(PHASE, "blocked", blocker="Telegram smoke proposal send failed")
        return 1

    ansi.info(f"Open Proactive Nudges and reply exactly: yes {proposal_id}")
    ansi.info(f"Waiting up to {POLL_TIMEOUT_S} seconds for Hermes to execute the proposal…")

    proposal = {}
    deadline = time.time() + POLL_TIMEOUT_S
    while time.time() < deadline:
        sr = ssh.run(host, f"{VENV_PY} /tmp/_hp_smoke_status.py {proposal_id}", ssh_key=key, timeout=20)
        if sr.returncode == 0:
            try:
                proposal = json.loads((sr.stdout.strip().splitlines() or ["{}"])[-1])
            except json.JSONDecodeError:
                proposal = {}
            if proposal.get("status") in ("resolved", "rejected", "errored"):
                break
        time.sleep(POLL_INTERVAL_S)

    if proposal.get("status") != "resolved":
        ansi.fail(f"proposal {proposal_id} did not resolve through Telegram. latest: {proposal}")
        ssh.run(host, f"{VENV_PY} /tmp/_hp_smoke_abort.py {proposal_id}", ssh_key=key, timeout=30)
        state.mark_phase(PHASE, "blocked", blocker="Telegram approval loop did not resolve smoke proposal")
        return 1

    event_id = (proposal.get("result") or {}).get("event_id")
    if not event_id:
        ansi.fail(f"proposal resolved without event_id: {proposal}")
        state.mark_phase(PHASE, "blocked", blocker="smoke proposal resolved without calendar event id")
        return 1

    ansi.ok(f"Telegram approval created calendar event {event_id}; deleting…")
    rc = ssh.run(host, f"{VENV_PY} /tmp/_hp_smoke_cleanup.py {event_id}", ssh_key=key, timeout=30)
    if rc.returncode != 0:
        ansi.warn(f"cleanup of test event failed (event will linger): {rc.stderr[:300]}")

    # Receipt to Daily Briefs via the robust helper.
    msg = ("hermes-proactive setup complete. Watchers are live, and the Telegram "
           "yes <id> approval loop created a real calendar event.")
    rs = ssh.run(host,
                 f"python3 {SEND_HELPER_REMOTE} {chat} {daily} {msg!r}",
                 ssh_key=key, timeout=30)
    if rs.returncode != 0:
        ansi.warn(f"receipt send failed: {(rs.stderr or rs.stdout)[:300]}")
        ansi.info("Setup is still complete; manually send a confirmation if you want.")
    else:
        ansi.ok("receipt posted to Daily Briefs")

    state.mark_phase(PHASE, "complete")
    ansi.ok("Phase J complete — full setup verified end-to-end")
    return 0


if __name__ == "__main__":
    sys.exit(run())
