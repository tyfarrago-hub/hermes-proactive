# Full Hermes Build Guide

The one-line installer (see the [README](../README.md)) gets you the **core**: a VPS running
Hermes, a Telegram command center, an iMessage relay, Google Workspace OAuth, two watchers, and
the proposal/approval loop. That core is the spine everything else hangs off.

This guide is the rest of the system. It is the full architecture of a mature Hermes setup,
written as a blank slate so you can recreate every capability around **your own** accounts,
messages, calendar, email, and life context.

It is not a clone. There are no tokens, browser profiles, message histories, or private notes
in here. You bring your own accounts and wire them into the same shapes.

Order of operations: get the core install working and quiet first. Then apply the **hardening
layer** (`../hardening/` — `install_hardening.sh` + `HARDENING.md`), which keeps Hermes up and
makes it understand replies: update-safe gateway patches (reply-context anchor + proactive-message
mirroring), `session_reset.mode: idle` (removes the daily reset that severs the message a user is
replying to), a provider fallback chain, and reliability watchdogs. Only after the core is green
and hardened, add modules from this guide one at a time, in the sequence at the end. Do not turn
on ten proactive jobs at once.

---

## 0. Mental model

Hermes is a personal operating system, not a chatbot.

It does four things:

1. **Reads trusted context** — calendar, iMessage, WhatsApp, Gmail, brain notes, CRM, bank,
   revenue, project files.
2. **Turns messy signals into clear actions** — reply drafts, calendar events, follow-ups,
   money alerts, decision cards.
3. **Runs continuously** through an internal cron scheduler and message gateways.
4. **Remembers** preferences, corrections, and rules so you do not repeat yourself.

The goal is not maximum automation. The goal is high-trust leverage.

The default posture is **draft-first**. Hermes can read, summarize, classify, label, and draft
anything. It must not send messages, spend money, place orders, or mutate important records
without explicit approval.

Bad version: a bot that reads everything and spams you.

Good version: an operator that reads quietly, understands context, and only interrupts when
there is leverage, risk, money, care, or a real decision.

---

## 1. The autonomy ladder

Pick a level per capability. This is the single most important design choice in the system.

| Level | What it does | Example |
| --- | --- | --- |
| **Observe** | Read, classify, label, store. No human visibility. | Gmail emoji labeler |
| **Draft** | Compose a candidate, store it as a proposal, ping you. | reply-draft watchers |
| **Execute on approval** | Same as Draft, but resolves to a real action on `yes <id>`. | the core calendar/email loop |
| **Execute autonomous** | Acts without per-event approval. Only for low-risk, well-scoped actions on a pre-approved template. | (enable last, sparingly) |

### The proposal loop (the only path to an outbound action)

1. A cron watcher decides an action is warranted.
2. It writes a record to `/root/.hermes/proposals.json` with a short id.
3. It posts a card into your Decisions topic with the proposed action and a preview.
4. You reply in-thread: `yes <id>` to act, `edit <id> <new body>` to revise, `no <id>` to drop.
5. `/root/.hermes/lib/proposal_executor.py` resolves it and logs to `proposal_log.jsonl`.

The core installer wires this loop end-to-end for calendar adds and email replies. Every module
below either feeds proposals into the same loop or stays at Observe/Draft.

### Hard approval gates

Hermes prepares, but asks before: sending texts, sending emails, placing orders, buying
anything, cancelling subscriptions, deleting important files, creating invoices, making calendar
events from vague details, contacting leads, or changing CRM identity mappings when uncertain.

Good operating phrase for the agent: **"Built / prepared / drafted. No checkout, send, or action
taken."**

---

## 2. The brain repo + file-based Living CRM

The brain is the durable context layer. It is where knowledge lives in files, not just chat
history. Both Hermes (on the VPS) and any Mac-side agent (Claude Code, Codex) read and write here.

### Locations

```
Mac:    ~/brain
VPS:    /root/brain
Remote: a PRIVATE GitHub repo you own
```

