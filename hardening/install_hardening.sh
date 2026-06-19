#!/usr/bin/env bash
# install_hardening.sh — apply the Hermes reliability + context-awareness
# hardening layer to a target Hermes VPS. Idempotent: safe to re-run.
#
# Usage:
#   ./install_hardening.sh <ssh_host> [--owner-chat <id>] [--no-restart]
#   ./install_hardening.sh <ssh_host> --check        # read-only: report state, change nothing
#
#   <ssh_host>  ssh alias or user@host for the target Hermes box (root).
#   --owner-chat <id>  Telegram chat id that watchdog/drift alerts go to.
#                      Written to /root/.hermes/.env as HERMES_OWNER_CHAT_ID.
#   --no-restart       apply changes but do not restart the gateway.
#   --check            verify what is already installed; make no changes.
#
# What it installs (each step idempotent, provider-aware):
#   1. Update-safe local-patch machinery (apply.sh + systemd ExecStartPre).
#   2. Gateway patches: mirror-cron-deliveries, reply-context-anchor.
#   3. config.yaml: session_reset.mode -> idle (removes the daily hard reset).
#   4. Reliability watchdogs + system crons (Codex token refresh if Codex is in
#      the chain; the 5-min unfreeze only if Codex is the PRIMARY brain; Google
#      OAuth monitor if Google OAuth is wired).
#   5. Restart the gateway and verify (unless --check / --no-restart).
set -uo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

HOST=""; CHECK=0; RESTART=1; OWNER_CHAT=""
while [ $# -gt 0 ]; do
  case "$1" in
    --check) CHECK=1; shift;;
    --no-restart) RESTART=0; shift;;
    --owner-chat) OWNER_CHAT="${2:-}"; shift 2;;
    -*) echo "unknown flag: $1" >&2; exit 2;;
    *) HOST="$1"; shift;;
  esac
done
[ -n "$HOST" ] || { echo "usage: $0 <ssh_host> [--owner-chat <id>] [--no-restart] [--check]" >&2; exit 2; }

say(){ printf '\033[1;36m==>\033[0m %s\n' "$*"; }
ok(){  printf '\033[1;32m  ok\033[0m %s\n' "$*"; }
warn(){ printf '\033[1;33m  !!\033[0m %s\n' "$*"; }
sshq(){ ssh -o BatchMode=yes -o ConnectTimeout=15 "$HOST" "$@"; }
scpq(){ scp -q "$1" "$HOST:$2" || { echo "  FATAL: scp failed: $1 -> $2"; exit 1; }; }

REPO=/root/.hermes/hermes-agent
LP=/root/.hermes/local-patches
DROPIN=/etc/systemd/system/hermes-gateway.service.d

# ---- preflight ------------------------------------------------------------
say "Preflight: $HOST"
sshq 'test -d '"$REPO"' && test -f /root/.hermes/config.yaml' \
  || { echo "  target is not a Hermes box ($REPO or config.yaml missing)"; exit 1; }
sshq 'test -x /root/.hermes/hermes-agent/venv/bin/python' \
  || { echo "  Hermes venv python missing at /root/.hermes/hermes-agent/venv/bin/python"; exit 1; }
# Provider detection ignores comment lines. Codex-in-chain (any) drives the token
# refresh; Codex-PRIMARY (the model: line) drives the 5-min unfreeze.
HAS_CODEX=0
sshq 'grep -vE "^[[:space:]]*#" /root/.hermes/config.yaml | grep -q "openai-codex"' && HAS_CODEX=1
CODEX_PRIMARY=0
sshq 'grep -E "^model:" /root/.hermes/config.yaml | grep -q "openai-codex"' && CODEX_PRIMARY=1
HAS_GOOGLE=0
sshq 'find /root/.hermes/google_accounts -name google_token.json 2>/dev/null | grep -q .' && HAS_GOOGLE=1
ok "reachable. codex=$HAS_CODEX (primary=$CODEX_PRIMARY) google_oauth=$HAS_GOOGLE"

