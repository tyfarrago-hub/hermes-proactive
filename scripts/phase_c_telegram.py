#!/usr/bin/env python3
"""Phase C — Telegram bot.

Walks the user through BotFather, captures bot token + username, attaches
the bot to Hermes via `hermes setup --add-platform telegram`. Idempotent.
"""

from __future__ import annotations

import getpass
import json
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
from lib import ansi, state, ssh  # type: ignore

PHASE = "c_telegram"


def _validate_token(token: str) -> tuple[bool, dict]:
    """Call Telegram getMe; return (ok, bot_info)."""
    url = f"https://api.telegram.org/bot{token}/getMe"
    try:
        with urllib.request.urlopen(url, timeout=15) as resp:
            data = json.loads(resp.read())
        return data.get("ok", False), data.get("result", {})
    except Exception as exc:
        return False, {"error": str(exc)}


def _capture_token() -> str | None:
    ansi.info("Open https://t.me/BotFather in Telegram and run /newbot")
    ansi.info("BotFather will ask for a name (e.g. 'My Hermes') then a username (e.g. myhermesbot).")
    ansi.info("Paste the token (looks like 1234:ABC…) below. Empty to abort.")
    try:
        token = getpass.getpass("  bot token: ").strip()
    except (EOFError, KeyboardInterrupt):
        return None
    return token or None


def run() -> int:
    if state.is_complete(PHASE):
        ansi.ok(f"phase {PHASE} already complete")
        return 0

    state.mark_phase(PHASE, "in_progress")
    ansi.header("Phase C — Telegram bot")

    data = state.read()
    host = data.get("vps", {}).get("host")
    key = data.get("vps", {}).get("ssh_key")
    bot_user = data.get("telegram", {}).get("bot_username")

    if bot_user:
        ansi.ok(f"existing bot on file: {bot_user}")
    else:
        token = _capture_token()
        if not token:
            state.mark_phase(PHASE, "blocked", blocker="no token entered")
            return 1
        ok, info = _validate_token(token)
        if not ok:
            ansi.fail(f"Telegram rejected the token: {info.get('error', info)}")
            state.mark_phase(PHASE, "blocked", blocker="invalid bot token")
            return 1
        bot_user = "@" + info.get("username", "unknown_bot")
        ansi.ok(f"token valid. bot: {bot_user} (id {info.get('id')})")
        state.update({"telegram": {"bot_username": bot_user, "bot_id": info.get("id")}})

        # Stash token on VPS via Hermes's own setup wizard. We don't store it on the Mac.
        ansi.info("Wiring bot into Hermes:")
        ansi.info(f"  ssh -i {key} {host}")
        ansi.info("  hermes setup --add-platform telegram   # paste the token there, NOT here")
        ansi.info("  sudo systemctl restart hermes-gateway")
        ansi.warn("Bot token is NOT saved on the Mac. It only lives in /root/.hermes/.env on the VPS.")

    # Confirm Hermes can reach the bot — easiest path is checking gateway logs for the bot username.
    r = ssh.run(host, "grep -l 'telegram' /root/.hermes/auth.json 2>/dev/null | head -1",
                ssh_key=key, timeout=15)
    if r.stdout.strip():
        ansi.ok("Hermes auth.json mentions telegram (bot wired)")
        state.mark_phase(PHASE, "complete")
        return 0

    ansi.warn("Hermes doesn't show a Telegram platform yet.")
    ansi.info("Re-run this phase after `hermes setup --add-platform telegram` on the VPS.")
    state.mark_phase(PHASE, "blocked", blocker="hermes setup --add-platform telegram not yet run")
    return 1


if __name__ == "__main__":
    sys.exit(run())
