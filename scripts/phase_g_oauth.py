#!/usr/bin/env python3
"""Phase G — Google Workspace OAuth.

Walks the user through Google Cloud Console (project + APIs + OAuth client),
then runs InstalledAppFlow.run_local_server to get a refresh token. SCPs
the resulting token + client secret to the VPS.

Browser steps are necessarily user-driven (Google consent click). The skill
opens each URL via `open` so the user just clicks the buttons.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
from lib import ansi, state, ssh  # type: ignore

PHASE = "g_oauth"

ROOT = Path.home() / ".hermes-proactive"
CLIENT_SECRET = ROOT / "client_secret.json"
TOKEN_PATH = ROOT / "token.json"

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/userinfo.email",
    "openid",
]

VENV_DIR = ROOT / "venv"


def _ensure_venv() -> Path:
    if not (VENV_DIR / "bin" / "python").exists():
        ansi.info("creating venv for Google libs…")
        subprocess.run([sys.executable, "-m", "venv", str(VENV_DIR)], check=True)
    pip = VENV_DIR / "bin" / "pip"
    subprocess.run([str(pip), "install", "-q", "google-auth-oauthlib", "google-auth", "google-api-python-client"], check=True)
    return VENV_DIR / "bin" / "python"


def _walk_through_console() -> None:
    ansi.header("Manual steps in Google Cloud Console (10 min)")
    print("""
  1. Open https://console.cloud.google.com/projectcreate
     I'll open it for you. Sign in, name the project (e.g. 'hermes'), click Create.
     Wait for the green checkmark before continuing.

  2. https://console.cloud.google.com/apis/library/gmail.googleapis.com
     Make sure the project is selected (top bar). Click Enable.

  3. https://console.cloud.google.com/apis/library/calendar-json.googleapis.com
     Click Enable.

  4. https://console.cloud.google.com/auth/overview
     If asked to configure consent, pick External (or Internal if you have Workspace).
     Add yourself as a test user.

  5. https://console.cloud.google.com/auth/clients
     Click + Create Client. Application type: Desktop app. Name: hermes-workspace.
     Click Create. The next dialog shows your client_id + client_secret ONCE.

  6. Copy or download the JSON. Paste the path or full JSON below.
""")
    for url in (
        "https://console.cloud.google.com/projectcreate",
        "https://console.cloud.google.com/apis/library/gmail.googleapis.com",
        "https://console.cloud.google.com/apis/library/calendar-json.googleapis.com",
        "https://console.cloud.google.com/auth/clients",
    ):
        subprocess.Popen(["open", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _capture_client_secret() -> bool:
    print("Paste path to downloaded client_secret JSON (or paste the JSON directly):")
    try:
        first = input("  > ").strip()
    except (EOFError, KeyboardInterrupt):
        return False
    if first.startswith("{"):
        # Inline JSON
        try:
            data = json.loads(first)
        except json.JSONDecodeError:
            ansi.fail("invalid JSON")
            return False
    elif Path(first).expanduser().exists():
        try:
            data = json.loads(Path(first).expanduser().read_text())
        except json.JSONDecodeError:
            ansi.fail("file is not valid JSON")
            return False
    else:
        ansi.fail("not a JSON blob and not a readable file path")
        return False

    if "installed" not in data and "web" not in data:
        ansi.fail("client_secret JSON missing 'installed' or 'web' key")
        return False

    ROOT.mkdir(parents=True, exist_ok=True)
    CLIENT_SECRET.write_text(json.dumps(data, indent=2))
    os.chmod(CLIENT_SECRET, 0o600)
    ansi.ok(f"saved {CLIENT_SECRET}")
    return True


def _run_oauth_flow(py: Path) -> bool:
    script = f"""
import json, os, sys
from pathlib import Path
from google_auth_oauthlib.flow import InstalledAppFlow
flow = InstalledAppFlow.from_client_secrets_file({str(CLIENT_SECRET)!r}, {SCOPES!r})
creds = flow.run_local_server(port=0, prompt='consent', access_type='offline')
Path({str(TOKEN_PATH)!r}).write_text(creds.to_json())
os.chmod({str(TOKEN_PATH)!r}, 0o600)
payload = json.loads(creds.to_json())
print('refresh_token_present:', bool(payload.get('refresh_token')))
print('scopes:', payload.get('scopes'))
"""
    r = subprocess.run([str(py), "-c", script], capture_output=True, text=True, timeout=300)
    if r.returncode != 0:
        ansi.fail(f"oauth flow failed: {r.stderr[:600]}")
        return False
    print(r.stdout)
    return TOKEN_PATH.exists()


def _scp_to_vps() -> bool:
    data = state.read()
    host = data.get("vps", {}).get("host")
    key = data.get("vps", {}).get("ssh_key")
    if not (host and key):
        ansi.fail("VPS not configured")
        return False
    r1 = ssh.scp(CLIENT_SECRET, host, "/root/.hermes/google_workspace_client_secret.json", ssh_key=key)
    r2 = ssh.scp(TOKEN_PATH, host, "/root/.hermes/google_workspace_token.json", ssh_key=key)
    if r1.returncode != 0 or r2.returncode != 0:
        ansi.fail(f"scp failed: {r1.stderr or r2.stderr}")
        return False
    ssh.run(host, "chmod 600 /root/.hermes/google_workspace_client_secret.json /root/.hermes/google_workspace_token.json",
            ssh_key=key, timeout=10)
    ansi.ok("credentials on VPS at /root/.hermes/google_workspace_*.json")
    return True


def run() -> int:
    if state.is_complete(PHASE):
        ansi.ok(f"phase {PHASE} already complete")
        return 0

    state.mark_phase(PHASE, "in_progress")
    ansi.header("Phase G — Google OAuth")

    if not CLIENT_SECRET.exists():
        _walk_through_console()
        if not _capture_client_secret():
            state.mark_phase(PHASE, "blocked", blocker="client_secret not captured")
            return 1
    else:
        ansi.ok(f"client_secret already present at {CLIENT_SECRET}")

    py = _ensure_venv()
    if not TOKEN_PATH.exists():
        ansi.info("Running OAuth flow — your browser will open for consent. Click Allow.")
        if not _run_oauth_flow(py):
            state.mark_phase(PHASE, "blocked", blocker="OAuth consent flow failed")
            return 1
    else:
        ansi.ok(f"token already present at {TOKEN_PATH}")

    if not _scp_to_vps():
        state.mark_phase(PHASE, "blocked", blocker="SCP to VPS failed")
        return 1

    state.update({"google": {
        "client_secret_path": str(CLIENT_SECRET),
        "token_path": str(TOKEN_PATH),
    }})
    state.mark_phase(PHASE, "complete")
    ansi.ok("phase G complete")
    return 0


if __name__ == "__main__":
    sys.exit(run())