if [ "$CHECK" = 1 ]; then
  say "CHECK mode — read-only state report"
  sshq 'set -e
    echo "  local-patches dir: $(ls '"$LP"'/*.patch 2>/dev/null | wc -l) patch(es)"
    for f in '"$LP"'/*.patch; do [ -e "$f" ] || continue; p=$(basename "$f" .patch)
      if (cd '"$REPO"' && git apply --reverse --check "$f" >/dev/null 2>&1); then echo "  patch $p: APPLIED"; else echo "  patch $p: present but NOT applied"; fi
    done
    echo "  ExecStartPre drop-in: $([ -f '"$DROPIN"'/local-patches.conf ] && echo present || echo MISSING)"
    echo "  session_reset.mode: $(awk "/^session_reset:/{f=1} f&&/mode:/{print \$2; exit}" /root/.hermes/config.yaml)"
    echo "  watchdog scripts: $(ls /root/.hermes/scripts/codex_token_refresh.py /root/.hermes/scripts/codex_unfreeze.py /root/.hermes/scripts/google_token_monitor.py 2>/dev/null | wc -l)/3 present"
    echo "  watchdog crons: $(crontab -l 2>/dev/null | grep -cE "codex_token_refresh|codex_unfreeze|google_token_monitor") installed"
    echo "  gateway: $(systemctl is-active hermes-gateway)"
  '
  exit 0
fi

# ---- 1. local-patch machinery --------------------------------------------
say "1/5 update-safe local-patch machinery"
sshq "mkdir -p $LP /root/.hermes/logs $DROPIN"
scpq "$SCRIPT_DIR/apply.sh" "$LP/apply.sh"
for p in "$SCRIPT_DIR"/patches/*.patch; do scpq "$p" "$LP/$(basename "$p")"; done
scpq "$SCRIPT_DIR/systemd/local-patches.conf" "$DROPIN/local-patches.conf"
sshq "chmod +x $LP/apply.sh && systemctl daemon-reload"
ok "machinery installed (apply.sh + $(ls "$SCRIPT_DIR"/patches/*.patch | wc -l | tr -d ' ') patches + ExecStartPre)"

# ---- 2. apply the gateway patches now ------------------------------------
say "2/5 apply gateway patches"
sshq "$LP/apply.sh; tail -n 3 /root/.hermes/logs/local-patches.log"
ok "patches applied (see log above; 'already applied' is success on re-run)"

# ---- 3. config.yaml session_reset -> idle (idempotent, comment-preserving) -
say "3/5 config.yaml session_reset.mode -> idle"
sshq 'python3 - <<PY
import re, time, shutil
CFG="/root/.hermes/config.yaml"
s=open(CFG).read()
m=re.search(r"(?ms)^session_reset:\n(?:[ \t]+.*\n)*", s)
if not m:
    print("  no session_reset block; leaving config untouched"); raise SystemExit(0)
block=m.group(0)
# Find the single mode: line inside the block.
modes=re.findall(r"(?m)^[ \t]+mode:.*$", block)
if len(modes)!=1:
    print(f"  expected exactly one mode: key in session_reset (found {len(modes)}); leaving untouched"); raise SystemExit(0)
# Replace ONLY the value token, preserving indentation and any trailing comment.
def repl(mo):
    return mo.group("pre")+"idle"+(mo.group("cmt") or "")
new_block, n = re.subn(
    r"(?m)^(?P<pre>[ \t]+mode:[ \t]*)([\x27\"]?)[A-Za-z_]+([\x27\"]?)(?P<cmt>[ \t]*(?:#.*)?)$",
    repl, block, count=1)
if n!=1:
    print("  could not parse mode: value; leaving untouched"); raise SystemExit(0)
if new_block==block:
    print("  already mode: idle (no change)"); raise SystemExit(0)
shutil.copy2(CFG, CFG+".bak.hardening."+time.strftime("%Y%m%d_%H%M%S"))
open(CFG,"w").write(s[:m.start()]+new_block+s[m.end():])
print("  session_reset.mode set to idle (backup written)")
PY'
ok "session_reset tuned"

# ---- optional: record owner chat id for alerts ---------------------------
if [ -n "$OWNER_CHAT" ]; then
  sshq "grep -q '^HERMES_OWNER_CHAT_ID=' /root/.hermes/.env 2>/dev/null || echo 'HERMES_OWNER_CHAT_ID=$OWNER_CHAT' >> /root/.hermes/.env"
  ok "owner chat id recorded for watchdog/drift alerts"
fi

# ---- 4. reliability watchdogs + crons (provider-aware) -------------------
say "4/5 reliability watchdogs"
sshq "mkdir -p /root/.hermes/scripts /root/.hermes/logs"
# Dedup by the FULL script path (fixed-string match), then append. Idempotent and
# safe: -F means no regex, and the path is unique to our line.
add_cron(){ # $1 = full script path (dedup key), $2 = full cron line
  sshq "( crontab -l 2>/dev/null | grep -vF '$1'; echo '$2' ) | crontab -"
}
CODEX_REFRESH=/root/.hermes/scripts/codex_token_refresh.py
CODEX_UNFREEZE=/root/.hermes/scripts/codex_unfreeze.py
GOOGLE_MON=/root/.hermes/scripts/google_token_monitor.py
if [ "$HAS_CODEX" = 1 ]; then
  scpq "$SCRIPT_DIR/watchdogs/codex_token_refresh.py" "$CODEX_REFRESH"
  sshq "chmod +x $CODEX_REFRESH"
  add_cron "$CODEX_REFRESH" "0 */8 * * * cd /root/.hermes/hermes-agent && HERMES_HOME=/root/.hermes HOME=/root /root/.hermes/hermes-agent/venv/bin/python $CODEX_REFRESH >> /root/.hermes/logs/codex_token_refresh.cron.log 2>&1"
  ok "Codex token refresh cron (8h)"
  if [ "$CODEX_PRIMARY" = 1 ]; then
    scpq "$SCRIPT_DIR/watchdogs/codex_unfreeze.py" "$CODEX_UNFREEZE"
    sshq "chmod +x $CODEX_UNFREEZE"
    add_cron "$CODEX_UNFREEZE" "*/5 * * * * cd /root/.hermes/hermes-agent && HERMES_HOME=/root/.hermes HOME=/root /root/.hermes/hermes-agent/venv/bin/python $CODEX_UNFREEZE >> /root/.hermes/logs/codex_unfreeze.cron.log 2>&1"
    ok "Codex unfreeze cron (5m, primary brain)"
  else
    warn "Codex is fallback-only — skipping the 5-min unfreeze (not worth the ticks)"
  fi
