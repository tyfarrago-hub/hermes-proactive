"""Google Workspace helper for Hermes — Gmail + Calendar.

Loads OAuth credentials, auto-refreshes token, exposes minimal API surface.

Files (VPS):
- /root/.hermes/google_workspace_client_secret.json
- /root/.hermes/google_workspace_token.json
"""

from __future__ import annotations

import base64
import json
import logging
import time
from datetime import datetime, timezone
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

logger = logging.getLogger(__name__)

HERMES_HOME = Path("/root/.hermes")
TOKEN_PATH = HERMES_HOME / "google_workspace_token.json"
CLIENT_SECRET_PATH = HERMES_HOME / "google_workspace_client_secret.json"

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/userinfo.email",
    "openid",
]


def _load_creds() -> Credentials:
    if not TOKEN_PATH.exists():
        raise FileNotFoundError(f"missing {TOKEN_PATH}; run OAuth flow on Mac and SCP token here")

    creds = Credentials.from_authorized_user_info(json.loads(TOKEN_PATH.read_text()), SCOPES)

    if not creds.valid:
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            TOKEN_PATH.write_text(creds.to_json())
            TOKEN_PATH.chmod(0o600)
        else:
            raise RuntimeError("creds invalid and not refreshable; re-run OAuth flow")

    return creds


def _gmail():
    return build("gmail", "v1", credentials=_load_creds(), cache_discovery=False)


def _calendar():
    return build("calendar", "v3", credentials=_load_creds(), cache_discovery=False)


# --- Gmail ---


def gmail_list_unread_threads(max_results: int = 30) -> list[dict[str, Any]]:
    """Return unread non-promo, non-update threads in the inbox.

    Output: list of {thread_id, subject, from, snippet, message_count, last_ts}.
    """
    svc = _gmail()
    # 'category:primary' isolates real human mail; '-from:no-reply' skips obvious notifications.
    query = "is:unread in:inbox category:primary -from:no-reply"
    result = svc.users().threads().list(userId="me", q=query, maxResults=max_results).execute()
    threads = result.get("threads", [])
    out = []
    for t in threads:
        full = svc.users().threads().get(userId="me", id=t["id"], format="metadata",
                                          metadataHeaders=["From", "Subject", "Date"]).execute()
        msgs = full.get("messages", [])
        if not msgs:
            continue
        last = msgs[-1]
        headers = {h["name"]: h["value"] for h in last.get("payload", {}).get("headers", [])}
        out.append({
            "thread_id": t["id"],
            "subject": headers.get("Subject", "(no subject)"),
            "from": headers.get("From", "(unknown)"),
            "snippet": last.get("snippet", ""),
            "message_count": len(msgs),
            "internal_date": int(last.get("internalDate", 0)),
        })
    return out


def gmail_get_thread_text(thread_id: str, max_chars: int = 4000) -> str:
    """Return concatenated plaintext bodies of a thread, oldest first, capped."""
    svc = _gmail()
    full = svc.users().threads().get(userId="me", id=thread_id, format="full").execute()
    parts = []
    for m in full.get("messages", []):
        headers = {h["name"]: h["value"] for h in m.get("payload", {}).get("headers", [])}
        body = _extract_plaintext(m.get("payload", {}))
        from_addr = headers.get("From", "?")
        date = headers.get("Date", "?")
        parts.append(f"--- From: {from_addr} | {date}\n{body[:1500]}")
    text = "\n\n".join(parts)
    return text[:max_chars]


def _extract_plaintext(payload: dict[str, Any]) -> str:
    if payload.get("mimeType") == "text/plain" and "data" in payload.get("body", {}):
        return base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", errors="replace")
    for part in payload.get("parts", []) or []:
        text = _extract_plaintext(part)
        if text:
            return text
    return ""


def gmail_send_reply(thread_id: str, to: str, subject: str, body: str) -> str:
    """Send a reply to a thread. Returns sent message id."""
    svc = _gmail()
    msg = MIMEText(body, _charset="utf-8")
    msg["to"] = to
    msg["subject"] = subject if subject.lower().startswith("re:") else f"Re: {subject}"
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("ascii")
    sent = svc.users().messages().send(
        userId="me", body={"raw": raw, "threadId": thread_id}
    ).execute()
    return sent["id"]


# --- Calendar ---


def calendar_create_event(
    title: str,
    start_iso: str,
    end_iso: str | None = None,
    attendees: list[str] | None = None,
    location: str | None = None,
    description: str | None = None,
    calendar_id: str = "primary",
) -> dict[str, Any]:
    """Create a calendar event.

    start_iso/end_iso: ISO 8601 with timezone offset, e.g. '2026-05-09T15:00:00-04:00'.
    If end_iso is None, defaults to start + 1 hour.
    """
    if not end_iso:
        from datetime import timedelta
        start_dt = datetime.fromisoformat(start_iso)
        end_dt = start_dt + timedelta(hours=1)
        end_iso = end_dt.isoformat()

    body: dict[str, Any] = {
        "summary": title,
        "start": {"dateTime": start_iso},
        "end": {"dateTime": end_iso},
    }
    if attendees:
        body["attendees"] = [{"email": a} for a in attendees]
    if location:
        body["location"] = location
    if description:
        body["description"] = description

    return _calendar().events().insert(calendarId=calendar_id, body=body).execute()


def smoke_test() -> dict[str, Any]:
    """Quick health check: list 1 unread, list calendars, return summary."""
    out: dict[str, Any] = {}
    try:
        threads = gmail_list_unread_threads(max_results=1)
        out["gmail_ok"] = True
        out["sample_thread"] = threads[0]["subject"] if threads else "(no unread)"
    except Exception as exc:
        out["gmail_ok"] = False
        out["gmail_err"] = str(exc)

    try:
        # events.list works with calendar.events scope; calendarList.list needs broader read.
        events = _calendar().events().list(
            calendarId="primary", maxResults=1, singleEvents=True,
            orderBy="startTime", timeMin=datetime.now(timezone.utc).isoformat(),
        ).execute()
        out["calendar_ok"] = True
        out["sample_event"] = events.get("items", [{}])[0].get("summary", "(no upcoming events)")
    except Exception as exc:
        out["calendar_ok"] = False
        out["calendar_err"] = str(exc)

    return out


if __name__ == "__main__":
    import json as _json
    print(_json.dumps(smoke_test(), indent=2))
