#!/usr/bin/env python3
"""Export recent iMessages from chat.db to JSON for Hermes ingestion.

Schema v1 (matches what Hermes /root/.hermes/inbox/imessage.json expects):
{
  "schema_version": 1,
  "generated_at": iso,
  "source": "hermes-proactive bridge",
  "host": <hostname>,
  "window_hours": 6,
  "count": int,
  "messages": [{id, ts, from_me, contact, chat, text, service, chat_id, handle, attachments}],
  "unanswered": [],   # placeholder, watcher derives this itself
  "chats": [],
  "health": {ok: true, duration_ms: int, errors: [], warnings: []}
}

Reads chat.db read-only with full disk access. Filters obvious spam.
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import re
import socket
import sqlite3
import sys
import time
from pathlib import Path

CHAT_DB = Path.home() / "Library/Messages/chat.db"
APPLE_EPOCH_OFFSET = 978307200  # seconds between unix epoch and apple cocoa epoch

WINDOW_HOURS = int(os.environ.get("HERMES_BRIDGE_WINDOW_HOURS", "6"))
MAX_MESSAGES = int(os.environ.get("HERMES_BRIDGE_MAX_MESSAGES", "2000"))

# Modern iMessage rows store rich text in attributedBody (NSKeyedArchiver)
# and leave message.text NULL. We don't fully decode the archive — we
# scan for printable runs and drop NSKeyedArchiver bookkeeping tokens.
_NS_TOKEN_RE = re.compile(
    r"NS[A-Z][a-zA-Z]+|kIM[A-Z][a-zA-Z]+|__kIM|streamtyped|NSKeyedArchiver|"
    r"NSDictionary|NSArray|NSString|NSAttributedString|NSMutableString|"
    r"\$null|\$class|\$archiver|\$version|\$top|\$objects"
)


def _extract_attributed_text(blob: bytes) -> str | None:
    """Pull readable text out of an NSAttributedString blob.

    Mirror of the chat_db.py logic in carbon-voiceprint, kept inline so the
    bridge stays self-contained on a user's Mac after install.
    """
    if not blob:
        return None
    try:
        decoded = blob.decode("utf-8", errors="ignore")
        segments = re.findall(r"[\x20-\x7e]{4,}", decoded)
        cleaned: list[str] = []
        for s in segments:
            s = s.strip()
            if _NS_TOKEN_RE.search(s):
                continue
            s = re.sub(r"^[+\x00-\x1f]+|[iI\x00-\x1f]+$", "", s).strip()
            if re.fullmatch(r"[a-z]{1,3}(\s+[a-z]+)*", s):
                continue
            if s and len(s) >= 2:
                cleaned.append(s)
        if cleaned:
            return max(cleaned, key=len)
    except Exception:
        pass
    return None


def _apple_to_iso(apple_ts_ns: int) -> str:
    seconds = apple_ts_ns / 1_000_000_000 + APPLE_EPOCH_OFFSET
    return _dt.datetime.fromtimestamp(seconds, tz=_dt.timezone.utc).astimezone().isoformat()


def _looks_spammy(text: str, handle: str) -> bool:
    if not text:
        return False
    lower = text.lower()
    if any(k in lower for k in ("verification code", "your code is", "2fa", "one-time code", "do not share")):
        return True
    if any(k in lower for k in ("unsubscribe", "msg&data rates", "stop to opt out", "reply stop")):
        return True
    return False


def _query(con: sqlite3.Connection, since_ts_ns: int) -> list[dict]:
    sql = """
    SELECT
      m.ROWID                              AS rowid,
      m.guid                               AS guid,
      m.date                               AS apple_date,
      m.is_from_me                         AS from_me,
      m.text                               AS text,
      m.attributedBody                     AS attributed_body,
      m.service                            AS service,
      h.id                                 AS handle,
      c.chat_identifier                    AS chat_id,
      c.display_name                       AS chat_name
    FROM message m
    LEFT JOIN handle h ON m.handle_id = h.ROWID
    LEFT JOIN chat_message_join cmj ON m.ROWID = cmj.message_id
    LEFT JOIN chat c ON cmj.chat_id = c.ROWID
    WHERE m.date > ?
      AND m.associated_message_type = 0   -- skip tapbacks
    ORDER BY m.date ASC
    LIMIT ?
    """
    rows = con.execute(sql, (since_ts_ns, MAX_MESSAGES)).fetchall()
    out = []
    for row in rows:
        text = row["text"]
        if not text:
            text = _extract_attributed_text(row["attributed_body"]) or ""
        handle = row["handle"] or ""
        if _looks_spammy(text, handle):
            continue
        out.append({
            "id": f"msg_{row['rowid']}",
            "ts": _apple_to_iso(row["apple_date"]),
            "from_me": bool(row["from_me"]),
            "contact": row["chat_name"] or handle or "(unknown)",
            "chat": row["chat_name"] or handle or "(unknown)",
            "text": text,
            "service": row["service"] or "iMessage",
            "chat_id": row["chat_id"] or handle or "",
            "handle": handle,
            "attachments": [],
        })
    return out


def main(out_path: str) -> int:
    if not CHAT_DB.exists():
        print(f"chat.db not found at {CHAT_DB}", file=sys.stderr)
        return 1

    started = time.time()
    errors: list[str] = []
    warnings: list[str] = []
    messages: list[dict] = []

    since = (_dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(hours=WINDOW_HOURS)).timestamp()
    since_apple_ns = int((since - APPLE_EPOCH_OFFSET) * 1_000_000_000)

    try:
        con = sqlite3.connect(f"file:{CHAT_DB}?mode=ro", uri=True)
        con.row_factory = sqlite3.Row
        messages = _query(con, since_apple_ns)
        con.close()
    except sqlite3.OperationalError as exc:
        # Most likely Full Disk Access not granted.
        errors.append(f"chat.db read failed (FDA?): {exc}")
        return 2

    duration_ms = int((time.time() - started) * 1000)

    payload = {
        "schema_version": 1,
        "generated_at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "source": "hermes-proactive bridge",
        "host": socket.gethostname(),
        "window_hours": WINDOW_HOURS,
        "count": len(messages),
        "messages": messages,
        "unanswered": [],
        "chats": [],
        "health": {"ok": not errors, "duration_ms": duration_ms,
                   "errors": errors, "warnings": warnings},
    }

    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    Path(out_path).write_text(json.dumps(payload))
    return 0 if not errors else 2


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "/tmp/imessage.json"
    sys.exit(main(out))
