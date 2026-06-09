#!/usr/bin/env python3
"""Phase H — Libs + watcher cron jobs on VPS.

SCPs the four lib files into /root/.hermes/lib/, pip-installs Google libs
into Hermes's venv, runs a smoke test, and creates the two cron jobs
(imessage-scheduling-watcher, gmail-reply-watcher) using the prompts in
prompts/.
"""

from __future__ import annotations

import json
import tempfile
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
from lib import ansi, state, ssh  # type: ignore

PHASE = "h_libs"

SKILL_DIR = Path(__file__).resolve().parent.parent
VPS_LIBS_DIR = SKILL_DIR / "vps_libs"
PROMPTS_DIR = SKILL_DIR / "prompts"

VENV_PY = "/root/.hermes/hermes-agent/venv/bin/python"
VENV_PIP = "/root/.hermes/hermes-agent/venv/bin/pip3"
HERMES_CLI = f"{VENV_PY} -m hermes_cli.main"


def _scp_libs(host: str, key: str) -> bool:
    ssh.run(host, "mkdir -p /root/.hermes/lib && mkdir -p /root/.hermes/agent/state", ssh_key=key, timeout=15)
    for name in ("google_workspace.py", "proposals.py", "proposal_executor.py", "gmail_candidates.py"):
        src = VPS_LIBS_DIR / name
        if not src.exists():
            ansi.fail(f"missing source: {src}")
            return False
        r = ssh.scp(src, host, f"/root/.hermes/lib/{name}", ssh_key=key)
        if r.returncode != 0:
            ansi.fail(f"scp {name} failed: {r.stderr}")
            return False
    ansi.ok("4 lib files copied to /root/.hermes/lib/")
    return True


def _pip_install(host: str, key: str) -> bool:
    cmd = f"{VENV_PIP} install -q google-auth google-api-python-client google-auth-oauthlib"
    r = ssh.run(host, cmd, ssh_key=key, timeout=180)
    if r.returncode != 0:
        ansi.fail(f"pip install failed: {r.stderr}")
        return False
    ansi.ok("Google libs installed in Hermes venv")
    return True


def _init_state_files(host: str, key: str) -> bool:
    cmd = (
        '[ -f /root/.hermes/proposals.json ] || '
        'echo \'{"proposals": [], "next_seq": 1}\' > /root/.hermes/proposals.json && '
        '[ -f /root/.hermes/agent/state/imessage-scheduling-watcher.json ] || '
        'echo \'{"last_processed_id": null}\' > /root/.hermes/agent/state/imessage-scheduling-watcher.json && '
        'chmod 600 /root/.hermes/proposals.json'
    )
    r = ssh.run(host, cmd, ssh_key=key, timeout=15)
    if r.returncode != 0:
        ansi.fail(f"state init failed: {r.stderr}")
        return False
    ansi.ok("proposals.json + watcher state initialized")
    return True


def _smoke_test(host: str, key: str) -> bool:
    cmd = f"{VENV_PY} /root/.hermes/lib/google_workspace.py"
    r = ssh.run(host, cmd, ssh_key=key, timeout=60)
    try:
        result = json.loads(r.stdout)
    except json.JSONDecodeError:
        ansi.fail(f"smoke test produced invalid output: {r.stdout[:300]}")
        return False
    if not (result.get("gmail_ok") and result.get("calendar_ok")):
        ansi.fail(f"smoke test failed: {result}")
        return False
    ansi.ok(f"gmail + calendar reachable: {result.get('sample_thread')!r} / {result.get('sample_event')!r}")
    return True


