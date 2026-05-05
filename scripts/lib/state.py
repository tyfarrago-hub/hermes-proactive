"""State machine for hermes-proactive setup.

Single source of truth: ~/.hermes-proactive/state.json. Read every boot,
written by each phase. Schema documented in SKILL.md.
"""

from __future__ import annotations

import datetime as _dt
import json
import os
from pathlib import Path
from typing import Any

ROOT = Path.home() / ".hermes-proactive"
STATE_PATH = ROOT / "state.json"
CONFIG_PATH = ROOT / "config.json"

PHASES = (
    "a_mac_prereqs",
    "b_vps",
    "c_telegram",
    "d_imessage",
    "e_supergroup",
    "f_routing",
    "g_oauth",
    "h_libs",
    "i_user_md",
    "j_smoke",
)


def _now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat()


def _empty_state() -> dict[str, Any]:
    return {
        "version": 1,
        "started_at": _now_iso(),
        "vps": {},
        "telegram": {},
        "google": {},
        "phases": {p: "pending" for p in PHASES},
    }


def ensure_dir() -> None:
    ROOT.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(ROOT, 0o700)
    except OSError:
        pass


def read() -> dict[str, Any]:
    ensure_dir()
    if not STATE_PATH.exists():
        return _empty_state()
    try:
        return json.loads(STATE_PATH.read_text())
    except json.JSONDecodeError:
        return _empty_state()


def write(data: dict[str, Any]) -> None:
    ensure_dir()
    STATE_PATH.write_text(json.dumps(data, indent=2))
    try:
        os.chmod(STATE_PATH, 0o600)
    except OSError:
        pass


def update(updates: dict[str, Any]) -> dict[str, Any]:
    """Shallow-merge updates into top-level state. Returns updated state.

    Phase status writes via mark_phase, not this.
    """
    data = read()
    for k, v in updates.items():
        if isinstance(v, dict) and isinstance(data.get(k), dict):
            data[k].update(v)
        else:
            data[k] = v
    write(data)
    return data


def mark_phase(phase: str, status: str, blocker: str | None = None) -> dict[str, Any]:
    if phase not in PHASES:
        raise ValueError(f"unknown phase {phase!r}; valid: {PHASES}")
    if status not in ("pending", "in_progress", "blocked", "complete"):
        raise ValueError(f"invalid status {status!r}")
    data = read()
    data["phases"][phase] = status
    if status == "blocked" and blocker:
        data.setdefault("blockers", {})[phase] = blocker
    elif phase in data.get("blockers", {}):
        del data["blockers"][phase]
    write(data)
    return data


def reset_phase(phase: str) -> dict[str, Any]:
    return mark_phase(phase, "pending")


def next_pending() -> str | None:
    data = read()
    for p in PHASES:
        if data["phases"].get(p) != "complete":
            return p
    return None


def is_complete(phase: str) -> bool:
    return read()["phases"].get(phase) == "complete"


def all_complete() -> bool:
    data = read()
    return all(data["phases"].get(p) == "complete" for p in PHASES)


def read_config() -> dict[str, Any]:
    if not CONFIG_PATH.exists():
        return {}
    try:
        return json.loads(CONFIG_PATH.read_text())
    except json.JSONDecodeError:
        return {}


def write_config(data: dict[str, Any]) -> None:
    ensure_dir()
    CONFIG_PATH.write_text(json.dumps(data, indent=2))
    try:
        os.chmod(CONFIG_PATH, 0o600)
    except OSError:
        pass
