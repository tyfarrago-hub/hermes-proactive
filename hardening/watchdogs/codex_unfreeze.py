#!/usr/bin/env python3
"""Lightweight auto-recovery for the Codex provider (pure-Codex, no fallback).

When Codex returns a 429 (rate limit), the pool freezes the only provider
(STATUS_EXHAUSTED) and Hermes goes fully dark until the cooldown elapses or
something resets it. This bounds that dark window: every 5 min it clears a stale
freeze so a TRANSIENT throttle self-heals within minutes.

Does NOT force a token refresh (avoids rotating the refresh token every 5 min);
the 8h codex_token_refresh job handles token freshness. select() still does a
normal refresh-if-expiring. Safe + quiet: no Telegram, no outbound messages.
A genuine hard Codex cap will simply re-freeze on the next real call (accepted).
"""
import os, sys, datetime
os.environ.setdefault('HERMES_HOME','/root/.hermes'); os.environ.setdefault('HOME','/root')
sys.path.insert(0,'/root/.hermes/hermes-agent')
LOG='/root/.hermes/logs/codex_unfreeze.log'
def log(m):
    line=f'{datetime.datetime.now().isoformat(timespec="seconds")}  {m}'
    try: open(LOG,'a').write(line+'\n')
    except Exception: pass
try:
    from agent.credential_pool import load_pool
    pool=load_pool('openai-codex')
    cleared=pool.reset_statuses()
    sel=pool.select()
    if cleared:
        log(f'cleared_freezes={cleared} usable={sel is not None}')
    sys.exit(0)
except Exception as e:
    log(f'FAIL {type(e).__name__}: {e}'); sys.exit(1)
