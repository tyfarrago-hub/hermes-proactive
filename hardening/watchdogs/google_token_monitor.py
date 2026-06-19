#!/usr/bin/env python3
"""Early-warning monitor for Hermes's Google (Gmail/Calendar) OAuth tokens.

Root cause it watches for: if your OAuth consent screen is published as External
+ 'Testing' (not Production), Google expires refresh tokens after ~7 days, so a
consumer gmail.com account silently dies with
'invalid_grant: Token has been expired or revoked' and inbox scans stop. (A
Google Workspace account in the same GCP org as the OAuth app is not subject to
the 7-day rule.)

This does an in-memory refresh test per account (does NOT save / rotate tokens)
and Telegrams the owner the moment one fails, so they re-auth on their own
schedule instead of discovering it via a broken digest. The durable fix is
publishing the OAuth consent app to Production -- this is only the smoke alarm.

Install: see hardening/HARDENING.md. Only relevant when Hermes has Google
Workspace OAuth wired (google_accounts/*/google_token.json present).
"""
import os, glob, datetime
os.environ.setdefault('HERMES_HOME', '/root/.hermes')
LOG = '/root/.hermes/logs/google_token_monitor.log'


def _owner_chat():
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


def log(m):
    line=f'{datetime.datetime.now().isoformat(timespec="seconds")}  {m}'
    print(line)
    try:
        open(LOG,'a').write(line+'\n')
    except Exception: pass


def telegram(text):
    try:
        import urllib.request, urllib.parse
        tok=os.getenv('TELEGRAM_BOT_TOKEN') or os.getenv('HERMES_TELEGRAM_BOT_TOKEN')
        chat=_owner_chat()
        if not tok:
            for ln in open('/root/.hermes/.env'):
                ln=ln.strip()
                if ln.startswith(('TELEGRAM_BOT_TOKEN=','HERMES_TELEGRAM_BOT_TOKEN=')):
                    tok=ln.split('=',1)[1].strip().strip(chr(34)).strip(chr(39)); break
        if not tok or not chat: return
        data=urllib.parse.urlencode({'chat_id':chat,'text':text}).encode()
        urllib.request.urlopen('https://api.telegram.org/bot'+tok+'/sendMessage',data=data,timeout=15)
    except Exception: pass


def main():
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    dead=[]
    for p in sorted(glob.glob('/root/.hermes/google_accounts/*/google_token.json')):
        acct=p.split('/')[-2]
        try:
            c=Credentials.from_authorized_user_file(p)
            c.refresh(Request())   # in-memory only; not saved
            log(f'{acct} OK')
        except Exception as e:
            log(f'{acct} FAIL {type(e).__name__}: {str(e)[:140]}')
            dead.append(acct)
    if dead:
        telegram('⚠️ Google OAuth refresh DEAD for: '+', '.join(dead)+
                 '. Re-auth needed (Hermes can\'t scan those inboxes). '
                 'Durable fix: publish your OAuth consent app to Production.')
        return 1
    return 0


if __name__=='__main__':
    import sys; sys.exit(main())
