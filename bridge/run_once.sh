#!/usr/bin/env bash
# Single end-to-end pass: export iMessages, push to VPS.
# Reads VPS_HOST + SSH_KEY from this file's siblings (the launchd plist exports them).
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
OUT="/tmp/hermes-proactive-imessage.json"

VPS_HOST="${HERMES_VPS_HOST:-${VPS_HOST:-}}"
SSH_KEY="${HERMES_SSH_KEY:-${SSH_KEY:-$HOME/.ssh/id_ed25519}}"

if [[ -z "$VPS_HOST" ]]; then
  echo "HERMES_VPS_HOST not set; bridge cannot push" >&2
  exit 1
fi

# Pick a Python that has stdlib sqlite — the system python3 is fine.
PY="${HERMES_PY:-/usr/bin/python3}"

"$PY" "$DIR/export_imessage.py" "$OUT"
EXPORT_RC=$?

if [[ $EXPORT_RC -gt 1 ]]; then
  echo "export failed (rc=$EXPORT_RC); skipping push" >&2
  exit $EXPORT_RC
fi

"$DIR/push_to_hermes.sh" "$OUT" "$VPS_HOST" "$SSH_KEY"
