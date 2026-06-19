#!/usr/bin/env bash
# Re-apply Hermes local patches after `hermes update` (git reset --hard wipes them).
# Idempotent: skips patches already present. Telegrams the owner if one no longer applies.
#
# Installed to /root/.hermes/local-patches/apply.sh and wired as an
# ExecStartPre on the hermes-gateway systemd unit (see systemd/local-patches.conf),
# so every gateway start — including the restart that follows `hermes update` —
# re-applies any patch in this directory that the update wiped.
set -u
REPO=/root/.hermes/hermes-agent
PATCHES=/root/.hermes/local-patches
LOG=/root/.hermes/logs/local-patches.log
mkdir -p "$(dirname "$LOG")"
cd "$REPO" || exit 0
ts(){ date -Is; }
# Owner chat id for drift alerts: read from .env (HERMES_OWNER_CHAT_ID preferred,
# TELEGRAM_CHAT_ID accepted). If neither is set the alert is silently skipped —
# the patch logic still runs; only the notification is best-effort.
alert(){
  local tok chat f="/root/.hermes/.env"
  chat=$(grep -m1 -E '^(HERMES_OWNER_CHAT_ID|TELEGRAM_CHAT_ID)=' "$f" 2>/dev/null | cut -d= -f2- | tr -d '"'"'"'"' )
  [ -n "$chat" ] || return 0
  tok=$(grep -m1 -E '^(TELEGRAM_BOT_TOKEN|HERMES_TELEGRAM_BOT_TOKEN)=' "$f" 2>/dev/null | cut -d= -f2- | tr -d '"'"'"'"' )
  [ -n "$tok" ] && curl -s -m 15 "https://api.telegram.org/bot${tok}/sendMessage" \
    --data-urlencode "chat_id=${chat}" \
    --data-urlencode "text=⚠️ Hermes local patch failed to apply: $1. Context drifted after an update — re-create the patch." >/dev/null 2>&1
}
for p in "$PATCHES"/*.patch; do
  [ -e "$p" ] || continue
  name=$(basename "$p")
  if git apply --reverse --check "$p" >/dev/null 2>&1; then
    echo "$(ts) $name: already applied" >> "$LOG"; continue
  fi
  if git apply --check "$p" >/dev/null 2>&1; then
    git apply "$p" && echo "$(ts) $name: re-applied" >> "$LOG"
  else
    echo "$(ts) $name: DOES NOT APPLY (context drift)" >> "$LOG"; alert "$name"
  fi
done
exit 0
