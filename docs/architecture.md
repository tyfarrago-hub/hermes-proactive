# Architecture

## Map of moving parts

```
┌──────────────────────────┐                ┌────────────────────────────────────┐
│ Mac (your laptop)        │                │ VPS (any provider, $5-12/mo)       │
│                          │                │                                    │
│ ~/.hermes-proactive/     │                │ /root/.hermes/                     │
│   bridge/                │  scp every 5m  │   inbox/imessage.json              │
│   client_secret.json     │ ─────────────▶ │   lib/google_workspace.py          │
│   token.json             │                │   lib/proposals.py                 │
│                          │  scp once      │   lib/proposal_executor.py         │
│ ~/Library/Messages/      │ ─────────────▶ │   lib/gmail_candidates.py          │
│   chat.db (read)         │                │   google_workspace_*.json (0600)   │
│                          │                │   proposals.json                   │
│ ~/Library/LaunchAgents/  │                │   proposal_log.jsonl               │
│   com.<user>.hermes-push │                │   USER.md (with proposal handler)  │
│   .plist (every 5m)      │                │                                    │
└──────────────────────────┘                │ hermes-gateway.service             │
                                            │   ├─ telegram bot polling          │
                                            │   ├─ cron tick every 60s           │
                                            │   └─ agent loop (LLM)              │
                                            │                                    │
                                            │ /root/.hermes/cron/jobs.json       │
                                            │   ├─ imessage-scheduling-watcher   │
                                            │   ├─ gmail-reply-watcher           │
                                            │   └─ ... your other crons          │
                                            └────────────────────────────────────┘
                                                            │
                                                            ▼
                                            ┌────────────────────────────────────┐
                                            │ Telegram                           │
                                            │   └─ "Hermes Ops" supergroup       │
                                            │       ├─ Daily Briefs (topic)      │
                                            │       └─ Proactive Nudges (topic)  │
                                            └────────────────────────────────────┘
```

## Data flow: incoming iMessage → calendar event

1. Friend texts you "see you Sat 3pm" on iMessage.
2. Within 5 minutes, the launchd plist on your Mac fires `bridge/run_once.sh`.
3. The bridge reads `~/Library/Messages/chat.db` (read-only, requires Full Disk Access), filters spam, exports the last 6 hours to a JSON.
4. SCP pushes the JSON to `/root/.hermes/inbox/imessage.json` on the VPS atomically.
5. Within the next minute, the `imessage-scheduling-watcher` cron fires.
6. The watcher's prompt instructs Hermes to: read the inbox JSON, read its state file (last processed message id), classify any new inbound message for scheduling intent, mint a proposal in `/root/.hermes/proposals.json`, and emit one "📅 Calendar add?" message to the Proactive Nudges topic.
7. You see the proposal on your phone in Telegram. Reply `yes a3` (or `edit a3 4pm`, or `no a3`).
8. Hermes (always running as a Telegram bot) receives your reply in Proactive Nudges. The agent's system prompt (USER.md) tells it to detect this pattern and run `proposal_executor.py a3 yes` via the terminal tool. Phase J verifies this exact Telegram reply path before setup is marked complete.
9. The executor looks up proposal a3, calls `google_workspace.calendar_create_event(...)`, records the result in `proposal_log.jsonl`, marks the proposal resolved.
10. Hermes replies "✓ Done — event added Sat 3pm with Friend".

Total wall-clock: usually under 2 minutes from your friend's text to a calendar event existing.

## Why this split

- **Mac side**: chat.db is the only piece that has to live on the Mac. Apple's TCC permission system means we can't read iMessage from anywhere else, so we extract on the Mac and push.
- **VPS side**: everything that needs to run 24/7 (the bot, the watchers, the executor) lives on the VPS. Your Mac can sleep, the system keeps running.
- **Stateless watchers**: each watcher is a cron job + prompt. No long-running daemon. If a tick is missed, the next one catches up.
- **Stateful proposals**: `/root/.hermes/proposals.json` is the single source of truth for what's pending. Watchers mint through `/root/.hermes/lib/proposals.py`; the executor reads + updates through the same helper. Locked with `fcntl` to prevent race conditions across concurrent ticks.

## Hermes Agent (the layer below us)

The skill builds on top of [Hermes Agent](https://github.com/NousResearch/hermes-agent), which provides:

- A gateway that connects to Telegram/Discord/Slack/etc.
- A Python agent loop that runs an LLM on incoming messages with terminal/file/code tools.
- A cron scheduler that fires jobs and routes their output to platforms (the `deliver` field, including topic routing via `telegram:<chat_id>:<thread_id>`).
- A skills system for reusable behaviors.

We do not modify Hermes core. We:
- Add four lib files to `/root/.hermes/lib/`.
- Add a section to Hermes's `USER.md` system prompt.
- Create two cron jobs.
- Set up Telegram, Google Cloud, and a Mac-side bridge as separate concerns.

When Hermes Agent updates upstream, we should be unaffected — we don't touch their code.

## Cost and scale

For a typical user:
- 1 Telegram bot: free
- 1 GCP project (Gmail + Calendar APIs): free tier, ~10k requests/day cap is way above what watchers need
- 1 VPS: $5–12/mo
- LLM tokens: depends on inbox size and watcher cadence. Sonnet is the default for reasoning. ~$5–20/mo for a busy inbox at the default cadences.

Watcher cost driver: gmail-reply-watcher reads up to 20 unread threads every 30 min. Most thicken inboxes don't have 20 needs-reply threads, so the watcher returns SILENT and emits nothing on most ticks.
