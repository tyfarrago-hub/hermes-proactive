# Hermes Hardening Layer

Reliability + context-awareness hardening for a Hermes Agent install. These are
the durable fixes that turn a stock Hermes into one that stays up and actually
understands replies. Apply after the core (phases A–J) is green and quiet.

All of it is **update-safe**: the two gateway source patches live in
`/root/.hermes/local-patches/` and are re-applied automatically on every gateway
start via a systemd `ExecStartPre`, so `hermes update` (a `git reset --hard`)
can't silently wipe them.

## Install

```bash
# one command, idempotent, provider-aware, safe to re-run:
./install_hardening.sh <ssh_host> --owner-chat <telegram_chat_id>

# read-only state report (changes nothing):
./install_hardening.sh <ssh_host> --check
```

`<ssh_host>` is the ssh alias/`user@host` for the target Hermes box. `--owner-chat`
is the Telegram chat id that watchdog + patch-drift alerts go to (written to
`/root/.hermes/.env` as `HERMES_OWNER_CHAT_ID`). The installer detects the
provider set and only installs the watchdogs that apply.

## What it installs

| Piece | File(s) | Why |
|-------|---------|-----|
| **Update-safe patch machinery** | `apply.sh`, `systemd/local-patches.conf` | Re-applies local patches on every gateway start so `hermes update` can't wipe them. The meta-pattern everything else rides on. |
| **Reply-context anchor** | `patches/reply-context-anchor.patch` + `config/session_reset.snippet.yaml` | Plain-text replies anchor to "the message directly above." Kills the #1 "Hermes answered something unrelated" bug. See below. |
| **Proactive-message context** | `patches/mirror-cron-deliveries.patch` | Cron/proactive deliveries (briefs, nudges, watcher output) get mirrored into the chat's session transcript, so a short reply like "remind me" has context. |
| **Image attachments work** | `patches/media-root-home.patch` (+ optional `HERMES_MEDIA_TRUST_RECENT_SECONDS`) | A root-homed Hermes ($HOME=/root) blanket-denies its own `/root` home in the media-delivery guard, which kills the recency-trust hatch, so every freshly generated image (QR, carousel, thumbnails) is silently dropped and only text is sent. This un-breaks it: `/root` is no longer treated as a forbidden system path (`.hermes` is added to the credential denylist instead). Images attach first-try; credentials stay blocked (they aren't media extensions, and `.ssh`/`.config`/`.hermes` remain denied). See below. |
| **Provider fallback chain** | `config/fallback_providers.snippet.yaml` | One provider hiccup (429 / expired token / failed compression) no longer takes the whole brain dark. |
| **Codex token refresh** | `watchdogs/codex_token_refresh.py` (8h cron) | Force-refreshes the Codex OAuth token inside its ~24h life, from a *system* cron independent of the brain. Installed whenever Codex is anywhere in the chain (primary or fallback). |
| **Codex unfreeze** | `watchdogs/codex_unfreeze.py` (5m cron) | Clears a stale `STATUS_EXHAUSTED` freeze so a transient 429 self-heals in minutes instead of staying dark. Installed only when Codex is the **primary** brain (pointless ticks for a fallback-only Codex). |
| **Google OAuth smoke alarm** | `watchdogs/google_token_monitor.py` (daily cron) | In-memory refresh test per Google account; alerts the owner the moment a token dies. Google-OAuth-only. |
| **Media allow dirs** (optional) | `systemd/media-allow.conf.example` | Lets the gateway read image dirs Hermes generates/caches. |

## The reply-context fix (most important)

**Symptom:** the user replies in plain text to something Hermes said, and Hermes
answers an unrelated, older topic.

**Root cause:** `session_reset.mode: both` with `at_hour` fires a DAILY hard reset
that ends the live session. A reply after that boundary opens a fresh EMPTY
session — the message directly above is gone — so the agent free-associates (it
will autonomously call `session_search` and latch onto a stale keyword match).

**Fix (two parts, both in this layer):**
1. `session_reset.mode: idle` (config) — removes the daily nuke; the conversation
   stays continuous through the day and only clears after a true long idle gap.
2. `reply-context-anchor.patch` — even when an idle reset *does* fire, the
   gateway captures the just-ended session's last message and injects it into the
   fresh session as an explicit `[Continuity note: the user is almost certainly
   replying to your last message: «…». Do NOT use session_search to guess …]`.

The patch touches `gateway/session.py` (capture `carryover_anchor` on reset) and
`gateway/run.py` (inject it at the auto-reset hook). Pure code, no secrets.

## Why generated images silently fail to send (media-root-home)

**Symptom:** Hermes says "here's the image / QR / carousel preview" but no image arrives; it takes a few back-and-forths to notice. The gateway logs `Skipping unsafe MEDIA directive path outside allowed roots`.

**Root cause:** the gateway only attaches files that are (a) under an explicit allowlist, or (b) freshly produced (recency-trust). Recency-trust is gated by a denylist that blanket-blocks the `/root` prefix. A Hermes running as **root** has `$HOME=/root`, so *everything it generates* (carousel slides, the WhatsApp QR, thumbnails) lives under `/root` → recency-trust is dead → only a few allowlisted cache dirs work → most generated images are dropped, and the agent is never told, so it claims success.

**Fix (`patches/media-root-home.patch`):** stop treating the agent's own home (`/root`) as a forbidden *system* path, and add `.hermes` to the in-home credential denylist instead. Recency-trust then works for any freshly generated image anywhere under `/root`. Credentials stay unattachable: they are `.env`/`.json`/`.yaml`/`.db` files the media filter never matches, and `.ssh`/`.aws`/`.config`/`.hermes` remain denied. Pair with `HERMES_MEDIA_TRUST_RECENT_SECONDS=1800` (see `systemd/media-allow.conf.example`) so slow renders still attach. Only relevant when Hermes runs as root — the installer applies it regardless (harmless on non-root installs, where `/root` was never the agent home).

## Verify

```bash
./install_hardening.sh <ssh_host> --check
# expect: both patches APPLIED, ExecStartPre present, session_reset.mode idle,
#         3/3 (or provider-appropriate) watchdogs present, gateway active.
```

Spot-checks on the box:
- `tail /root/.hermes/logs/local-patches.log` → patches "already applied".
- `grep -A2 '^session_reset:' /root/.hermes/config.yaml` → `mode: idle`.
- `crontab -l | grep -E 'codex_|google_token'` → the relevant watchdogs.
- `cat /root/.hermes/gateway_state.json` → `telegram: connected`.

## Manual apply (if not using the installer)

1. `scp apply.sh patches/*.patch` → `/root/.hermes/local-patches/`; `chmod +x apply.sh`.
2. `scp systemd/local-patches.conf` → `/etc/systemd/system/hermes-gateway.service.d/`; `systemctl daemon-reload`.
3. Run `/root/.hermes/local-patches/apply.sh` (applies both patches to the working tree).
4. Edit `/root/.hermes/config.yaml`: under `session_reset:` set `mode: idle`.
5. Merge `config/fallback_providers.snippet.yaml` into `config.yaml` (each fallback needs a working credential in the pool).
6. `scp` the relevant `watchdogs/*.py` → `/root/.hermes/scripts/`; add the matching lines from `crontab.snippet` to root's crontab.
7. `systemctl restart hermes-gateway` (while the chat is idle), then run the verify checks.

## Provider auth recipes (referenced by the watchdogs)

- **Codex pool refresh (manual recovery):** `from agent.credential_pool import load_pool; p=load_pool('openai-codex'); p.reset_statuses(); p.select(); p.try_refresh_current()` — run with `HERMES_HOME=/root/.hermes` and the gateway venv.
- **Anthropic fallback credential:** mint an interactive-login OAuth grant via the PKCE flow (authorize at `claude.ai/oauth/authorize`, exchange at `console.anthropic.com/v1/oauth/token`, send a non-default User-Agent or Cloudflare 403s) and write it into the anthropic credential pool. An interactive-login OAuth token billed via `Authorization: Bearer` runs on the subscription ($0); a `setup-token`/API key bills the org's API balance — do not use those for a subscription-backed brain.
- **Why there is no Anthropic token watchdog:** the anthropic pool entry self-refreshes on use — the adapter runs a network `grant_type=refresh_token` refresh and persists the rotated tokens whenever the credential is exercised. So as long as the fallback is actually in the chain (and therefore exercised), it self-heals; no cron is needed. The only failure mode is a fallback that is *configured but never reached* — keep at least one real call path through it. Codex, by contrast, needs the cron because its token expires on a fixed ~24h clock regardless of use.

## If a patch drifts after `hermes update`

`apply.sh` runs before every gateway start and logs to `/root/.hermes/logs/local-patches.log`. If a patch ever logs `DOES NOT APPLY (context drift)` (and Telegrams the owner), upstream changed the code the patch targets:
1. `cd /root/.hermes/hermes-agent && git log --oneline -5` to see what moved.
2. Open the failing `.patch`, locate the new code around the same function, and either re-create the patch against the current source or delete it if Hermes now has the behavior natively.
3. Re-run `/root/.hermes/local-patches/apply.sh` and confirm the log says `re-applied`/`already applied`.

## Notes / boundaries

- The watchdogs assume the standard Hermes home `/root/.hermes` and the gateway venv at `/root/.hermes/hermes-agent/venv/bin/python` (the installer preflights both).
- `apply.sh` runs on EVERY gateway start, not just after an update — that is intentional (patches also survive crashes and manual git ops). It is idempotent; the log grows ~1 line per restart, trim it if it gets large.
- `at_hour` in the session_reset config is inert under `mode: idle`; it is preserved only so you can flip back to `mode: both` easily.
- **Generic only.** This layer is Hermes *infrastructure* hardening. The owner's automations are NOT part of it and must never be bundled into a client install: finance/`plaid` alerts, market bots, Instagram/social pipelines, personal iMessage style/reply scripts, any persona rulebook (e.g. an operator channel prompt), and the owner's brain repo. Those are per-owner; build them separately after the hardened core is green.
- **Optional debug tweak (not bundled):** adding `exc_info=True` to the provider-error `logger.error(...)` call in `agent/conversation_loop.py` gives full tracebacks on provider failures. It is a one-line cosmetic aid, easily wiped by `hermes update`; package it as another `local-patches/*.patch` if you want it to persist.
