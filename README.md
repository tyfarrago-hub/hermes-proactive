# hermes-proactive

Bottle the proactive Hermes Agent setup so a friend with fresh Claude Code can reach the same endpoint in one session.

## What you get when this finishes

- A **VPS** with [Hermes Agent](https://github.com/NousResearch/hermes-agent) running as a systemd service.
- A **Telegram supergroup** ("Hermes Ops") with two topics:
  - **Daily Briefs** — predictable scheduled briefs (~2/day).
  - **Proactive Nudges** — proposals you confirm with one reply.
- A **Mac iMessage bridge** that pushes recent messages to the VPS every 5 minutes.
- A **Google Workspace OAuth** token that lets Hermes read your Gmail, send drafts, and create calendar events.
- Two **watchers** running on cron:
  - `imessage-scheduling-watcher` (every 1 min) — when someone confirms a meeting in iMessage, you get "📅 Calendar add? yes / edit / no" in Proactive Nudges.
  - `gmail-reply-watcher` (every 30 min) — when an email needs a reply, Hermes drafts it in your voice and shows it as "📨 Reply to {sender}? yes / edit / no".
- A **proposal-execution loop**. When you reply `yes <id>` in Proactive Nudges, Hermes actually creates the calendar event or sends the email and confirms back with ✓.

## Install

One line:

```bash
curl -fsSL https://raw.githubusercontent.com/tyfarrago-hub/hermes-proactive/v0.1.2/install.sh | bash
```

Then in a fresh Claude Code session in the same shell:

> set up hermes-proactive

The agent will run the setup gate, which walks ten phases. Most are automatic. You'll be asked to do five manual things across the whole flow:

1. **BotFather** — `/newbot` and paste the token back when asked (phase C).
2. **Telegram supergroup** — create "Hermes Ops", enable Topics, add two topics, add the bot as admin (phase E). The skill walks you through each tap.
3. **Google Cloud Console** — create a project, enable Gmail + Calendar APIs, click Create on a Desktop OAuth client, paste the JSON back (phase G).
4. **Google consent** — click Allow on the OAuth consent screen that pops up (phase G).
5. **Final Telegram smoke** — reply `yes <id>` to one test proposal so the setup proves the actual approval loop (phase J).

Total wall-clock target: under 60 minutes. Most of that is waiting on the Hermes installer + the first cron tick.

## Requirements

- macOS (for iMessage chat.db read; chat.db is Apple-only)
- Python 3.11 or newer
- A VPS you control with SSH access (any provider — DigitalOcean, Hetzner, Linode all work; ~$5–12/mo)
- An OpenRouter API key (or any LLM provider Hermes supports)
- A Telegram account
- A Google account with Gmail + Calendar

## Cost

- Hermes Agent: free, MIT
- VPS: $5–12/mo
- LLM: $5–20/mo typical, depends on your inbox size
- Google APIs: free tier, way bigger than what Hermes uses
- Telegram: free
- This skill: free

## Privacy notes

- Your **iMessages** never leave your Mac except to your own VPS over SSH.
- The **bot token** is stored only in `/root/.hermes/.env` on the VPS. The skill never writes it to your Mac.
- The **OAuth client_secret** and **token** live at `~/.hermes-proactive/` (0600) and `/root/.hermes/google_workspace_*.json` (0600). They're tied to your Google account; revoke anytime from [Google account permissions](https://myaccount.google.com/permissions).
- All bot decisions on what to draft are local to your VPS. Your inbox content goes to whichever LLM provider you configured Hermes with.

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

See `docs/uninstall.md` for a clean teardown that removes the launchd plist, the cron jobs on the VPS, the lib files, and the USER.md section. It does NOT delete Hermes itself or your Telegram supergroup — those are yours to keep.

## License

MIT.
