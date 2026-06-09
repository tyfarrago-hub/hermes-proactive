---
name: hermes-proactive
description: Set up a proactive Hermes Agent partner from scratch. Provisions VPS-side Hermes, Telegram supergroup with Dashboard and Decisions topics, Mac iMessage relay, Google Workspace OAuth, watchers that detect scheduling intent in iMessage and reply-needed Gmail threads, and a proposal-execution loop that lets you say "yes <id>" to actually create calendar events or send drafted emails. Use when a user wants Hermes to act like a real partner, not just a notifier.
---

# hermes-proactive

Turnkey installer for the proactive Hermes pipeline. Takes a fresh Mac + a fresh VPS to a working state where Hermes:

- Sees your iMessages (read-only via chat.db relay)
- Sees your Gmail (read + send)
- Has Calendar write access
- Watches both for actionable events
- Mints proposals you confirm with one Telegram reply
- Actually executes calendar adds and email sends when you say "yes"

## When the agent loads this skill

Boot sequence:

1. Read `~/.hermes-proactive/state.json`. If missing, treat all phases as pending.
2. Run `scripts/check_setup.py` — it confirms which phases are green and surfaces the next blocker as ONE concrete next action.
3. Execute the next pending phase by invoking `scripts/phase_<x>_*.py`. Each phase is idempotent.
4. After every phase, re-run `check_setup.py` to update state and choose the next move.
5. Stop and ask the user only when a phase requires a manual UI step (BotFather, Google consent, FDA grant, choosing a VPS provider).

The agent is the conductor. The skill scripts are the instruments. Don't free-style — call the phase scripts in order, let them update state.

## Modes

- **`setup`** (default) — run pending phases until either complete or blocked on a manual step.
- **`status`** — show current state, no changes.
- **`reset <phase_letter>`** — wipe state for a single phase so it re-runs (e.g. `reset g` to redo Google OAuth).
- **`uninstall`** — remove launchd plist, remove cron jobs from VPS, remove libs from VPS, remove USER.md section. Does NOT delete Hermes itself or your Telegram supergroup.

## File map (skill internals)

```
hermes-proactive/
├── SKILL.md                    this file
├── README.md                   github-facing
├── install.sh                  curl-target installer
├── config.example.json         skill config template
├── setup.md                    human-readable phase guide
├── scripts/
│   ├── check_setup.py          master gate, called every boot
│   ├── lib/
│   │   ├── state.py            ~/.hermes-proactive/state.json io
│   │   ├── ssh.py              ssh + scp wrappers
│   │   ├── ansi.py             green/red/yellow output
│   │   └── chat_db.py          chat.db reader (from carbon-voiceprint)
│   └── phase_a_mac_prereqs.py …phase_j_smoke.py
├── bridge/                     mac iMessage bridge files (installed to ~/.hermes-proactive/bridge)
├── vps_libs/                   files SCP'd to /root/.hermes/lib/
├── prompts/                    cron job prompts
├── snippets/                   reusable text fragments (USER.md addition)
└── docs/
    ├── full-build-guide.md     blank-slate guide to the FULL system (everything past the core)
    ├── architecture.md
    ├── troubleshooting.md
    └── uninstall.md
```

## Beyond the core

The ten phases install the **core**: Hermes + Telegram (Dashboard + Decisions) + iMessage + Google
+ the two watchers + the approval loop. That is the spine.

When the user wants more than the core — a brain repo / Living CRM, WhatsApp, the Gmail emoji
labeler or unsubscribe audit, Plaid, Stripe, the persistent VPS browser, the full cron map, or the
USER/SOUL/MEMORY profile system — read `docs/full-build-guide.md` and follow the module + sequence
there. Those modules are documented (not auto-installed); add them one at a time, after the core is
green and quiet.

## State machine

State file: `~/.hermes-proactive/state.json`. Schema:

```json
{
  "version": 1,
  "started_at": "...iso...",
  "vps": {"host": "1.2.3.4", "ssh_key": "~/.ssh/id_ed25519"},
  "telegram": {"bot_token_field": "in_keychain", "bot_username": "@foo_bot",
               "supergroup_chat_id": "-100...", "dashboard_thread_id": 3,
               "decisions_thread_id": 7},
  "google": {"client_secret_path": "~/.hermes-proactive/client_secret.json",
             "token_path": "~/.hermes-proactive/token.json",
             "project_id": "...", "client_id": "..."},
  "phases": {
    "a_mac_prereqs": "complete",
    "b_vps":         "complete",
    "c_telegram":    "complete",
    "d_imessage":    "complete",
    "e_supergroup":  "complete",
    "f_routing":     "complete",
    "g_oauth":       "complete",
    "h_libs":        "complete",
    "i_user_md":     "complete",
    "j_smoke":       "complete"
  }
}
```

Phase status values: `pending` (default), `in_progress`, `blocked` (with `blocker` field), `complete`.

## Hard rules

- **Never write secrets via shell heredoc.** Always use the `Write` tool or Python file IO. Shell history is permanent.
- **Always ssh-copy-id, never paste private keys.** Bridge SSH key gets generated on the user's Mac, public half copied to VPS.
- **Verify before asserting.** Each phase ends with a smoke test that confirms its own work, not the user's vibe.
- **One phase at a time.** Don't run phase H before phase G is complete — the libs need the OAuth token to even import.
- **macOS only on the user side.** chat.db is Apple-only. Bail in `phase_a` with a clean message if Linux/Windows.
- **No em dashes** in any user-facing output.

## Failure handling

If any phase fails:
1. Phase script writes `blocked` + `blocker` field to state.
2. Returns non-zero exit code.
3. Master `check_setup.py` re-reads state, prints the blocker as the next action.
4. Agent surfaces blocker to user with the suggested fix, waits.
5. User fixes, says "continue", agent re-runs the same phase. Idempotent.

The skill never auto-retries. Retries are user-driven so noise from real failures is visible.

## Linked skills

- `~/.claude/skills/carbon-voiceprint/` — source of `chat_db.py`. Don't dual-maintain — copy is intentional, lives separately.
- `~/Developer/browser-harness/` — used by phase E and G when the user has it installed. Falls back to `claude-in-chrome` MCP if not.
