#!/usr/bin/env python3
"""Phase A — Mac prerequisites.

Verifies macOS, Python, SSH keypair, prompts for VPS host, checks FDA,
writes results to state. Idempotent.
"""

from __future__ import annotations

import platform
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
from lib import ansi, state, ssh  # type: ignore

PHASE = "a_mac_prereqs"


def _check_macos() -> bool:
    if platform.system() != "Darwin":
        ansi.fail(f"hermes-proactive needs macOS for the iMessage bridge; detected {platform.system()}")
        ansi.info("Linux/WSL users: open an issue, we'll consider a Telegram-only mode.")
        return False
    ansi.ok(f"macOS {platform.mac_ver()[0]}")
    return True


def _check_python() -> bool:
    if sys.version_info < (3, 11):
        ansi.fail(f"Python 3.11+ required; have {sys.version_info.major}.{sys.version_info.minor}")
        ansi.info("Install with: brew install python@3.12")
        return False
    ansi.ok(f"Python {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}")
    return True


def _check_ssh_key(state_data: dict) -> str | None:
    key = state_data.get("vps", {}).get("ssh_key", "~/.ssh/id_ed25519")
    pk = Path(key).expanduser()
    if pk.exists():
        ansi.ok(f"SSH key present at {key}")
        return str(pk)
    ansi.warn(f"SSH key missing at {key}; generating ed25519 keypair…")
    try:
        ssh.ensure_keypair(str(pk), comment="hermes-proactive")
        ansi.ok(f"generated {pk}")
        return str(pk)
    except subprocess.CalledProcessError as exc:
        ansi.fail(f"ssh-keygen failed: {exc.stderr or exc.stdout}")
        return None


def _check_fda() -> bool:
    """Probe by attempting to open ~/Library/Messages/chat.db read-only."""
    chat_db = Path.home() / "Library/Messages/chat.db"
    if not chat_db.exists():
        ansi.warn("chat.db not found at ~/Library/Messages/chat.db (iMessage may not be set up)")
        return False
    try:
        with chat_db.open("rb") as f:
            f.read(16)
        ansi.ok("Full Disk Access verified (chat.db readable)")
        return True
    except PermissionError:
        ansi.fail("Full Disk Access NOT granted to your terminal.")
        ansi.info("Open System Settings → Privacy & Security → Full Disk Access.")
        ansi.info("Add Terminal (or your shell host) and toggle on. Quit + reopen terminal after.")
        subprocess.Popen(
            ["open", "x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        return False


def _prompt_vps_host(state_data: dict) -> str | None:
    existing = state_data.get("vps", {}).get("host")
    if existing:
        ansi.ok(f"VPS host on file: {existing}")
        return existing
    ansi.info("Enter your VPS in the form `user@host` or `host` (defaults user=root).")
    ansi.info("If you don't have one yet, see docs/architecture.md for cheap providers.")
    try:
        target = input("  vps: ").strip()
    except EOFError:
        ansi.fail("no vps host entered; rerun this phase when you have one provisioned")
        return None
    if not target:
        return None
    user, host = ssh.parse_user_host(target)
    full = f"{user}@{host}"
    state.update({"vps": {"host": full}})
    ansi.ok(f"saved VPS host: {full}")
    return full


def _check_vps_reachable(host: str, key: str) -> bool:
    if ssh.probe(host, ssh_key=key):
        ansi.ok(f"SSH reachable: {host}")
        return True
    ansi.fail(f"cannot SSH to {host} with key {key}")
    ansi.info(f"  add the public key to the VPS first: ssh-copy-id -i {key}.pub {host}")
    ansi.info("  or copy ~/.ssh/<key>.pub manually into VPS ~/.ssh/authorized_keys")
    return False


def run() -> int:
    state.ensure_dir()
    state_data = state.read()

    if state.is_complete(PHASE):
        ansi.ok(f"phase {PHASE} already complete (run `check_setup.py reset a` to redo).")
        return 0

    state.mark_phase(PHASE, "in_progress")
    ansi.header("Phase A — Mac prerequisites")

    if not _check_macos():
        state.mark_phase(PHASE, "blocked", blocker="not macOS")
        return 1

    if not _check_python():
        state.mark_phase(PHASE, "blocked", blocker="Python < 3.11")
        return 1

    key = _check_ssh_key(state_data)
    if not key:
        state.mark_phase(PHASE, "blocked", blocker="ssh key generation failed")
        return 1
    state.update({"vps": {"ssh_key": key}})

    host = _prompt_vps_host(state.read())
    if not host:
        state.mark_phase(PHASE, "blocked", blocker="VPS host not provided")
        return 1

    if not _check_vps_reachable(host, key):
        state.mark_phase(PHASE, "blocked", blocker="VPS not SSH-reachable; copy key first")
        return 1

    if not _check_fda():
        state.mark_phase(PHASE, "blocked", blocker="Full Disk Access not granted to terminal")
        return 1

    state.mark_phase(PHASE, "complete")
    ansi.ok("Phase A complete")
    return 0


if __name__ == "__main__":
    sys.exit(run())