### Structure

```
brain/
  people/           # one md per person, relationship state
  companies/
  crm/
    views/          # generated dashboards (dashboard.md, opportunity-pipeline.md, next-actions.md)
  org/
    money-board.md
    decision-queue.md
  projects/
    _registry.md
    _archive/
  bridge/           # async handoff between machines/agents
  inbox/
  journal/
  scripts/          # the CRM ingest + view-rebuild scripts
```

### Sync mechanics

Keep Mac and VPS in sync through the private GitHub repo. A simple, robust pattern:

- **Mac → GitHub**: a small `brain_sync.sh` that commits and pushes, scheduled via launchd every
  few minutes (and runnable on demand). Use `git fetch` + `git merge --ff-only` and fail loudly on
  conflicts rather than auto-merging.
- **GitHub → VPS**: a single Linux cron entry on the VPS:

  ```cron
  */5 * * * * cd /root/brain && git pull origin main >> /var/log/brain-sync.log 2>&1
  ```

End-to-end propagation is up to ~10 minutes. For urgency, push on the Mac and pull on the VPS by
hand.

### The Living CRM

The CRM is just markdown files plus a few ingest scripts. Its job:

- create money and momentum,
- keep promised follow-ups from falling through,
- notice care obligations (family, friends),
- track real relationships,
- avoid clutter.

It **promotes** signals like paid client asks, warm intros, referral opportunities, invoice /
payment moments, testimonial chances, and unresolved promises. It **suppresses** noise like
promos, OTPs, receipt-only texts, reaction-only replies, and stale archived contacts.

Typical scripts under `brain/scripts/`:

```
ingest_daily_crm.py        # daily notes -> CRM state
ingest_imessage_crm.py     # iMessage feed -> CRM state
ingest_whatsapp_crm.py     # WhatsApp feed -> CRM state
rebuild_crm_views.py       # regenerate the dashboards
run_message_pipeline.sh    # health -> archive -> ingest -> views -> commit
```

### Security rule

The brain repo is **private but treat it as if it is already public**. No tokens, no secrets, no
raw bank payloads, no account numbers. Secrets live only in `/root/.hermes/.env` on the VPS.

---

## 3. USER.md / SOUL.md / MEMORY.md (the profile system)

These three files at the root of `/root/.hermes/` are what make drafts sound like you. Author them
**before** turning on any draft watcher, because every draft consults them.

```
USER.md     # who you are, what you do, how you communicate, what you do not want
SOUL.md     # identity, values, voice rules (drives brief + draft tone)
MEMORY.md   # corrections, preferences, stable facts learned over time
```

What goes in the profile: communication style, business context, key relationships, recurring
obligations, schedule norms, health/food preferences, revenue model, and any life principles that
should shape advice.

Memory stores stable facts and corrections. It should **not** store temporary task progress — put
that in files or let session history handle it. When the agent gets something consistently wrong,
the fix is a one-line correction in MEMORY.md, not a longer prompt.

The core installer appends a proposal-handler section to `USER.md`. Everything else here is yours
to write.

---

## 4. Telegram command center (beyond two topics)

The core ships two topics (Dashboard, Decisions). A mature setup uses a small set of
**buckets** (forum topics) so different kinds of output stay self-coherent. A proven layout:

| Bucket | Purpose | Outbound rule |
| --- | --- | --- |
| **Dashboard** | morning brief, nightly accomplishment, weekly pulses | auto-posts scheduled briefs |
| **Decisions** | the proposal flow lives here | `yes/edit/no <id>` resolve here |
| **Money** | revenue + spend signals | drafts proposals to Decisions, never auto-sends |
| **Projects** | project registry summaries | read-only summarizer |
| **Inbox / Triage** | raw dumps, message digests | default landing for unsorted input |
| **Archive / Later** | parked items | read-only |

Routing rules that keep it sane:

