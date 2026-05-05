#!/usr/bin/env python3
"""Tiny helper that runs ON the VPS to send a Telegram message via the
configured Hermes bot token. Used by phase_j_smoke for the setup-complete
receipt. Robust env parsing — handles quoted, unquoted, and `export X=...`
forms.

Usage on VPS:
    python3 _vps_send_telegram.py <chat_id> <thread_id_or_-> <text...>
"""

from __future__ import annotations

import json
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

ENV_PATH = Path("/root/.hermes/.env")


def _read_token() -> str | None:
    if not ENV_PATH.exists():
        return None
    raw = ENV_PATH.read_text()
    # Match optional `export `, optional whitespace, the var name, =, optional quotes.
    m = re.search(
        r"^\s*(?:export\s+)?TELEGRAM_BOT_TOKEN\s*=\s*['\"]?([^'\"\r\n]+)['\"]?\s*$",
        raw, re.MULTILINE,
    )
    return m.group(1).strip() if m else None


def main() -> int:
    if len(sys.argv) < 4:
        print("usage: _vps_send_telegram.py <chat_id> <thread_id|-> <text>", file=sys.stderr)
        return 2
    chat_id = sys.argv[1]
    thread_arg = sys.argv[2]
    text = " ".join(sys.argv[3:])

    token = _read_token()
    if not token:
        print("TELEGRAM_BOT_TOKEN not found in /root/.hermes/.env", file=sys.stderr)
        return 3

    payload: dict[str, str] = {"chat_id": chat_id, "text": text}
    if thread_arg and thread_arg != "-":
        payload["message_thread_id"] = thread_arg

    data = urllib.parse.urlencode(payload).encode()
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        with urllib.request.urlopen(url, data=data, timeout=15) as resp:
            body = json.loads(resp.read())
    except Exception as exc:
        print(f"send failed: {exc}", file=sys.stderr)
        return 4

    if not body.get("ok"):
        print(f"telegram api rejected: {body}", file=sys.stderr)
        return 5
    print(body.get("result", {}).get("message_id", "sent"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
