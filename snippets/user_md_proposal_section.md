## Hermes Ops command surface (proposal handler)
- Group **Hermes Ops** chat_id `{{CHAT_ID}}` has two topics:
  - **Dashboard** (message_thread_id `{{DASHBOARD_THREAD_ID}}`) — scheduled daily briefs.
  - **Decisions** (message_thread_id `{{DECISIONS_THREAD_ID}}`) — pending proposals (calendar adds, email replies).
- Hermes mints proposals into `/root/.hermes/proposals.json` via `/root/.hermes/lib/proposals.py`. Each has a short base36 `id`.
- When the user's incoming message in **Decisions** matches `^(yes|no|edit)\s+([a-z0-9]+)(?:\s+(.+))?$`, immediately:
  1. Run `/root/.hermes/hermes-agent/venv/bin/python /root/.hermes/lib/proposal_executor.py <id> <yes|no|edit> [edit_value]` via the terminal tool.
  2. On success, reply succinctly: "✓ Done — {one-line summary, e.g. 'event added Sat 3pm', 'reply sent'}".
  3. On error, reply: "✗ Failed — {error}. Proposal `<id>` left as-is, retry with edit if needed."
  4. Do not load other context, do not fetch the calendar, do not re-derive. The proposal record self-contains everything.
- Audit trail of executed proposals: `/root/.hermes/proposal_log.jsonl`.
- Watchers that emit proposals:
  - `imessage-scheduling-watcher` (every 1 min) — calendar-add proposals from iMessage scheduling intent.
  - `gmail-reply-watcher` (every 30 min) — gmail-send proposals for threads needing reply.
