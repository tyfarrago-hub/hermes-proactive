#!/usr/bin/env python3
"""Phase B — Hermes Agent install on VPS.

Runs the upstream Nous Research installer if Hermes isn't already present,
then prompts the user to complete `hermes setup` interactively. Idempotent.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
from lib import ansi, state, ssh  # type: ignore

PHASE = "b_vps"

INSTALLER_URL = "https://raw.githubusercontent.com/NousResearch/hermes-agent/main/scripts/install.sh"


def _hermes_installed(host: str, key: str) -> bool:
    r = ssh.run(host, "test -d /root/.hermes/hermes-agent && echo yes || echo no",
                ssh_key=key, timeout=15)
    return r.stdout.strip() == "yes"


def _gateway_running(host: str, key: str) -> bool:
    r = ssh.run(host, "systemctl is-active hermes-gateway 2>/dev/null || echo inactive",
                ssh_key=key, timeout=15)
    return r.stdout.strip() == "active"


def _install_hermes(host: str, key: str) -> bool:
    ansi.info(f"installing Hermes Agent on {host} (this takes 5-10 min)…")
    cmd = f"curl -fsSL {INSTALLER_URL} | bash"
    r = ssh.run(host, cmd, ssh_key=key, timeout=900)
    if r.returncode != 0:
        ansi.fail(f"installer exited {r.returncode}")
        if r.stderr:
            print(r.stderr[:1000])
        return False
    return _hermes_installed(host, key)


def run() -> int:
    if state.is_complete(PHASE):
        ansi.ok(f"phase {PHASE} already complete")
        return 0

    state.mark_phase(PHASE, "in_progress")
    ansi.header("Phase B — Hermes Agent on VPS")

    data = state.read()
    host = data.get("vps", {}).get("host")
    key = data.get("vps", {}).get("ssh_key")
    if not host or not key:
        ansi.fail("VPS host or SSH key missing from state. Run phase A first.")
        state.mark_phase(PHASE, "blocked", blocker="phase A not complete")
        return 1

    if _hermes_installed(host, key):
        ansi.ok("Hermes already installed at /root/.hermes/hermes-agent")
    else:
        if not _install_hermes(host, key):
            state.mark_phase(PHASE, "blocked", blocker="Hermes installer failed; check VPS logs")
            return 1
        ansi.ok("Hermes installed")

    # Setup wizard requires interactive shell. Tell the user to run it.
    if not _gateway_running(host, key):
        ansi.warn("hermes-gateway service is not running yet.")
        ansi.info(f"SSH in and run: ssh -i {key} {host}")
        ansi.info("then: hermes login --provider openai-codex   # primary brain: OpenAI Codex gpt-5.5 (OAuth), set model openai-codex/gpt-5.5")
        ansi.info("then: sudo systemctl enable --now hermes-gateway")
        ansi.info("Re-run this phase when the gateway is active.")
        state.mark_phase(PHASE, "blocked", blocker="hermes-gateway service not active; complete `hermes setup` and start it")
        return 1

    ansi.ok("hermes-gateway service is active")
    state.mark_phase(PHASE, "complete")
    return 0


if __name__ == "__main__":
    sys.exit(run())
