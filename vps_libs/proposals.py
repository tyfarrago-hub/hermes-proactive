"""Proposal store for Hermes proactive nudges.

A proposal is a pending action Hermes drafted that Ty hasn't approved yet.
Stored at /root/.hermes/proposals.json. Resolved entries kept in the same file
for audit. Append-only-ish; updates only flip 'status' and add 'resolved_at' /
'result' / 'error'.

Schema:
{
  "next_seq": int,
  "proposals": [
    {
      "id": "a",            # base36 of seq, 1-3 chars
      "type": "calendar.add" | "gmail.send",
      "status": "pending" | "resolved" | "rejected" | "errored",
      "created_at": iso,
      "source": "imessage" | "gmail",
      ...type-specific payload...
    }
  ]
}
"""

from __future__ import annotations

import datetime as _dt
import fcntl
import json
from pathlib import Path
from typing import Any

PROPOSALS_PATH = Path("/root/.hermes/proposals.json")


def _now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat()


def _to_base36(n: int) -> str:
    if n == 0:
        return "0"
    chars = "0123456789abcdefghijklmnopqrstuvwxyz"
    out = []
    while n:
        n, r = divmod(n, 36)
        out.append(chars[r])
    return "".join(reversed(out))


def _read() -> dict[str, Any]:
    if not PROPOSALS_PATH.exists():
        return {"next_seq": 1, "proposals": []}
    return json.loads(PROPOSALS_PATH.read_text())


def _write(data: dict[str, Any]) -> None:
    PROPOSALS_PATH.write_text(json.dumps(data, indent=2))
    PROPOSALS_PATH.chmod(0o600)


def _with_lock(fn):
    """Open proposals.json with exclusive lock for the duration of fn(data)."""
    PROPOSALS_PATH.touch(exist_ok=True)
    with PROPOSALS_PATH.open("r+") as f:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        try:
            try:
                data = json.loads(f.read() or "{}")
            except json.JSONDecodeError:
                data = {}
            data.setdefault("next_seq", 1)
            data.setdefault("proposals", [])
            result = fn(data)
            f.seek(0)
            f.truncate()
            f.write(json.dumps(data, indent=2))
            return result
        finally:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)


def mint(type_: str, source: str, **payload: Any) -> dict[str, Any]:
    """Mint a new pending proposal. Returns the full proposal entry including id."""

    def _mint(data):
        seq = data["next_seq"]
        data["next_seq"] = seq + 1
        entry = {
            "id": _to_base36(seq),
            "type": type_,
            "status": "pending",
            "created_at": _now_iso(),
            "source": source,
            **payload,
        }
        data["proposals"].append(entry)
        return entry

    return _with_lock(_mint)


def get(proposal_id: str) -> dict[str, Any] | None:
    data = _read()
    for p in data["proposals"]:
        if p["id"] == proposal_id:
            return p
    return None


def update_status(
    proposal_id: str, status: str,
    result: Any = None, error: str | None = None, edited: dict | None = None,
) -> dict[str, Any] | None:
    """Mark a proposal resolved/rejected/errored. Returns the updated entry."""

    def _update(data):
        for p in data["proposals"]:
            if p["id"] == proposal_id:
                p["status"] = status
                p["resolved_at"] = _now_iso()
                if result is not None:
                    p["result"] = result
                if error:
                    p["error"] = error
                if edited:
                    p["edited"] = edited
                return p
        return None

    return _with_lock(_update)


def patch(proposal_id: str, **field_updates: Any) -> dict[str, Any] | None:
    """Apply arbitrary field updates to a proposal record. Returns updated entry."""

    def _patch(data):
        for p in data["proposals"]:
            if p["id"] == proposal_id:
                p.update(field_updates)
                return p
        return None

    return _with_lock(_patch)


def list_pending() -> list[dict[str, Any]]:
    data = _read()
    return [p for p in data["proposals"] if p.get("status") == "pending"]


def has_pending_for(source_id: str) -> bool:
    """Avoid duplicate proposals for the same source message/email."""
    data = _read()
    return any(
        p.get("status") in ("pending", "resolved")
        and (p.get("source_msg_id") == source_id or p.get("thread_id") == source_id)
        for p in data["proposals"]
    )
