# Troubleshooting

## "Phase A blocked: Full Disk Access not granted"

The bridge needs to read `~/Library/Messages/chat.db`. macOS blocks this by default.

Fix: System Settings → Privacy & Security → Full Disk Access. Add Terminal (or whichever app you launched Claude Code from). Toggle it on. Quit and reopen the terminal.

If you're using iTerm2, VS Code's integrated terminal, or another shell host, add that one too. The grant inherits to child processes (launchd → zsh → python3), so you only need to grant the parent shell.

## "Phase B blocked: hermes-gateway service not active"

You need to authenticate the LLM brain. SSH in and run `hermes login --provider openai-codex` (the recommended primary: OpenAI Codex `gpt-5.5`, an OAuth login, no API key to paste). Confirm `/root/.hermes/config.yaml` has `model: openai-codex/gpt-5.5`. Then `sudo systemctl enable --now hermes-gateway` and re-run phase B.

## "Phase C blocked: hermes setup --add-platform telegram not yet run"

The bot token never lives on your Mac. You have to paste it into the VPS's interactive setup wizard.

```bash
ssh -i ~/.ssh/id_ed25519 root@your-vps
hermes setup --add-platform telegram
# paste the token from BotFather
sudo systemctl restart hermes-gateway
```

Then re-run phase C.

## "Phase D blocked: VPS did not receive iMessage push"

Check `~/Library/Logs/HermesProactive/sync.err` on your Mac. Common causes:

- SSH key not on the VPS yet → run `ssh-copy-id -i ~/.ssh/id_ed25519.pub root@your-vps`
- chat.db unreadable → see Phase A FDA fix above
- VPS has no `/root/.hermes/inbox/` directory → SSH in and `mkdir -p /root/.hermes/inbox`

Test the bridge manually: `~/.hermes-proactive/bridge/run_once.sh`. Read stderr.

## "Phase E: I can't find my chat_id even after sending the messages"

The bot has to be admin and have privacy mode disabled (which admins automatically do). Three checks:

1. The bot is in the group as a member.
2. The bot is promoted to admin (right-click bot → Promote → toggle on Manage Topics).
3. You sent the message *with the @bot mention* in each topic, not just plain text.

Also: Telegram's `getUpdates` only returns the last 24 hours of unprocessed updates. If you sent the messages over a day ago, send fresh ones, then re-run the phase.

## "Phase G: client_secret JSON missing 'installed' key"

You probably downloaded a Web Application OAuth client by accident. The skill needs Application type **Desktop app**. Re-create the client in Google Cloud Console with the right type and try again.

## "Phase H smoke test: calendar_ok: false"

Most likely: the OAuth scopes didn't include `calendar.events`. Confirm by looking at `~/.hermes-proactive/token.json` — the `scopes` field should include `https://www.googleapis.com/auth/calendar.events`. If not, run `python3 ~/.claude/skills/hermes-proactive/scripts/check_setup.py reset g` and redo phase G.

## "Phase J ran but I didn't see a setup-complete message"

The receipt is sent via the bot. If the bot isn't actually wired to the supergroup yet, the message goes nowhere. Open Telegram, look at "Hermes Ops" → Dashboard. If empty:

1. Confirm the bot is admin in the supergroup with Send Messages permission.
2. SSH to VPS, run: `tail /root/.hermes/cron/logs/*.log | head -50`. Look for delivery errors.
3. Manually send a test from VPS:
   ```bash
   /root/.hermes/hermes-agent/venv/bin/python -c "
   import urllib.request, urllib.parse, json
   tok = open('/root/.hermes/.env').read()
   import re; m = re.search(r'TELEGRAM_BOT_TOKEN[ =]+(\\S+)', tok)
   tok = m.group(1).strip().strip(chr(34)).strip(chr(39))
   data = urllib.parse.urlencode({'chat_id': YOUR_CHAT_ID, 'message_thread_id': YOUR_DAILY_THREAD_ID, 'text': 'test'}).encode()
   r = urllib.request.urlopen(f'https://api.telegram.org/bot{tok}/sendMessage', data=data, timeout=15)
   print(r.status)
   "
   ```

## A watcher fires but emits weird output

Read the cron output: `cat /root/.hermes/cron/output/<job_id>/<latest>.md`. The "## Response" section shows what the LLM said. If it didn't follow the prompt, the prompt may need clarification. Edit `prompts/imessage_scheduling_watcher.txt` or `prompts/gmail_reply_watcher.txt` in the skill, then `hermes cron edit <id> --prompt "$(cat newprompt)"`.

## The bot keeps replying to me with skill_view stuff instead of executing proposals

Check `/root/.hermes/USER.md` — the proposal-handler section must be present. Search for `<!-- hermes-proactive:proposal-handler -->`. If missing, re-run phase I:

```bash
python3 ~/.claude/skills/hermes-proactive/scripts/check_setup.py reset i
python3 ~/.claude/skills/hermes-proactive/scripts/phase_i_user_md.py
```

## I want to change the watcher cadence

Easiest: edit cron directly on the VPS.

```bash
hermes cron edit <imessage-watcher-id> --schedule "*/2 * * * *"   # every 2 min
hermes cron edit <gmail-watcher-id> --schedule "*/15 * * * *"     # every 15 min
```

Or update `config.example.json` defaults and re-run phase H to recreate.

## I broke something. How do I start over?

```bash
python3 ~/.claude/skills/hermes-proactive/scripts/check_setup.py reset a
# then b, c, d, ... etc
```

Each phase starts from scratch when reset. Files written on the VPS are overwritten cleanly.

For a full nuclear option, see `docs/uninstall.md`.
