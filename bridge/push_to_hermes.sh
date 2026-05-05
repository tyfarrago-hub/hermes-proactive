#!/usr/bin/env bash
# Push the local imessage.json to Hermes VPS via SCP + atomic rename.
# Args: $1 = local path, $2 = vps host (user@host), $3 = ssh key path
set -euo pipefail

LOCAL="${1:-/tmp/imessage.json}"
HOST="${2:?vps host required}"
KEY="${3:?ssh key path required}"

if [[ ! -f "$LOCAL" ]]; then
  echo "missing $LOCAL" >&2
  exit 1
fi

REMOTE="/root/.hermes/inbox/imessage.json"
REMOTE_DIR="/root/.hermes/inbox"
TMP_REMOTE="${REMOTE}.tmp.$$"

# Ensure the remote inbox dir exists. Idempotent. Cheap one-shot.
ssh -q -o BatchMode=yes -o ConnectTimeout=15 -i "$KEY" "$HOST" "mkdir -p ${REMOTE_DIR}"

scp -q -o BatchMode=yes -o ConnectTimeout=15 -i "$KEY" "$LOCAL" "${HOST}:${TMP_REMOTE}"
ssh -q -o BatchMode=yes -o ConnectTimeout=15 -i "$KEY" "$HOST" "mv ${TMP_REMOTE} ${REMOTE}"
echo "pushed $LOCAL -> ${HOST}:${REMOTE}"
