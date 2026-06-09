# hermes-proactive

Stand up a proactive [Hermes Agent](https://github.com/NousResearch/hermes-agent) that works like a
chief-of-staff, not a notifier: it reads your trusted context, drafts the action, and waits for you
to say "yes." One install gets you the working spine. A companion guide takes you to the full
system.

This is a blank slate. There are no accounts, tokens, messages, or personal preferences baked in —
you wire it to your own.

## The core (what the one-line install gives you)

- A **VPS** running Hermes as a systemd service.
- A **Telegram command center** ("Hermes Ops") with two topics:
  - **Dashboard** — your scheduled briefs land here (~2/day).
  - **Decisions** — proposals you confirm with one reply. Nothing else clutters it.
- A **Mac iMessage bridge** that pushes recent messages to the VPS every 5 minutes (read-only).
- **Google Workspace OAuth** so Hermes can read your Gmail, draft replies, and create calendar events.
- Two **watchers** on cron:
  - `imessage-scheduling-watcher` — when someone confirms a meeting in iMessage, you get
    "📅 Calendar add? yes / edit / no" in Decisions.
  - `gmail-reply-watcher` — when an email needs a reply, Hermes drafts it in your voice and shows
    "📨 Reply to {sender}? yes / edit / no".
- The **proposal/approval loop**: reply `yes <id>` in Decisions and Hermes actually creates the
  event or sends the email, then confirms with ✓.

## The full system (the rest of how a mature Hermes is set up)

The core is the spine. The [Full Hermes Build Guide](docs/full-build-guide.md) is everything else,
written as a blank slate so you can add it around your own accounts:

- a **brain repo + file-based Living CRM** that turns messages into tracked relationships and
  next actions,
- a **USER.md / SOUL.md / MEMORY.md** profile system that makes every draft sound like you,
- **WhatsApp**, multi-account **Gmail** with an emoji labeler and an unsubscribe audit,
- **Plaid** (read-only bank visibility) and **Stripe** (revenue signals),
- a **persistent VPS browser** for logged-in services (groceries, bank link, etc.),
- the **full cron map** (morning/nightly briefs, weekly pulses, journal, soul refinement) with a
  deliberately sparse cadence philosophy,
- **MCP integration** so you can talk to Hermes from Claude Code.

Add those one at a time, after the core install is green and quiet. The guide gives the sequence.

## Install

One line:

```bash
curl -fsSL https://raw.githubusercontent.com/tyfarrago-hub/hermes-proactive/v0.2.1/install.sh | bash
```

Then in a fresh Claude Code session in the same shell:

> set up hermes-proactive

The agent runs a ten-phase setup gate. Most phases are automatic. You'll be asked to do five
manual things across the whole flow:

1. **BotFather** — `/newbot` and paste the token back when asked (phase C).
2. **Telegram supergroup** — create "Hermes Ops", enable Topics, add the **Dashboard** and
   **Decisions** topics, add the bot as admin (phase E). The skill walks each tap.
3. **Google Cloud Console** — create a project, enable Gmail + Calendar APIs, create a Desktop OAuth
   client, paste the JSON back (phase G).
4. **Google consent** — click Allow on the OAuth consent screen (phase G).
5. **Final Telegram smoke** — reply `yes <id>` to one test proposal so setup proves the real
   approval loop (phase J).

Total wall-clock target: under 60 minutes, most of it waiting on the Hermes installer and the first
cron tick.

## Requirements

- macOS (for the iMessage `chat.db` read; chat.db is Apple-only)
- Python 3.11 or newer
- A VPS you control with SSH access (DigitalOcean, Hetzner, Linode, etc.; ~$5–12/mo)
- An LLM brain for Hermes. Recommended: an **OpenAI / ChatGPT account** that Codex can log into — the primary is **OpenAI Codex `gpt-5.5`** via `hermes login` (OAuth, no API key). Optionally an **Anthropic** key for the recommended Sonnet→Haiku fallback. (Any other provider Hermes supports, e.g. OpenRouter, also works.)
- A Telegram account
- A Google account with Gmail + Calendar

## Cost

- Hermes Agent: free, MIT
- VPS: $5–12/mo
- LLM: $5–20/mo typical, scales with inbox size and cadence
- Google APIs: free tier, far bigger than what Hermes uses
- Telegram: free
- This skill: free

## Privacy notes

- Your **iMessages** never leave your Mac except to your own VPS over SSH.
- The **bot token** is stored only in `/root/.hermes/.env` on the VPS. The skill never writes it to
  your Mac.
- The **OAuth client_secret** and **token** live at `~/.hermes-proactive/` (0600) and
  `/root/.hermes/google_workspace_*.json` (0600). Revoke anytime from
  [Google account permissions](https://myaccount.google.com/permissions).
- All decisions on what to draft are local to your VPS. Inbox content goes to whichever LLM provider
  you configured Hermes with.

## Re-running phases

Each phase is idempotent. To redo one:

```bash
python3 ~/.claude/skills/hermes-proactive/scripts/check_setup.py reset g   # redo google oauth
python3 ~/.claude/skills/hermes-proactive/scripts/phase_g_oauth.py
```

To check status:

```bash
python3 ~/.claude/skills/hermes-proactive/scripts/check_setup.py status
```

## Uninstall

See [docs/uninstall.md](docs/uninstall.md) for a clean teardown that removes the launchd plist, the
core cron jobs on the VPS, the lib files, and the USER.md section. It does NOT delete Hermes itself
or your Telegram supergroup — those are yours to keep.

## License

MIT.
