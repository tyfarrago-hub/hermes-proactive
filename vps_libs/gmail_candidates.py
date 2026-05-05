#!/usr/bin/env python3
"""Fetch unread Gmail threads + for each, return enough context for an LLM to
decide needs-reply and draft.

Output: JSON list to stdout. Each entry:
  {thread_id, subject, from, to, snippet, body_text, internal_date, already_proposed}

Filters out threads we already minted a proposal for (pending or resolved) and
threads that are pure newsletters / system mail (best-effort heuristics).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import google_workspace as gws
import proposals

NEWSLETTER_HINTS = (
    "unsubscribe",
    "view this email in your browser",
    "you are receiving this email because",
)

SYSTEM_FROM_HINTS = (
    "no-reply",
    "noreply",
    "donotreply",
    "do-not-reply",
    "notifications@",
    "alerts@",
    "support@github.com",
)


def _looks_like_newsletter(text: str, from_addr: str) -> bool:
    lower_from = from_addr.lower()
    if any(h in lower_from for h in SYSTEM_FROM_HINTS):
        return True
    lower = text.lower()
    return sum(1 for h in NEWSLETTER_HINTS if h in lower) >= 1


def main(max_results: int = 20) -> None:
    threads = gws.gmail_list_unread_threads(max_results=max_results)
    out = []
    for t in threads:
        if proposals.has_pending_for(t["thread_id"]):
            continue
        body = gws.gmail_get_thread_text(t["thread_id"], max_chars=3000)
        if _looks_like_newsletter(body, t["from"]):
            continue
        out.append({
            "thread_id": t["thread_id"],
            "subject": t["subject"],
            "from": t["from"],
            "snippet": t["snippet"],
            "body_text": body,
            "internal_date": t["internal_date"],
        })
    print(json.dumps(out))


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 20
    main(n)
