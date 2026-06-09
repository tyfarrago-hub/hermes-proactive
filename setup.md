# Setup walkthrough — phase by phase

The skill is a state machine. State lives at `~/.hermes-proactive/state.json`. Each phase is idempotent; re-running a complete phase is a no-op.

The fastest path: open a Claude Code session and say "set up hermes-proactive". The agent invokes the right phase script for you each time.

This doc is for people who want to run the phases manually or understand what each one does.

## Phase A — Mac prerequisites

Script: `scripts/phase_a_mac_prereqs.py`

- Confirms macOS, Python ≥ 3.11.
- Generates `~/.ssh/id_ed25519` if missing.
- Prompts you for `vps_host` (`user@host` or `host`).
- Tests SSH connectivity.
- Probes Full Disk Access by trying to read `~/Library/Messages/chat.db`.

Manual you do: install your SSH public key on the VPS (`ssh-copy-id -i ~/.ssh/id_ed25519.pub root@your-vps`), grant Terminal Full Disk Access in System Settings if not already.

## Phase B — VPS Hermes install

Script: `scripts/phase_b_vps.py`

- SSHes in, runs the upstream Nous Research installer if Hermes isn't already at `/root/.hermes/hermes-agent/`.
- Confirms `hermes-gateway.service` is active.

Manual you do: SSH in once and run `hermes setup` to pick an LLM provider (OpenRouter recommended) and paste the API key. Then `sudo systemctl enable --now hermes-gateway`.

## Phase C — Telegram bot

Script: `scripts/phase_c_telegram.py`

- Walks you through BotFather (`/newbot`).
- Validates the bot token with `getMe`.
- Captures the bot username, asks you to wire it into Hermes via `hermes setup --add-platform telegram` (token paste happens on the VPS, not your Mac).

Manual you do: tap through BotFather, paste token into the VPS's `hermes setup`.

## Phase D — Mac iMessage bridge

Script: `scripts/phase_d_imessage.py`

- Copies `bridge/` into `~/.hermes-proactive/bridge/`.
- Renders `~/Library/LaunchAgents/com.<user>.hermes-push.plist` with your VPS host + SSH key.
- Loads the launchd plist (push every 5 minutes).
- Triggers one push and verifies `/root/.hermes/inbox/imessage.json` is fresh.

Manual you do: nothing if FDA was granted in phase A.

## Phase E — Telegram supergroup

Script: `scripts/phase_e_supergroup.py`

This is the one phase with the most clicks. The script gives you a numbered checklist:

1. Create "Hermes Ops" group, just yourself.
2. Enable Topics in group settings.
3. Create topic "Dashboard", then "Decisions".
4. Add your bot as admin with Manage Topics permission.
5. In each topic, send the bot a message: `@yourbot dashboard ready` and `@yourbot decisions ready`.

Then the script polls Telegram's bot API `getUpdates` to discover the chat_id and the two thread_ids, writes them to state.

## Phase F — Cron routing

Script: `scripts/phase_f_routing.py`

Reads existing Hermes cron jobs, classifies each into Dashboard / local using a name-fragment table, applies edits via `hermes cron edit ... --deliver=...`. Auto-pauses jobs that don't match any bucket. Never deletes. Every remote pause/edit must return success before the phase is marked complete.

Manual you do: confirm the proposed action plan with `y`.

## Phase G — Google OAuth

Script: `scripts/phase_g_oauth.py`

- Opens four URLs in your default browser (project create, Gmail API enable, Calendar API enable, OAuth client create).
- Asks you to paste the path or content of the downloaded `client_secret.json`.
- Runs `InstalledAppFlow.run_local_server()` — opens browser to Google's consent screen, captures code, exchanges for tokens.
- SCPs `client_secret.json` + `token.json` to the VPS at `/root/.hermes/google_workspace_*.json` (0600).

Manual you do: click through the four Google Cloud Console pages and click Allow on the consent screen.

## Phase H — Libs + watchers on VPS

Script: `scripts/phase_h_libs.py`

- SCPs `vps_libs/{google_workspace,proposals,proposal_executor,gmail_candidates}.py` to `/root/.hermes/lib/`.
- `pip install`s `google-auth google-api-python-client google-auth-oauthlib` into Hermes's venv.
- Initializes `proposals.json` + watcher state.
- Smoke test: runs `google_workspace.py` — must return both `gmail_ok: true` and `calendar_ok: true`.
- Creates two cron jobs: `imessage-scheduling-watcher` (every 1 min) and `gmail-reply-watcher` (every 30 min), routed to Decisions.

## Phase I — USER.md proposal handler

Script: `scripts/phase_i_user_md.py`

Appends `snippets/user_md_proposal_section.md` to `/root/.hermes/USER.md`, templated with your chat_id + thread_ids. Idempotent via marker comment.

## Phase J — End-to-end smoke test

Script: `scripts/phase_j_smoke.py`

- Mints a synthetic `calendar.add` proposal scheduled for 2099 (won't conflict).
- Posts it to Decisions and tells you the exact `yes <id>` reply to send.
- Polls `/root/.hermes/proposals.json` until Hermes receives the Telegram reply and executes the proposal.
- Confirms a calendar event was created through the actual approval loop.
- Deletes it.
- Sends a "✅ hermes-proactive setup complete" message to your Dashboard topic.

If you see the green check in Dashboard, the Telegram approval loop works end-to-end.

## What to do once it's running

Watch Decisions. When a proposal comes in, reply `yes <id>` to execute. The first time a real "📅 Calendar add?" appears for a friend confirming a meeting in iMessage, the system has paid for itself.
