#!/usr/bin/env python3
"""Phase D — Mac iMessage bridge install.

Copies bridge/ into ~/.hermes-proactive/bridge/, renders the launchd plist
with the user's home + bridge path, loads it, and verifies one push lands
in /root/.hermes/inbox/imessage.json.
"""

from __future__ import annotations

import getpass
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
from lib import ansi, state, ssh  # type: ignore

PHASE = "d_imessage"

SKILL_DIR = Path(__file__).resolve().parent.parent
SRC_BRIDGE = SKILL_DIR / "bridge"
DEST_BRIDGE = Path.home() / ".hermes-proactive" / "bridge"
PLIST_NAME_TEMPLATE = "com.{user}.hermes-push.plist"
LAUNCH_AGENTS = Path.home() / "Library" / "LaunchAgents"
LOGS_DIR = Path.home() / "Library" / "Logs" / "HermesProactive"


def _install_bridge_files() -> bool:
    DEST_BRIDGE.mkdir(parents=True, exist_ok=True)
    for name in ("export_imessage.py", "push_to_hermes.sh", "run_once.sh"):
        src = SRC_BRIDGE / name
        if not src.exists():
            ansi.fail(f"missing source: {src}")
            return False
        shutil.copy2(src, DEST_BRIDGE / name)
        if name.endswith(".sh") or name.endswith(".py"):
            os.chmod(DEST_BRIDGE / name, 0o700)
    ansi.ok(f"bridge files installed to {DEST_BRIDGE}")
    return True


def _render_plist(host: str, ssh_key: str) -> Path:
    user = getpass.getuser()
    template = (SRC_BRIDGE / "com.USER.hermes-push.plist.template").read_text()
    rendered = (
        template
        .replace("{{USER}}", user)
        .replace("{{HOME}}", str(Path.home()))
        .replace("{{BRIDGE_DIR}}", str(DEST_BRIDGE))
        .replace("{{LOGS_DIR}}", str(LOGS_DIR))
        .replace("{{VPS_HOST}}", host)
        .replace("{{SSH_KEY}}", str(Path(ssh_key).expanduser()))
    )
    plist_path = LAUNCH_AGENTS / PLIST_NAME_TEMPLATE.format(user=user)
    LAUNCH_AGENTS.mkdir(parents=True, exist_ok=True)
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    plist_path.write_text(rendered)
    os.chmod(plist_path, 0o644)
    return plist_path


def _load_launchd(plist: Path) -> bool:
    label = plist.stem
    subprocess.run(["launchctl", "unload", str(plist)], capture_output=True, text=True)
    r = subprocess.run(["launchctl", "load", str(plist)], capture_output=True, text=True)
    if r.returncode != 0:
        ansi.fail(f"launchctl load failed: {r.stderr or r.stdout}")
        return False
    ansi.ok(f"launchd loaded: {label}")
    return True


def _trigger_push() -> bool:
    """Run the bridge once synchronously."""
    r = subprocess.run([str(DEST_BRIDGE / "run_once.sh")], capture_output=True, text=True, timeout=180)
    if r.returncode not in (0, 2):  # 2 = partial success in bridge convention
        ansi.fail(f"bridge run failed (exit {r.returncode}): {r.stderr[:400]}")
        return False
    ansi.ok("bridge ran once successfully")
    return True


def _verify_push(host: str, key: str) -> bool:
    r = ssh.run(host, "stat -c '%Y' /root/.hermes/inbox/imessage.json 2>/dev/null || echo 0",
                ssh_key=key, timeout=15)
    try:
        mtime = int(r.stdout.strip())
    except ValueError:
        mtime = 0
    if mtime == 0:
        ansi.fail("/root/.hermes/inbox/imessage.json missing on VPS")
        return False
    age = int(time.time()) - mtime
    if age > 300:
        ansi.warn(f"imessage.json is {age}s old; bridge may not have pushed yet")
        return False
    ansi.ok(f"imessage.json fresh on VPS ({age}s old)")
    return True


def run() -> int:
    if state.is_complete(PHASE):
        ansi.ok(f"phase {PHASE} already complete")
        return 0

    state.mark_phase(PHASE, "in_progress")
    ansi.header("Phase D — Mac iMessage bridge")

    data = state.read()
    host = data.get("vps", {}).get("host")
    key = data.get("vps", {}).get("ssh_key")
    if not host or not key:
        state.mark_phase(PHASE, "blocked", blocker="VPS not configured (phase A)")
        return 1

    if not _install_bridge_files():
        state.mark_phase(PHASE, "blocked", blocker="bridge file copy failed")
        return 1

    plist = _render_plist(host, key)
    ansi.ok(f"plist rendered: {plist}")
    if not _load_launchd(plist):
        state.mark_phase(PHASE, "blocked", blocker="launchctl load failed")
        return 1

    if not _trigger_push():
        state.mark_phase(PHASE, "blocked", blocker="initial push failed; check ~/Library/Logs/HermesProactive/")
        return 1

    if not _verify_push(host, key):
        state.mark_phase(PHASE, "blocked", blocker="VPS did not receive iMessage push")
        return 1

    state.mark_phase(PHASE, "complete")
    ansi.ok("phase D complete")
    return 0


if __name__ == "__main__":
    sys.exit(run())