else
  warn "brain is not Codex — skipping Codex watchdogs"
fi
if [ "$HAS_GOOGLE" = 1 ]; then
  scpq "$SCRIPT_DIR/watchdogs/google_token_monitor.py" "$GOOGLE_MON"
  add_cron "$GOOGLE_MON" "30 9 * * * cd /root/.hermes/hermes-agent && HERMES_HOME=/root/.hermes HOME=/root /root/.hermes/hermes-agent/venv/bin/python $GOOGLE_MON >> /root/.hermes/logs/google_token_monitor.cron.log 2>&1"
  ok "Google OAuth smoke-alarm cron (daily 09:30)"
else
  warn "no Google OAuth wired — skipping Google monitor"
fi

# ---- 5. restart + verify -------------------------------------------------
if [ "$RESTART" = 1 ]; then
  say "5/5 restart gateway + verify"
  if sshq 'journalctl -u hermes-gateway --since "90 sec ago" 2>/dev/null | grep -qiE "agent start|processing message|tool_call"'; then
    warn "gateway looks busy — re-run with the box idle, or restart manually:"
    warn "  ssh $HOST systemctl restart hermes-gateway"
  else
    sshq 'systemctl restart hermes-gateway; for i in $(seq 1 15); do [ "$(systemctl is-active hermes-gateway)" = active ] && break; sleep 2; done'
    if [ "$(sshq 'systemctl is-active hermes-gateway')" != active ]; then
      echo "  FATAL: gateway did not come back active after restart — check: ssh $HOST journalctl -u hermes-gateway -n 50"
      exit 1
    fi
    sshq 'echo "  active=$(systemctl is-active hermes-gateway)"; echo "  session_reset.mode=$(awk "/^session_reset:/{f=1} f&&/mode:/{print \$2; exit}" /root/.hermes/config.yaml)"; python3 -c "import json;d=json.load(open(\"/root/.hermes/gateway_state.json\"));print(\"  telegram=\"+d[\"platforms\"][\"telegram\"][\"state\"])" 2>/dev/null'
    ok "restarted + verified"
  fi
else
  say "5/5 skipping restart (--no-restart). Apply with: ssh $HOST systemctl restart hermes-gateway"
fi
say "hardening complete on $HOST"
