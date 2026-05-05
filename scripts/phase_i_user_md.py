#!/usr/bin/env python3
"""Phase I — Append proposal-handler section to /root/.hermes/USER.md.

Reads snippets/user_md_proposal_section.md, templates in chat_id and the two
thread_ids from state, appends to USER.md only if not already present.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
from lib import ansi, state, ssh  # type: ignore

PHASE = "i_user_md"
SKILL_DIR = Path(__file__).resolve().parent.parent
SNIPPET = SKILL_DIR / "snippets" / "user_md_proposal_section.md"
MARKER = "<!-- hermes-proactive:proposal-handler -->"


def run() -> int:
    if state.is_complete(PHASE):
        ansi.ok(f"phase {PHASE} already complete")
        return 0

    state.mark_phase(PHASE, "in_progress")
    ansi.header("Phase I — USER.md proposal handler")

    data = state.read()
    host = data.get("vps", {}).get("host")
    key = data.get("vps", {}).get("ssh_key")
    tg = data.get("telegram", {})
    chat = tg.get("supergroup_chat_id")
    daily = tg.get("daily_thread_id")
    proactive = tg.get("proactive_thread_id")
    if not all([host, key, chat, daily, proactive]):
        state.mark_phase(PHASE, "blocked", blocker="phase E incomplete")
        return 1

    if not SNIPPET.exists():
        state.mark_phase(PHASE, "blocked", blocker=f"snippet missing: {SNIPPET}")
        return 1

    # Idempotency: check if marker already present.
    r = ssh.run(host, f"grep -F '{MARKER}' /root/.hermes/USER.md 2>/dev/null", ssh_key=key, timeout=15)
    if r.returncode == 0 and r.stdout.strip():
        ansi.ok("USER.md already contains proposal-handler section")
        state.mark_phase(PHASE, "complete")
        return 0

    rendered_body = (
        SNIPPET.read_text()
        .replace("{{CHAT_ID}}", str(chat))
        .replace("{{DAILY_THREAD_ID}}", str(daily))
        .replace("{{PROACTIVE_THREAD_ID}}", str(proactive))
    )
    # Build the full block locally with real newlines around the marker
    # then append on the VPS in one shot. Avoids any echo \n quoting trap.
    full_block = f"\n\n{MARKER}\n{rendered_body.rstrip()}\n"

    import tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as f:
        f.write(full_block)
        local = f.name

    remote_tmp = "/tmp/hermes_proposal_section.md"
    scp_r = ssh.scp(local, host, remote_tmp, ssh_key=key)
    if scp_r.returncode != 0:
        ansi.fail(f"scp failed: {scp_r.stderr}")
        state.mark_phase(PHASE, "blocked", blocker="snippet SCP failed")
        return 1

    cat_r = ssh.run(host, f"cat {remote_tmp} >> /root/.hermes/USER.md && rm -f {remote_tmp}",
                    ssh_key=key, timeout=15)
    if cat_r.returncode != 0:
        ansi.fail(f"append failed: {cat_r.stderr}")
        state.mark_phase(PHASE, "blocked", blocker="USER.md append failed")
        return 1

    ansi.ok("appended proposal-handler section to /root/.hermes/USER.md")
    state.mark_phase(PHASE, "complete")
    return 0


if __name__ == "__main__":
    sys.exit(run())
