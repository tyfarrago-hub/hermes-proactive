#!/usr/bin/env bash
# hermes-proactive curl-target installer.
# Usage: curl -fsSL https://raw.githubusercontent.com/tyfarrago-hub/hermes-proactive/v0.1.2/install.sh | bash
set -euo pipefail

TARGET="${HERMES_PROACTIVE_TARGET:-$HOME/.claude/skills/hermes-proactive}"
REPO="${HERMES_PROACTIVE_REPO:-https://github.com/tyfarrago-hub/hermes-proactive.git}"

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "hermes-proactive currently requires macOS for the iMessage bridge."
  echo "Linux/Windows users: open an issue, we'll consider a Telegram-only mode."
  exit 1
fi

find_python() {
  local candidates=(
    python3.14 python3.13 python3.12 python3.11 python3
    /opt/homebrew/bin/python3.14 /opt/homebrew/bin/python3.13
    /opt/homebrew/bin/python3.12 /opt/homebrew/bin/python3.11 /opt/homebrew/bin/python3
    /usr/local/bin/python3.14 /usr/local/bin/python3.13
    /usr/local/bin/python3.12 /usr/local/bin/python3.11 /usr/local/bin/python3
  )
  local py
  for py in "${candidates[@]}"; do
    if command -v "$py" >/dev/null 2>&1; then
      py_path="$(command -v "$py")"
      if "$py_path" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' >/dev/null 2>&1; then
        printf '%s\n' "$py_path"
        return 0
      fi
    elif [[ -x "$py" ]]; then
      if "$py" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' >/dev/null 2>&1; then
        printf '%s\n' "$py"
        return 0
      fi
    fi
  done
  return 1
}

PYTHON_BIN="$(find_python || true)"
if [[ -z "$PYTHON_BIN" ]]; then
  echo "Python 3.11+ required. Install with: brew install python@3.12"
  exit 1
fi
PY_VER="$("$PYTHON_BIN" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}")')"

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
echo "Python for setup checks: $PYTHON_BIN ($PY_VER)"
echo
echo "Next: open a Claude Code session and ask: 'set up hermes-proactive'"
echo "Or run the setup gate manually:  $PYTHON_BIN $TARGET/scripts/check_setup.py"
