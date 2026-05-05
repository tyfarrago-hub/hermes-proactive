# Uninstall

This removes the proactive layer (watchers, libs, USER.md changes, Mac bridge).
It does NOT delete Hermes Agent itself or your Telegram supergroup — those are yours.

## Mac side

```bash
USER_NAME="$(whoami)"
PLIST="$HOME/Library/LaunchAgents/com.${USER_NAME}.hermes-push.plist"

# Unload and remove the launchd job
launchctl unload "$PLIST" 2>/dev/null || true
rm -f "$PLIST"

# Remove the bridge + state + creds
rm -rf "$HOME/.hermes-proactive"

# Logs (optional — they have your iMessage push history)
rm -rf "$HOME/Library/Logs/HermesProactive"
```

Optionally remove the skill itself:

```bash
rm -rf "$HOME/.claude/skills/hermes-proactive"
```

## VPS side

SSH in:

```bash
ssh -i ~/.ssh/id_ed25519 root@your-vps
```

Remove the cron jobs:

```bash
cd /root/.hermes/hermes-agent
VENV=/root/.hermes/hermes-agent/venv/bin/python
LIST_JOBS=$($VENV -m hermes_cli.main cron list --all 2>/dev/null | grep -E "imessage-scheduling-watcher|gmail-reply-watcher" | awk '{print $1}')
for jid in $LIST_JOBS; do
  $VENV -m hermes_cli.main cron remove "$jid"
done
```

Remove the lib files and credentials:

```bash
rm -f /root/.hermes/lib/google_workspace.py \
      /root/.hermes/lib/proposals.py \
      /root/.hermes/lib/proposal_executor.py \
      /root/.hermes/lib/gmail_candidates.py
rm -f /root/.hermes/google_workspace_client_secret.json \
      /root/.hermes/google_workspace_token.json
rm -f /root/.hermes/proposals.json /root/.hermes/proposal_log.jsonl
rm -f /root/.hermes/agent/state/imessage-scheduling-watcher.json
```

Remove the proposal-handler section from USER.md:

```bash
python3 -c "
from pathlib import Path
p = Path('/root/.hermes/USER.md')
content = p.read_text()
marker = '<!-- hermes-proactive:proposal-handler -->'
if marker in content:
    cleaned = content.split(marker)[0].rstrip() + '\n'
    p.write_text(cleaned)
    print('removed proposal-handler section')
else:
    print('marker not present; no changes')
"
```

## Google Cloud side (optional)

The OAuth tokens stay valid until you revoke them.

To revoke:
- Go to https://myaccount.google.com/permissions
- Find your OAuth client (named like "hermes" or whatever you chose)
- Click Remove Access

To delete the entire project (also stops any other clients on it):
- https://console.cloud.google.com/cloud-resource-manager
- Select the project, click Delete. (30-day soft delete, so you can recover.)

## Telegram side (optional)

The supergroup keeps running. To remove the bot from it:
- Open the supergroup → Members → tap the bot → Remove from group.

To delete the supergroup entirely:
- Group settings → Delete Group.

## Sanity check after uninstall

```bash
ssh root@your-vps "ls /root/.hermes/lib/ 2>&1; cat /root/.hermes/cron/jobs.json | python3 -c 'import json,sys; d=json.load(sys.stdin); print([j[\"name\"] for j in d.get(\"jobs\",[])])'"
launchctl list 2>/dev/null | grep hermes-push   # should be empty
```

If all three return nothing related to this skill, the uninstall is clean.
