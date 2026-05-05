"""Execute resolved proposals: actually create the calendar event or send the email.

Used by the proposal-reply handler when Ty replies 'yes <id>'.
Logs every executed action to /root/.hermes/proposal_log.jsonl.
"""

from __future__ import annotations

import datetime as _dt
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent))

import google_workspace as gws
import proposals

LOG_PATH = Path("/root/.hermes/proposal_log.jsonl")


def _audit(entry: dict[str, Any]) -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a") as f:
        f.write(json.dumps({"ts": _dt.datetime.now(_dt.timezone.utc).isoformat(), **entry}) + "\n")


def execute(proposal_id: str, action: str = "yes", edit_value: str | None = None) -> dict[str, Any]:
    """Execute or reject a proposal.

    action: 'yes' (execute as drafted), 'no' (reject), 'edit' (apply edit_value then execute).
    Returns {ok: bool, result|error: ..., proposal: updated_entry}.
    """
    p = proposals.get(proposal_id)
    if not p:
        return {"ok": False, "error": f"no proposal with id {proposal_id!r}"}

    # Allow retry on errored, plus normal pending. Resolved/rejected stay terminal.
    if p.get("status") not in ("pending", "errored"):
        return {"ok": False, "error": f"proposal {proposal_id!r} already {p['status']}"}

    if action == "no":
        updated = proposals.update_status(proposal_id, "rejected")
        _audit({"action": "reject", "proposal_id": proposal_id, "type": p["type"]})
        return {"ok": True, "result": "rejected", "proposal": updated}

    if action == "edit" and edit_value:
        # Persist the edit onto the proposal record itself before sending,
        # so audit later reflects what was actually sent.
        if p["type"] == "calendar.add":
            p = proposals.patch(proposal_id, datetime_iso=edit_value, datetime_human=edit_value)
        elif p["type"] == "gmail.send":
            p = proposals.patch(proposal_id, body=edit_value)

    try:
        if p["type"] == "calendar.add":
            event = gws.calendar_create_event(
                title=p["title"],
                start_iso=p["datetime_iso"],
                attendees=p.get("attendees") or None,
                location=p.get("location"),
                description=p.get("description"),
            )
            proposals.update_status(
                proposal_id, "resolved",
                result={"event_id": event.get("id"), "html_link": event.get("htmlLink")},
                edited={"datetime_iso": p["datetime_iso"]} if action == "edit" else None,
            )
            _audit({
                "action": action, "proposal_id": proposal_id, "type": "calendar.add",
                "title": p["title"], "event_id": event.get("id"),
            })
            return {"ok": True, "result": event, "proposal": proposals.get(proposal_id)}

        if p["type"] == "gmail.send":
            msg_id = gws.gmail_send_reply(
                thread_id=p["thread_id"], to=p["to"],
                subject=p["subject"], body=p["body"],
            )
            proposals.update_status(
                proposal_id, "resolved",
                result={"message_id": msg_id},
                edited={"body": p["body"]} if action == "edit" else None,
            )
            _audit({
                "action": action, "proposal_id": proposal_id, "type": "gmail.send",
                "thread_id": p["thread_id"], "message_id": msg_id,
            })
            return {"ok": True, "result": {"message_id": msg_id}, "proposal": proposals.get(proposal_id)}

        return {"ok": False, "error": f"unknown proposal type {p['type']!r}"}

    except Exception as exc:
        proposals.update_status(proposal_id, "errored", error=str(exc))
        _audit({
            "action": action, "proposal_id": proposal_id,
            "type": p.get("type"), "error": str(exc),
        })
        return {"ok": False, "error": str(exc), "proposal": proposals.get(proposal_id)}


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("usage: proposal_executor.py <id> <yes|no|edit> [edit_value]", file=sys.stderr)
        sys.exit(1)
    pid = sys.argv[1]
    act = sys.argv[2]
    edit = sys.argv[3] if len(sys.argv) > 3 else None
    print(json.dumps(execute(pid, act, edit), indent=2, default=str))
