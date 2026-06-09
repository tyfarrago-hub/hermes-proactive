#!/usr/bin/env python3
"""Phase E — Telegram supergroup with topics.

Necessarily human-in-the-loop because Telegram bots can't create groups.

Critical: Hermes's gateway already polls getUpdates on the same bot token.
If we poll concurrently, Telegram routes each update to whichever poller
asks first, so we'd see nothing. Solution: stop the gateway, have the user
send marker messages AFTER, poll until found, then restart.
"""

from __future__ import annotations

import getpass
import json
import secrets
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
from lib import ansi, state, ssh  # type: ignore

PHASE = "e_supergroup"

POLL_TIMEOUT_S = 180   # how long to wait for both marker messages
POLL_INTERVAL = 3      # seconds between getUpdates calls


def _get_token() -> str | None:
    ansi.info("Telegram bot token (from BotFather, same one you used in phase C):")
    try:
        return getpass.getpass("  token: ").strip() or None
    except (EOFError, KeyboardInterrupt):
        return None


def _get_updates(token: str, offset: int) -> tuple[list[dict], int]:
    """Long-poll getUpdates. Returns (updates, max_update_id_seen)."""
    url = f"https://api.telegram.org/bot{token}/getUpdates?offset={offset}&timeout=2"
    try:
        with urllib.request.urlopen(url, timeout=15) as resp:
            data = json.loads(resp.read())
    except Exception as exc:
        ansi.warn(f"getUpdates failed: {exc}")
        return [], offset
    if not data.get("ok"):
        ansi.warn(f"getUpdates not ok: {data}")
        return [], offset
    updates = data.get("result", []) or []
    max_id = max((u.get("update_id", 0) for u in updates), default=offset - 1)
    return updates, max_id + 1


def _stop_gateway(host: str, key: str) -> bool:
    """Stop hermes-gateway so we own getUpdates. Idempotent — silent if absent."""
    r = ssh.run(host, "systemctl stop hermes-gateway 2>&1 || true", ssh_key=key, timeout=15)
    return r.returncode == 0


def _start_gateway(host: str, key: str) -> bool:
    r = ssh.run(host, "systemctl start hermes-gateway 2>&1 || true", ssh_key=key, timeout=15)
    return r.returncode == 0


def _walk_user_through_creation(bot_username: str) -> None:
    ansi.header("Phase E.1 — Create the supergroup (manual, ~3 min)")
    print(f"""
  1. Open Telegram. Tap the new-message pencil → New Group.
  2. Add yourself only first. Name it 'Hermes Ops'. Tap Create.
  3. Open group settings (tap the title) → Edit.
  4. Group Type: Private.
  5. Toggle Topics ON. Display as Tabs or List, your call.
  6. Back to chat. Top-right menu (…) → Create Topic. Name it: Dashboard
  7. Same menu → Create Topic. Name it: Decisions
  8. Group settings → Administrators → Add Admin → search for {bot_username}.
  9. Grant the bot at minimum: Send Messages + Manage Topics permissions. Save.

   Press Enter when those 9 steps are done. (Do NOT send any messages yet.)
""")


def _walk_user_through_markers(bot_username: str, dashboard_marker: str, decisions_marker: str) -> None:
    ansi.header("Phase E.2 — Mark each topic (manual, ~1 min)")
    print(f"""
  Send these EXACT messages, one per topic:

  In Dashboard topic:
      {bot_username} {dashboard_marker}

  In Decisions topic:
      {bot_username} {decisions_marker}

  Mention the bot. The unique tokens above tell us which thread is which.
  After both are sent, this script will pick them up automatically.
""")


def _scan_until_found(token: str, dashboard_marker: str, decisions_marker: str
                      ) -> tuple[int | None, int | None, int | None]:
    chat_id = None
    dashboard_thread = None
    decisions_thread = None
    offset = 0
    deadline = time.time() + POLL_TIMEOUT_S

    while time.time() < deadline and not (chat_id and dashboard_thread and decisions_thread):
        updates, offset = _get_updates(token, offset)
        for upd in updates:
            msg = upd.get("message") or upd.get("edited_message") or {}
            chat = msg.get("chat", {}) or {}
            if chat.get("type") != "supergroup":
                continue
            text = msg.get("text") or ""
            thread = msg.get("message_thread_id")
            if dashboard_marker in text and thread:
                chat_id = chat.get("id")
                dashboard_thread = thread
            if decisions_marker in text and thread:
                chat_id = chat.get("id")
                decisions_thread = thread
        if not (chat_id and dashboard_thread and decisions_thread):
            time.sleep(POLL_INTERVAL)

    return chat_id, dashboard_thread, decisions_thread


def run() -> int:
    if state.is_complete(PHASE):
        ansi.ok(f"phase {PHASE} already complete")
        return 0

    state.mark_phase(PHASE, "in_progress")
    ansi.header("Phase E — Telegram supergroup")

    data = state.read()
    bot_username = data.get("telegram", {}).get("bot_username")
    host = data.get("vps", {}).get("host")
    key = data.get("vps", {}).get("ssh_key")
    if not (bot_username and host and key):
        state.mark_phase(PHASE, "blocked", blocker="phase A or C incomplete")
        return 1

    _walk_user_through_creation(bot_username)
    try:
        input()
    except (EOFError, KeyboardInterrupt):
        state.mark_phase(PHASE, "blocked", blocker="user did not complete creation steps")
        return 1

    token = _get_token()
    if not token:
        state.mark_phase(PHASE, "blocked", blocker="no token provided")
        return 1

    # Stop the gateway so it doesn't race us for getUpdates. Restart no
    # matter what at the end via try/finally.
    ansi.info("pausing hermes-gateway on VPS so we can read bot updates…")
    _stop_gateway(host, key)
    # Sleep briefly so any in-flight getUpdates from the gateway finishes.
    time.sleep(2)

    dashboard_marker = f"hp-dashboard-{secrets.token_hex(3)}"
    decisions_marker = f"hp-decisions-{secrets.token_hex(3)}"

    try:
        _walk_user_through_markers(bot_username, dashboard_marker, decisions_marker)
        ansi.info(f"polling Telegram for up to {POLL_TIMEOUT_S} seconds…")
        chat_id, dashboard_thread, decisions_thread = _scan_until_found(token, dashboard_marker, decisions_marker)
    finally:
        ansi.info("restarting hermes-gateway…")
        _start_gateway(host, key)

    if not (chat_id and dashboard_thread and decisions_thread):
        ansi.fail(
            f"timeout waiting for marker messages. "
            f"chat_id={chat_id} dashboard={dashboard_thread} decisions={decisions_thread}"
        )
        ansi.info("Most common cause: bot is not yet admin (cannot read non-mention messages), or messages weren't sent in the named topics. Re-run this phase.")
        state.mark_phase(PHASE, "blocked", blocker="topic thread_ids not discovered within timeout")
        return 1

    state.update({"telegram": {
        "supergroup_chat_id": chat_id,
        "dashboard_thread_id": dashboard_thread,
        "decisions_thread_id": decisions_thread,
    }})
    ansi.ok(f"chat_id={chat_id}  dashboard_thread={dashboard_thread}  decisions_thread={decisions_thread}")
    state.mark_phase(PHASE, "complete")
    return 0


if __name__ == "__main__":
    sys.exit(run())
