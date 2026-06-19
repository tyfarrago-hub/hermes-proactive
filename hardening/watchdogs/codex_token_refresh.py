#!/usr/bin/env python3
"""Proactively force-refresh the Codex (ChatGPT) OAuth token in Hermes's
credential pool so it never expires mid-flight.

Why this exists: a Hermes running Codex as its primary provider goes fully dark
the moment its token expires or its pool entry freezes STATUS_EXHAUSTED after a
401 -- every cron job and every direct message 401s. This runs on a *system*
cron (independent of the LLM brain, so it works even when the brain is down)
every 8h, well inside the ~24h Codex token lifetime.

Steps mirror the live gateway's own pool path:
  1. reset_statuses()       -> clear any stale STATUS_EXHAUSTED freeze
  2. select()               -> pick + set current (+ refresh-if-expiring, persists)
  3. try_refresh_current()  -> FORCE a fresh token, resets the clock, persists

Prints only safe metadata, never a token. Exit 0 on success, 1 on failure.

Install: see hardening/HARDENING.md. Only relevant when Hermes' primary provider
is openai-codex; skip it for an Anthropic-primary brain.
"""
import os, sys, datetime

os.environ.setdefault('HERMES_HOME', '/root/.hermes')
os.environ.setdefault('HOME', '/root')
sys.path.insert(0, '/root/.hermes/hermes-agent')

LOG = '/root/.hermes/logs/codex_token_refresh.log'


def _owner_chat():
    """Owner chat id for failure alerts. Reads env first, then .env. None = skip alert."""
    chat = os.getenv('HERMES_OWNER_CHAT_ID') or os.getenv('TELEGRAM_CHAT_ID')
    if not chat:
        try:
            for ln in open('/root/.hermes/.env'):
                ln = ln.strip()
                if ln.startswith(('HERMES_OWNER_CHAT_ID=', 'TELEGRAM_CHAT_ID=')):
                    chat = ln.split('=', 1)[1].strip().strip(chr(34)).strip(chr(39)); break
        except Exception:
            pass
    # only a numeric Telegram id (optionally negative for groups) is usable
    if chat and chat.lstrip('-').isdigit():
        return chat
    return None


def log(msg):
    line = f'{datetime.datetime.now().isoformat(timespec="seconds")}  {msg}'
    print(line)
    try:
        with open(LOG, 'a') as f:
            f.write(line + '\n')
    except Exception:
        pass


def notify_failure(detail):
    try:
        import urllib.request, urllib.parse
        tok = os.getenv('TELEGRAM_BOT_TOKEN') or os.getenv('HERMES_TELEGRAM_BOT_TOKEN')
        chat = _owner_chat()
        if not tok:
            try:
                for ln in open('/root/.hermes/.env'):
                    ln = ln.strip()
                    if ln.startswith(('TELEGRAM_BOT_TOKEN=', 'HERMES_TELEGRAM_BOT_TOKEN=')):
                        tok = ln.split('=', 1)[1].strip().strip(chr(34)).strip(chr(39)); break
            except Exception:
                pass
        if not tok or not chat:
            return
        data = urllib.parse.urlencode({'chat_id': chat,
            'text': '⚠️ Codex token auto-refresh FAILED: ' + detail[:300] +
                    '\nHermes may go down within ~24h. Re-auth needed.'}).encode()
        urllib.request.urlopen('https://api.telegram.org/bot' + tok + '/sendMessage', data=data, timeout=15)
    except Exception:
        pass


def main():
    try:
        from agent.credential_pool import load_pool
    except Exception as e:
        log(f'IMPORT_FAIL {type(e).__name__}: {e}'); notify_failure(f'import error {e}'); return 1
    try:
        pool = load_pool('openai-codex')
        n = len(pool.entries())
        cleared = pool.reset_statuses()
        sel = pool.select()
        if sel is None:
            log(f'NO_ENTRY entries={n} cleared={cleared} (no usable codex credential in pool)')
            notify_failure('no usable codex credential in pool'); return 1
        refreshed = pool.try_refresh_current()
        ok = refreshed is not None and bool(getattr(refreshed, 'access_token', None))
        log(f'REFRESH ok={ok} entries={n} cleared_freezes={cleared} '
            f'status={getattr(refreshed, "last_status", None)} last_refresh={getattr(refreshed, "last_refresh", None)}')
        if not ok:
            notify_failure('force refresh returned no token'); return 1
        return 0
    except Exception as e:
        log(f'REFRESH_FAIL {type(e).__name__}: {e}'); notify_failure(f'{type(e).__name__}: {e}'); return 1


if __name__ == '__main__':
    sys.exit(main())