- The **source of truth** for topic ids is a small JSON on the VPS (e.g.
  `/root/.hermes/cron/command_center_topics.json`), not any doc. Update the doc and the JSON
  together.
- A trigger responds **inside the bucket it belongs to**, not where it was typed.
- Ambiguous triggers default to Dashboard.
- A job that has nothing useful to say outputs `[SILENT]` or delivers `local`. Never ping a topic
  with an empty update.

Setup pattern for each new topic: create it in the forum group, note its `message_thread_id`, add
it to the topics JSON, and reference it in the relevant cron job's `deliver` field as
`telegram:<chat_id>:<thread_id>`.

---

## 5. iMessage (CRM ingestion + reply drafts)

The core installer already relays iMessage read-only from the Mac to the VPS and runs the
scheduling watcher. To get the full value, add two things:

1. **CRM ingestion** — feed the same inbox JSON into `ingest_imessage_crm.py` so conversations
   update the Living CRM, not just the calendar watcher.
2. **A reply-draft watcher** — a cron job that finds human messages needing a reply and drafts
   them in your voice into the Decisions topic. Reading and drafting are automated; **sending stays
   approval-gated** (and, when you do build send, allowlist test contacts first and never auto-send
   anything emotional, family, romantic, or pricing-related).

Noise filter (drop): OTP codes, receipts, promos, carrier texts, reaction-only messages,
"lol / thanks / sounds good", malformed payloads, obvious spam.

Surface (keep): paid client asks, scheduling intent, invoices / payment requests, business leads,
care obligations.

---

## 6. WhatsApp

Separate from iMessage, same posture (read + draft automated, send approval-gated).

```
WhatsApp bridge (a Baileys-style daemon on the VPS, run as its own systemd service)
  -> writes a rolling JSON snapshot
  -> copy/symlink to /root/.hermes/inbox/whatsapp.json
  -> ingest_whatsapp_crm.py
  -> CRM views + a whatsapp-reply-draft watcher
```

Setup: provision the bridge as a systemd service, pair once by scanning the QR from your phone's
"Linked Devices", and confirm the snapshot refreshes. Then add the reply-draft watcher on a cron
(e.g. every 5 min, `local` delivery to start).

---

## 7. Gmail (beyond the core read+send)

The core gives you OAuth read + send + a reply watcher. Three additions make it a real inbox
operator:

### Multi-account

Use **per-account token directories** instead of overwriting one token:

```
/root/.hermes/google_accounts/<account-a>/google_token.json
/root/.hermes/google_accounts/<account-b>/google_token.json
```

The Google Workspace wrapper takes `--account <name>` to target one.

> **OAuth gotcha worth knowing up front:** an External OAuth app left in "Testing" publishing
> status force-expires consumer (gmail.com) refresh tokens every 7 days, so a personal account will
> silently die about weekly. Publish the consent screen to **Production** to stop that. Workspace
> accounts in the same org as the GCP project are not affected.

### Intelligent emoji labeler (Observe level)

A classifier script that applies **one** primary emoji label per message, e.g.:

```
💸 Money     🤖 AI/Software     🤝 People/Leads     📅 Schedule     📣 Marketing
```

Be conservative with human/business labels and separate direct mail from bulk marketing. Run it on
a cron (e.g. every 15 min, `local`).

### Unsubscribe audit (Draft level)

A job that finds low-value recurring senders and **asks** before unsubscribing. Hard rule: never
silently unsubscribe. Keep a per-operator allow-list of senders you always want.

### Sending

Send goes through the proposal loop: Hermes mints a `gmail.send` proposal into Decisions, you
approve with `yes <id>`. Optionally run outbound from a dedicated agent subdomain (separate
from-address with its own SPF/DKIM/DMARC) so agent mail is distinct from your primary inbox.

---

## 8. Calendar (watchers + the event-creation rule)

Calendar is the planning baseline — Hermes should check it before any timing or scheduling
suggestion. The core already has read + create.

