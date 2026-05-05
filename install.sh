#!/usr/bin/env bash
# hermes-proactive curl-target installer.
# Usage: curl -fsSL https://raw.githubusercontent.com/<owner>/hermes-proactive/main/install.sh | bash
set -euo pipefail

TARGET="${HERMES_PROACTIVE_TARGET:-$HOME/.claude/skills/hermes-proactive}"
REPO="${HERMES_PROACTIVE_REPO:-https://github.com/tyfarrago-hub/hermes-proactive.git}"

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "hermes-proactive currently requires macOS for the iMessage bridge."
  echo "Linux/Windows users: open an issue, we'll consider a Telegram-only mode."
  exit 1
fi

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 not found. Install with: xcode-select --install   (or: brew install python@3.12)"
  exit 1
fi

PY_VER="$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
MAJ="$(echo "$PY_VER" | cut -d. -f1)"
MIN="$(echo "$PY_VER" | cut -d. -f2)"
if (( MAJ < 3 || (MAJ == 3 && MIN < 11) )); then
  echo "Python 3.11+ required. Detected: $PY_VER"
  exit 1
fi

if [[ -d "$TARGET/.git" ]]; then
  echo "Updating existing checkout at $TARGET"
  git -C "$TARGET" pull --ff-only
elif [[ -d "$TARGET" ]]; then
  echo "$TARGET exists but is not a git checkout."
  echo "Move or remove it, then re-run."
  exit 1
else
  echo "Cloning $REPO into $TARGET"
  mkdir -p "$(dirname "$TARGET")"
  git clone "$REPO" "$TARGET"
fi

chmod +x "$TARGET/scripts/check_setup.py" 2>/dev/null || true
chmod +x "$TARGET/scripts/phase_"*.py 2>/dev/null || true
chmod +x "$TARGET/bridge/run_once.sh" "$TARGET/bridge/push_to_hermes.sh" 2>/dev/null || true

echo
echo "hermes-proactive installed to $TARGET"
echo
echo "Next: open a Claude Code session and ask: 'set up hermes-proactive'"
echo "Or run the setup gate manually:  python3 $TARGET/scripts/check_setup.py"