def _create_cron(host: str, key: str, name: str, schedule: str, prompt_file: Path, deliver: str) -> bool:
    """Create a Hermes cron job with full shell safety.

    SCPs the prompt and a tiny Python launcher to the VPS, then runs the
    launcher as a file. The prompt and cron args never pass through a shell
    tokenizer.
    """
    if not prompt_file.exists():
        ansi.fail(f"missing prompt file: {prompt_file}")
        return False
    remote_prompt = f"/tmp/hermes_prompt_{name}.txt"
    remote_launcher = f"/tmp/hermes_create_cron_{name}.py"
    r1 = ssh.scp(prompt_file, host, remote_prompt, ssh_key=key)
    if r1.returncode != 0:
        ansi.fail(f"scp {prompt_file.name}: {r1.stderr}")
        return False

    py_src = f"""#!/usr/bin/env python3
import subprocess
import sys

prompt = open({remote_prompt!r}).read()
r = subprocess.run(
    [{VENV_PY!r}, "-m", "hermes_cli.main", "cron", "create",
     {schedule!r}, prompt, "--name", {name!r}, "--deliver", {deliver!r}],
    capture_output=True,
    text=True,
    cwd="/root/.hermes/hermes-agent",
)
sys.stdout.write(r.stdout)
sys.stderr.write(r.stderr)
sys.exit(r.returncode)
"""
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as f:
        f.write(py_src)
        local_launcher = Path(f.name)

    r_launcher = ssh.scp(local_launcher, host, remote_launcher, ssh_key=key)
    try:
        local_launcher.unlink(missing_ok=True)
    except OSError:
        pass
    if r_launcher.returncode != 0:
        ansi.fail(f"scp cron launcher failed for {name}: {r_launcher.stderr}")
        return False

    r2 = ssh.run(
        host,
        f"{VENV_PY} {remote_launcher}; rc=$?; rm -f {remote_launcher} {remote_prompt}; exit $rc",
        ssh_key=key,
        timeout=45,
    )
    combined = (r2.stdout + r2.stderr).lower()
    if "created job" in combined or "already exists" in combined:
        ansi.ok(f"cron job: {name}")
        return True
    ansi.fail(f"cron create failed for {name}: {(r2.stderr or r2.stdout)[:600]}")
    return False


def run() -> int:
    if state.is_complete(PHASE):
        ansi.ok(f"phase {PHASE} already complete")
        return 0

    state.mark_phase(PHASE, "in_progress")
    ansi.header("Phase H — Libs + watcher crons")

    data = state.read()
    host = data.get("vps", {}).get("host")
    key = data.get("vps", {}).get("ssh_key")
    tg = data.get("telegram", {})
    chat = tg.get("supergroup_chat_id")
    decisions = tg.get("decisions_thread_id")

    if not all([host, key, chat, decisions]):
        state.mark_phase(PHASE, "blocked", blocker="phase E or A incomplete")
        return 1

    decisions_target = f"telegram:{chat}:{decisions}"

    if not _scp_libs(host, key):
        state.mark_phase(PHASE, "blocked", blocker="lib SCP failed")
        return 1
    if not _pip_install(host, key):
        state.mark_phase(PHASE, "blocked", blocker="pip install failed on VPS")
        return 1
    if not _init_state_files(host, key):
        state.mark_phase(PHASE, "blocked", blocker="state file init failed")
        return 1
    if not _smoke_test(host, key):
        state.mark_phase(PHASE, "blocked", blocker="google_workspace smoke test failed")
        return 1

    ok1 = _create_cron(host, key, "imessage-scheduling-watcher",
                       "* * * * *",
                       PROMPTS_DIR / "imessage_scheduling_watcher.txt",
                       decisions_target)
    ok2 = _create_cron(host, key, "gmail-reply-watcher",
                       "*/30 * * * *",
                       PROMPTS_DIR / "gmail_reply_watcher.txt",
                       decisions_target)
    if not (ok1 and ok2):
        state.mark_phase(PHASE, "blocked", blocker="watcher cron creation failed")
        return 1

    state.mark_phase(PHASE, "complete")
    ansi.ok("phase H complete")
    return 0


if __name__ == "__main__":
    sys.exit(run())