Add **intent-watcher state** so the same thread is not proposed twice: small JSON files
(`calendar_intent_watcher_state.json`, etc.) track which message threads have already been examined
for scheduling intent. The reply-draft watchers consult them.

Event-creation rule: create an event only when date/time/location are concrete. If vague, mint a
proposal asking for the missing detail rather than guessing.

---

## 9. Plaid (read-only bank visibility)

Strictly read-only. This is for transaction sync, balances, and spend reports — never for moving
money.

```
PLAID_CLIENT_ID, PLAID_SECRET, PLAID_ENV   # in /root/.hermes/.env only
/root/.hermes/scripts/plaid/               # local Python toolkit + venv
/root/.hermes/.config/plaid/               # access tokens per institution (encrypted)
/root/.hermes/audit/plaid/transactions.sqlite3   # sanitized local cache
```

Setup: get keys from the Plaid dashboard (start in `sandbox`), write them to `.env`, connect each
institution through Plaid Link via the persistent-browser pattern (Section 11) — you log in to the
bank manually, the scripts exchange the public token and store the access token encrypted.

Cron ideas: monthly spend review, nightly money-movement report, optional purchase alerts. All
`local` to start.

Hard rules: product scope limited to `transactions`, `auth`, `balance`. No processor tokens, no
wallets, no account/routing-number flows. **Never** paste bank credentials, Plaid secrets, raw bank
payloads, or account/routing numbers into chat, notes, or the brain repo.

---

## 10. Stripe (revenue visibility)

For surfacing business events: new purchase, failed payment, cancellation risk, refund, high-value
lead, renewal issue.

Setup: create a **restricted** API key with minimal read scopes (`customers`, `invoices`,
`charges`, `subscriptions`, `payment_intents`, `payouts`, `disputes` read; add `promotion_codes`
write only if you want discount creation). Store as `STRIPE_RESTRICTED_KEY` in `.env`. Optionally
add a webhook for the events above with `STRIPE_WEBHOOK_SECRET`.

Posture: read-only for ingestion; write-with-approval for discount/refund flows. Never charge
customers, never modify subscription state, never expose keys.

---

## 11. Persistent VPS browser (logged-in services)

For any site needing login, 2FA, CAPTCHA, trusted cookies, or human checkout approval (groceries,
Plaid Link, etc.).

```
Real Chrome on the VPS, one durable profile per service
  -> you open a temporary noVNC session over a tunnel
  -> log in manually once
  -> close the tunnel
  -> Hermes reuses the trusted profile via CDP later
```

```
/root/.hermes/browser-profiles/<service>/   # Chrome user data dir
/root/.hermes/browser-sessions/<service>/    # session logs
```

Rules: Hermes may research, scan live prices, and build a cart up to the final screen. It must scan
live prices before any value claim. It must **not** place or pay for an order without explicit
approval. Never leave a public tunnel open longer than the login takes.

---

## 12. The full cron map + cadence philosophy

These are Hermes-managed jobs (`hermes cron list`), not Linux cron. A mature, deliberately sparse
map looks like this (delivery shown as visible-topic vs `local`):

```
morning-brief                  0 8 * * *      -> Dashboard (visible)
nightly-accomplishment-report  30 22 * * *    -> Dashboard (visible)
relationships-pulse            weekly         -> Dashboard (visible)
mood-mirror                    weekly         -> local
learning-loop                  weekly         -> local
soul-refinement                monthly        -> local (proposes edits to SOUL.md)
health-pulse                   daily morning  -> local
journal-pipeline               nightly        -> local
dream-pass                     overnight      -> local
Daily Living CRM ingestion     daily          -> local
Message feed watchdog + CRM    */5 * * * *    -> local
imessage-reply-draft-watcher   */2 or */15    -> Decisions (drafts)
whatsapp-reply-draft-watcher   */5 or */30    -> local
gmail-reply-watcher            */30 or hourly -> local (drafts)
Gmail emoji labeler            */15 or hourly -> local
Gmail unsubscribe audit        every 4h       -> local
monthly-finance-spending-review monthly       -> Money (visible)
nightly money movement report  nightly        -> local
```

### Cadence philosophy (learned the hard way)

- **Start sparse.** Only the morning brief, nightly accomplishment, weekly pulses, and monthly
  finance review should be *visible*. Everything else delivers `local` and is read on demand.
- **Cadence is the cost lever, not model choice.** A swarm of sub-5-minute watchers, each spinning a
  full context-heavy agent, is what drains an LLM plan and triggers rate limits. If costs spike,
  slow the watchers before you touch the model.
- **A job with nothing to say must say nothing** — output `[SILENT]` or deliver `local`.
- Add proactive jobs one at a time, only after the quiet baseline holds.

---

## 13. MCP integration (talk to Hermes from Claude Code)

Expose Hermes as a live MCP server in your Mac-side Claude Code by adding a block to `~/.claude.json`:

```json
"hermes": {
  "command": "ssh",
  "args": ["root@<your-vps>", "/root/.local/bin/hermes", "mcp", "serve", "--accept-hooks"],
  "env": { "CLAUDE_MCP_TIMEOUT": "30000" }
}
```

That gives you tools like `channels_list`, `conversations_list`, `messages_read`,
`messages_send`, `events_poll`, `attachments_fetch`, and `permissions_respond` from inside Claude
Code. Use the MCP channel for live calls; use the `brain/bridge/` markdown files for async handoffs
that can wait.

---

## 14. Skills and procedural memory

Skills live at `/root/.hermes/skills/<topic>/<skill>/` — a `SKILL.md` plus scripts. They are
reusable procedures the agent invokes.

Rule of thumb:

- **Memory** stores facts and preferences.
- **Skills** store procedures and workflows.
- **Files** (the brain repo) store durable project/relationship context.

If Hermes solves something complicated, save the workflow as a skill so it does not re-derive it.

---

## 15. Provider, model, and resilience

### Recommended setup (what runs in production)

- **Primary brain: OpenAI Codex `gpt-5.5`.** Authenticate it with `hermes login --provider
  openai-codex` — an OAuth login against your OpenAI / ChatGPT account, no API key to paste. Then set
  the model in `/root/.hermes/config.yaml`:

  ```yaml
  model: openai-codex/gpt-5.5
  ```

  Point the vision/auxiliary model at the same thing if you want screenshot workflows.

- **Fallback chain: Anthropic Sonnet → Haiku.** Add it under `fallback_providers` in the same
  `config.yaml` so a Codex rate-limit or token hiccup degrades instead of going dark:

  ```yaml
  fallback_providers:
    - provider: anthropic
      model: claude-sonnet-4-6
    - provider: anthropic
      model: claude-haiku-4-5
  ```

  Note: `hermes login` only covers `nous`, `openai-codex`, and `xai-oauth` — Anthropic is not in that
  list, so the fallback needs an Anthropic credential set up separately (an API key in
  `/root/.hermes/.env`, or an OAuth token if you run on a Claude subscription). Restart the gateway
  after editing the config.

Any provider Hermes supports will work (OpenRouter, plain Anthropic, etc.), but Codex-primary +
Anthropic-fallback is the proven pairing.

### Two durable lessons from running this in production

1. **Configure a fallback chain.** A single primary provider with no fallback means one rate-limit
   or expired token takes the whole agent dark — including the context-compression step, which shows
   up as the agent "losing context." The Sonnet → Haiku chain above is exactly that safety net.
2. **Watch tokens, not the network.** Most "agent went quiet" incidents are an expired OAuth token
   or a hit rate-limit, not connectivity. A tiny system-cron watchdog that refreshes the Codex token
   on a schedule (well inside its ~24h expiry window) prevents most outages, and because it is plain
   system cron it keeps working even when the agent brain is down.

---

## 16. Secrets and security

- Secrets live **only** in `/root/.hermes/.env`. Never in the brain repo (treat the brain as public).
- Use restricted-scope keys wherever a provider offers them (Stripe restricted key, Plaid
  read-only, Gmail least-scope).
- Rotate keys quarterly.
- Never write secrets via shell heredoc (shell history is permanent). Use file IO.
- Never paste credentials, tokens, or raw financial payloads into chat or notes.

### Env keys reference (names only — fill with your own values)

```
# core
TELEGRAM_BOT_TOKEN, TELEGRAM_ALLOWED_USERS, TELEGRAM_HOME_CHANNEL
<your LLM provider key>

# if you add finance
PLAID_CLIENT_ID, PLAID_SECRET, PLAID_ENV
STRIPE_RESTRICTED_KEY, STRIPE_WEBHOOK_SECRET

# if you add outbound agent email
AGENT_EMAIL_FROM, WEBHOOK_SECRET

# optional capability keys
ELEVENLABS_API_KEY / CARTESIA_API_KEY   # voice replies
BEEHIIV_API_KEY / BEEHIIV_PUBLICATION_ID  # newsletter ops
```

---

## 17. Operator posture (the part that actually matters)

Once the wiring is done, this is the whole game.

**Daily** — read the morning brief; resolve proposal cards in the Decisions topic in batches;
glance at the nightly accomplishment and correct SOUL/USER/MEMORY if something is consistently off.

**Weekly** — read the Sunday pulses; let the CRM hygiene job pull stale contacts out of the active
set.

**Monthly** — approve/edit/reject the SOUL-refinement proposals; read the finance review.

**Hard rules** — never change routing or jobs from a chat-level instruction without a proposal
record; never post client-identifying info outside your private group; never auto-send anything
touching money, pricing, relationships, family, or emotion; allowlist new outbound contacts before
even an approved send; mark uncertain claims `[UNCLEAR]` rather than guessing.

---

## 18. Sequenced rebuild (add modules in this order)

1. **Core install** — run the one-line installer, get the approval loop green and quiet. (README)
2. **Profile** — author USER.md, SOUL.md, MEMORY.md.
3. **Brain + CRM** — create the private repo, mirror the structure, wire Mac↔VPS sync, ingest
   messages, build the generated views.
4. **Gmail depth** — multi-account, emoji labeler, unsubscribe audit.
5. **Messages depth** — iMessage CRM ingestion + reply-draft watcher; then WhatsApp.
6. **Command center** — expand to the full bucket layout once there is real output to route.
7. **Finance** — Plaid (read-only), then Stripe (if you have revenue).
8. **Persistent browser** — for groceries / any logged-in service.
9. **Proactive layer** — voice replies, anticipatory triggers, soul refinement, learning loop.
   One at a time, only after the quiet baseline holds.

---

## 19. Known gotchas

- Hermes cron is **not** Linux cron. Use `hermes cron list` / `hermes cron edit`, not `crontab`.
- Restart the gateway (`systemctl restart hermes-gateway`) if MCP calls hang on a stale session.
- The Mac iMessage bridge needs **Full Disk Access** on Terminal. Re-grant after macOS updates.
- Telegram thread ids in the topics JSON are the source of truth — keep the doc and the JSON in
  sync.
- Google `GAPI`/`GSETUP` wrappers default to the legacy single token. Pass `--account <name>` for
  multi-account.
- The brain repo is public-by-default in posture. Any secret committed there is leaked.

---

## First-grade summary

The one-line install gives you the engine: a little always-on helper that reads your texts, email,
and calendar and writes neat drafts you approve with "yes." This guide is the rest of the car —
how to add a memory binder (the brain + CRM), more inboxes (WhatsApp, more Gmail tricks), money
dashboards (Plaid, Stripe), a logged-in web helper for things like groceries, and a tidy set of
daily and weekly check-ins. The rule the whole time: the helper can get everything ready, but it
never sends, buys, or changes anything important until you say yes.
