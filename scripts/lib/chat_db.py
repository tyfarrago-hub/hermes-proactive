"""
chat_db.py — shared library for carbon-voiceprint.

Reads ~/Library/Messages/chat.db (macOS iMessage), resolves contacts from
the user's local AddressBook, decodes the modern attributedBody NSAttributedString
blob when message.text is NULL, and provides spam/closer filters that both
the digest and the voice-extract pipelines rely on.

No network calls live in this file. It is pure local SQLite + regex.
"""

import sqlite3
import os
import re
import glob
from datetime import datetime, timedelta

DB = os.path.expanduser("~/Library/Messages/chat.db")
APPLE_EPOCH_OFFSET = 978307200  # 2001-01-01 to 1970-01-01 in seconds
NS_TO_S = 1_000_000_000

# Tapback / reaction message types (associated_message_type column)
TAPBACK_MAP = {
    2000: "❤️", 2001: "👍", 2002: "👎", 2003: "😂", 2004: "‼️", 2005: "❓",
    3000: "removed ❤️", 3001: "removed 👍", 3002: "removed 👎",
    3003: "removed 😂", 3004: "removed ‼️", 3005: "removed ❓",
}

# Closer phrases — short conversation enders. If the other person's last
# message is one of these, the thread does NOT need a reply.
CLOSER_PATTERNS = re.compile(
    r'^(thanks?|thank you|tysm|thx|ty|appreciate it|'
    r'sounds good|perfect|awesome|great|bet|cool|'
    r'ok thanks|ok thank you|ok ty|ok cool|ok great|ok perfect|ok bet|'
    r'got it|will do|for sure|no worries|all good|'
    r'good night|goodnight|gn|night|nighty night|'
    r'talk soon|chat soon|ttyl|later|see you|'
    r'love you|love u|luv u|❤️|🙏|👍|haha|lol|lmao)[\s!.\-❤️🙏👍😂🔥]*$',
    re.IGNORECASE
)

# Promo / OTP / no-reply automated messages. Broad on purpose — false
# positives are bounded (a marketing blast wrongly dropped) but false
# negatives clutter the digest with noise.
SPAM_KEYWORDS = [
    'verification code', 'one-time', 'otp', 'security code',
    'confirmation code', 'login code', 'access code', 'authentication code',
    'your code is', 'your otp',
    'reply stop', 'text stop', 'txt stop', 'reply unstop', 'text unstop',
    'unstop to resume', 'blocked from receiving',
    'to unsubscribe', 'msg&data', 'msg & data', 'standard rates apply',
    'do not reply', 'do-not-reply', 'no-reply', 'noreply',
]

BRAND_PREFIX_RE = re.compile(r'\[[A-Za-z][A-Za-z0-9 ._-]{1,30}\]')
TOLL_FREE_PREFIXES = {'800', '833', '844', '855', '866', '877', '888'}


def is_spam_thread(text):
    if not text:
        return False
    low = text.lower()
    if any(kw in low for kw in SPAM_KEYWORDS):
        return True
    if BRAND_PREFIX_RE.search(text):
        return True
    return False


def is_short_code(contact):
    if contact.startswith('mailto:'):
        return False
    digits = re.sub(r'[^0-9]', '', contact)
    return 0 < len(digits) < 10


def is_toll_free(contact):
    if contact.startswith('mailto:'):
        return False
    digits = re.sub(r'[^0-9]', '', contact)
    if len(digits) == 11 and digits[0] == '1':
        return digits[1:4] in TOLL_FREE_PREFIXES
    if len(digits) == 10:
        return digits[:3] in TOLL_FREE_PREFIXES
    return False


def is_business_sender(contact):
    return is_short_code(contact) or is_toll_free(contact)


def is_conversation_closer(text):
    if not text:
        return False
    cleaned = text.strip()
    if len(cleaned) > 60:
        return False
    return bool(CLOSER_PATTERNS.match(cleaned))


def build_contact_lookup():
    """Phone number (last 10 digits) → full name, from macOS Contacts.app."""
    dbs = glob.glob(os.path.expanduser(
        "~/Library/Application Support/AddressBook/Sources/*/AddressBook-v22.abcddb"))
    contacts = {}
    for db in dbs:
        try:
            con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
            cur = con.cursor()
            cur.execute("""
                SELECT r.ZFIRSTNAME, r.ZLASTNAME, p.ZFULLNUMBER
                FROM ZABCDRECORD r
                JOIN ZABCDPHONENUMBER p ON p.ZOWNER = r.Z_PK
                WHERE p.ZFULLNUMBER IS NOT NULL
            """)
            for first, last, phone in cur.fetchall():
                digits = re.sub(r'[^0-9]', '', phone or '')
                if len(digits) >= 10:
                    key = digits[-10:]
                    name = f'{first or ""} {last or ""}'.strip()
                    if name:
                        contacts[key] = name
            con.close()
        except Exception:
            pass
    return contacts


def resolve_name(contact_id, lookup):
    digits = re.sub(r'[^0-9]', '', contact_id)
    if len(digits) >= 10:
        name = lookup.get(digits[-10:])
        if name:
            return name
    return contact_id


_NS_TOKEN_RE = re.compile(
    r'(__kIM[A-Za-z]*|\$class(?:name|es)?|'
    r'NSAttributedString|NSMutableAttributedString|'
    r'NSObject|NSString|NSDictionary|NSNumber|NSValue|NSArray|NSData|'
    r'streamtyped|classname[a-z]*|classeswn[a-z]+)'
)


def extract_attributed_text(blob):
    """Pull readable text out of an NSAttributedString blob.

    Modern iMessage rows store rich text in attributedBody (binary
    NSKeyedArchiver) and leave message.text NULL. We do not reimplement
    NSKeyedArchiver — we scan for printable ASCII runs ≥ 4 chars, drop
    framework class names and any segment polluted with NSKeyedArchiver
    bookkeeping tokens, then return the longest clean segment.
    """
    if not blob:
        return None
    try:
        decoded = blob.decode('utf-8', errors='ignore')
        segments = re.findall(r'[\x20-\x7e]{4,}', decoded)
        cleaned = []
        for s in segments:
            s = s.strip()
            # Drop segments that contain any NS class hint or kIM attribute name
            if _NS_TOKEN_RE.search(s):
                continue
            # Strip leading/trailing junk binary chars
            s = re.sub(r'^[+\x00-\x1f]+|[iI\x00-\x1f]+$', '', s).strip()
            # Drop pure-class-prefix lowercase artifacts ("z classnamex", "w xnsobject", etc.)
            if re.fullmatch(r'[a-z]{1,3}(\s+[a-z]+)*', s):
                continue
            if s and len(s) >= 2:
                cleaned.append(s)
        if cleaned:
            return max(cleaned, key=len)
    except Exception:
        pass
    return None


def describe_message(text, associated_type, has_attachment, mime_type):
    """Render a single message row into a human-readable string."""
    if associated_type and associated_type in TAPBACK_MAP:
        return f"[{TAPBACK_MAP[associated_type]} reaction]"
    if associated_type and 2006 <= associated_type < 3000:
        emoji = (text or "").strip()
        return f"[{emoji} reaction]" if emoji else "[reaction]"

    if has_attachment and (not text or text.strip() in ('', '￼' * len(text.strip()))):
        if mime_type:
            if 'video' in mime_type:
                return "[sent a video]"
            if 'image' in mime_type or 'heic' in mime_type:
                return "[sent a photo]"
            if 'audio' in mime_type:
                return "[sent audio]"
            return "[sent a file]"
        return "[sent an attachment]"

    if has_attachment and text:
        clean = text.replace('￼', '').strip()
        if clean:
            if mime_type and 'image' in mime_type:
                return f"{clean} [+ photo]"
            if mime_type and 'video' in mime_type:
                return f"{clean} [+ video]"
            return clean
        if mime_type and 'video' in mime_type:
            return "[sent a video]"
        if mime_type and ('image' in mime_type or 'heic' in mime_type):
            return "[sent a photo]"
        return "[sent an attachment]"

    return text or ""


def open_chat_db():
    """Open chat.db read-only. Caller must close()."""
    return sqlite3.connect(f"file:{DB}?mode=ro&immutable=1", uri=True)


def fda_probe():
    """Return (ok: bool, error_message: str|None). Cheap test for Full Disk Access."""
    try:
        con = open_chat_db()
        con.cursor().execute("SELECT 1 FROM message LIMIT 1").fetchone()
        con.close()
        return True, None
    except sqlite3.OperationalError as e:
        return False, str(e)
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


def get_outbound_messages(con, since_dt, exclude_threads=None):
    """Yield ALL messages the user sent in 1-on-1 threads since `since_dt`.

    Used by voice-extract. Only is_from_me=1 rows from non-group threads.
    Drops threads whose resolved contact name OR raw handle id matches an
    entry in `exclude_threads` (case-insensitive substring match).

    Yields dicts with: text (decoded), date_unix (seconds), contact (resolved name).
    """
    cur = con.cursor()
    lookup = build_contact_lookup()
    cutoff = int(since_dt.timestamp())

    cur.execute("""
        SELECT m.text, m.date, m.attributedBody, m.associated_message_type,
               m.cache_has_attachments, h.id
        FROM message m
        LEFT JOIN handle h ON m.handle_id = h.ROWID
        WHERE m.is_from_me = 1
          AND m.cache_roomnames IS NULL
          AND (m.date/? + ?) > ?
        ORDER BY m.date ASC
    """, (NS_TO_S, APPLE_EPOCH_OFFSET, cutoff))

    excludes_norm = [e.lower() for e in (exclude_threads or [])]

    for text, date, attr_body, assoc_type, has_attach, contact_id in cur.fetchall():
        if not text and attr_body:
            text = extract_attributed_text(attr_body)
        if not text:
            continue
        if assoc_type and assoc_type > 0:  # skip reactions
            continue
        if has_attach:  # attachments without real text are noise for voice analysis
            cleaned = (text or '').replace('￼', '').strip()
            if not cleaned:
                continue
            text = cleaned

        contact_id = contact_id or ''
        resolved = resolve_name(contact_id, lookup) if contact_id else ''
        if any(e in (resolved + ' ' + contact_id).lower() for e in excludes_norm):
            continue

        yield {
            "text": text,
            "date_unix": date / NS_TO_S + APPLE_EPOCH_OFFSET,
            "contact": resolved or contact_id or "unknown",
        }


def get_top_contacts(con, limit=20, days=180):
    """Return top N contacts by 1-on-1 message volume in the last `days`.

    Used by setup to power the interactive exclude-threads picker.
    """
    cur = con.cursor()
    lookup = build_contact_lookup()
    cutoff = int((datetime.now() - timedelta(days=days)).timestamp())

    cur.execute("""
        SELECT h.id, COUNT(*) as n
        FROM message m
        JOIN handle h ON m.handle_id = h.ROWID
        WHERE m.cache_roomnames IS NULL
          AND (m.date/? + ?) > ?
        GROUP BY h.id
        ORDER BY n DESC
        LIMIT ?
    """, (NS_TO_S, APPLE_EPOCH_OFFSET, cutoff, limit))

    out = []
    for handle_id, n in cur.fetchall():
        if is_business_sender(handle_id):
            continue
        out.append({"contact": resolve_name(handle_id, lookup), "handle": handle_id, "count": n})
    return out


# ---------- digest helpers (used by digest.py) ----------

def _iso(ts_ns):
    if ts_ns is None:
        return None
    dt = datetime.utcfromtimestamp(ts_ns / NS_TO_S + APPLE_EPOCH_OFFSET)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def get_messages_for_handle(cur, handle_rowid, cutoff):
    """Last messages with a given handle. cutoff=None → last 8 messages."""
    if cutoff:
        cur.execute("""
            SELECT m.ROWID, m.is_from_me, m.text, m.date,
                m.associated_message_type, m.cache_has_attachments, m.attributedBody
            FROM message m
            WHERE m.handle_id = ?
                AND (m.date/? + ?) > ?
                AND m.cache_roomnames IS NULL
            ORDER BY m.date ASC
        """, (handle_rowid, NS_TO_S, APPLE_EPOCH_OFFSET, cutoff))
    else:
        cur.execute("""
            SELECT m.ROWID, m.is_from_me, m.text, m.date,
                m.associated_message_type, m.cache_has_attachments, m.attributedBody
            FROM message m
            WHERE m.handle_id = ?
                AND m.cache_roomnames IS NULL
            ORDER BY m.date DESC
            LIMIT 8
        """, (handle_rowid,))

    rows = cur.fetchall()
    if not cutoff:
        rows.reverse()

    messages = []
    for rowid, is_from_me, text, date, assoc_type, has_attach, attr_body in rows:
        if not text and attr_body:
            text = extract_attributed_text(attr_body)
        mime_type = None
        if has_attach:
            cur.execute("""
                SELECT a.mime_type FROM attachment a
                JOIN message_attachment_join maj ON a.ROWID = maj.attachment_id
                WHERE maj.message_id = ?
                LIMIT 1
            """, (rowid,))
            att = cur.fetchone()
            if att:
                mime_type = att[0]

        desc = describe_message(text, assoc_type, has_attach, mime_type)
        if not desc:
            continue
        if assoc_type and assoc_type >= 3000:  # removed reactions
            continue

        messages.append({
            "is_from_me": is_from_me,
            "text": desc,
            "date": date,
            "is_reaction": bool(assoc_type and assoc_type > 0),
            "is_closer": is_conversation_closer(desc) if not is_from_me else False,
            "is_attachment": bool(has_attach and (not assoc_type or assoc_type == 0)),
        })
    return messages


def get_todays_conversations(hours_back, user_label, lookup=None):
    """Pull all 1-on-1 + group conversations from the last `hours_back` hours.

    Returns (conversations, rolling_unanswered).

    `user_label` is the label rendered in the thread for is_from_me messages
    (e.g. "Sam" or "You"). Pulled from config so the digest reads naturally.
    """
    con = open_chat_db()
    cur = con.cursor()
    if lookup is None:
        lookup = build_contact_lookup()

    cutoff = int((datetime.now() - timedelta(hours=hours_back)).timestamp())

    # 1-on-1 threads
    cur.execute("""
        SELECT h.id, h.ROWID, MAX(m.date) as last_date
        FROM message m
        JOIN handle h ON m.handle_id = h.ROWID
        WHERE m.cache_roomnames IS NULL
            AND (m.date/? + ?) > ?
        GROUP BY h.id, h.ROWID
        ORDER BY last_date DESC
    """, (NS_TO_S, APPLE_EPOCH_OFFSET, cutoff))

    handles = cur.fetchall()
    conversations = []
    for contact, handle_rowid, _ in handles:
        if not contact.startswith('+') and not contact.startswith('mailto:'):
            continue
        if is_business_sender(contact):
            continue

        messages = get_messages_for_handle(cur, handle_rowid, cutoff)
        if not messages:
            continue

        all_text = " ".join(m["text"] for m in messages)
        if is_spam_thread(all_text):
            continue

        display_name = resolve_name(contact, lookup)

        thread = []
        for m in messages:
            sender = user_label if m["is_from_me"] else display_name
            thread.append(f"{sender}: {m['text']}")

        last_user_action = None
        last_them = None
        for m in reversed(messages):
            if m["is_from_me"] and not last_user_action:
                last_user_action = m
            if not m["is_from_me"] and not m["is_reaction"] and not m.get("is_closer") and not last_them:
                last_them = m
            if last_user_action and last_them:
                break

        if last_them and last_user_action:
            unanswered = last_them["date"] > last_user_action["date"]
        elif last_them and not last_user_action:
            unanswered = True
        else:
            unanswered = False

        conversations.append({
            "handle": contact,
            "contact": display_name,
            "msg_count": len(messages),
            "unanswered": unanswered,
            "thread": "\n".join(thread),
            "last_inbound_text": last_them["text"] if last_them else None,
            "last_inbound_at": _iso(last_them["date"]) if last_them else None,
            "last_user_reply_at": _iso(last_user_action["date"]) if last_user_action else None,
        })

    # Group chats
    cur.execute("""
        SELECT c.ROWID, COALESCE(c.display_name, c.chat_identifier) as name,
               MAX(m.date) as last_date
        FROM message m
        JOIN chat_message_join cmj ON m.ROWID = cmj.message_id
        JOIN chat c ON cmj.chat_id = c.ROWID
        WHERE c.room_name IS NOT NULL
            AND (m.date/? + ?) > ?
        GROUP BY c.ROWID
        ORDER BY last_date DESC
    """, (NS_TO_S, APPLE_EPOCH_OFFSET, cutoff))

    groups = cur.fetchall()
    for chat_rowid, group_name, _ in groups:
        cur.execute("""
            SELECT m.ROWID, m.is_from_me, COALESCE(h.id, ?) as sender,
                m.text, m.date, m.associated_message_type, m.cache_has_attachments
            FROM message m
            JOIN chat_message_join cmj ON m.ROWID = cmj.message_id
            LEFT JOIN handle h ON m.handle_id = h.ROWID
            WHERE cmj.chat_id = ?
                AND (m.date/? + ?) > ?
            ORDER BY m.date ASC
        """, (user_label, chat_rowid, NS_TO_S, APPLE_EPOCH_OFFSET, cutoff))

        rows = cur.fetchall()
        if not rows:
            continue

        messages = []
        for rowid, is_from_me, sender, text, date, assoc_type, has_attach in rows:
            mime_type = None
            if has_attach:
                cur.execute("""
                    SELECT a.mime_type FROM attachment a
                    JOIN message_attachment_join maj ON a.ROWID = maj.attachment_id
                    WHERE maj.message_id = ? LIMIT 1
                """, (rowid,))
                att = cur.fetchone()
                if att:
                    mime_type = att[0]

            desc = describe_message(text, assoc_type, has_attach, mime_type)
            if not desc or (assoc_type and assoc_type >= 3000):
                continue

            name = user_label if is_from_me else resolve_name(sender, lookup)
            messages.append({"sender": name, "text": desc, "is_from_me": is_from_me, "date": date})

        if not messages:
            continue

        thread = [f"{m['sender']}: {m['text']}" for m in messages]
        last_from_me = messages[-1]["is_from_me"]
        unanswered = not last_from_me

        conversations.append({
            "contact": f"[GROUP] {group_name}",
            "msg_count": len(messages),
            "unanswered": unanswered,
            "thread": "\n".join(thread),
        })

    # Dedupe by display name (same person via phone + email)
    by_name = {}
    for c in conversations:
        key = c["contact"]
        if key in by_name:
            prev = by_name[key]
            if c["msg_count"] > prev["msg_count"]:
                c["unanswered"] = c["unanswered"] or prev["unanswered"]
                by_name[key] = c
            else:
                prev["unanswered"] = prev["unanswered"] or c["unanswered"]
        else:
            by_name[key] = c
    conversations = list(by_name.values())

    # Rolling 7-day unanswered (from same con/cur)
    rolling = _get_rolling_unanswered(con, cutoff, lookup, user_label)
    today_contacts = {c["contact"] for c in conversations}
    rolling = [r for r in rolling if r["contact"] not in today_contacts]

    con.close()
    return conversations, rolling


def _get_rolling_unanswered(con, cutoff_today, lookup, user_label):
    cur = con.cursor()
    cutoff_week = int((datetime.now() - timedelta(days=7)).timestamp())

    cur.execute("""
        SELECT h.id, h.ROWID, MAX(m.date) as last_date
        FROM message m
        JOIN handle h ON m.handle_id = h.ROWID
        WHERE m.cache_roomnames IS NULL
            AND (m.date/? + ?) > ?
            AND (m.date/? + ?) <= ?
        GROUP BY h.id, h.ROWID
        ORDER BY last_date DESC
    """, (NS_TO_S, APPLE_EPOCH_OFFSET, cutoff_week,
          NS_TO_S, APPLE_EPOCH_OFFSET, cutoff_today))

    handles = cur.fetchall()
    out = []

    for contact, handle_rowid, _ in handles:
        if not contact.startswith('+') and not contact.startswith('mailto:'):
            continue
        if is_business_sender(contact):
            continue

        messages = get_messages_for_handle(cur, handle_rowid, None)
        if not messages:
            continue

        last_user_action = None
        for m in reversed(messages):
            if m["is_from_me"]:
                last_user_action = m
                break

        last_them = None
        for m in reversed(messages):
            if not m["is_from_me"] and not m["is_reaction"] and not m.get("is_closer"):
                last_them = m
                break

        if not last_them:
            continue
        if last_user_action and last_user_action["date"] > last_them["date"]:
            continue

        thread_text = " ".join(m["text"] for m in messages)
        if is_spam_thread(thread_text):
            continue

        display_name = resolve_name(contact, lookup)

        thread = []
        for m in messages[-5:]:
            sender = user_label if m["is_from_me"] else display_name
            thread.append(f"{sender}: {m['text']}")

        last_dt = datetime.fromtimestamp(last_them["date"] / NS_TO_S + APPLE_EPOCH_OFFSET)
        hours_ago = int((datetime.now() - last_dt).total_seconds() / 3600)

        out.append({
            "handle": contact,
            "contact": display_name,
            "last_msg_time": f"{hours_ago}h ago",
            "thread": "\n".join(thread),
            "last_inbound_text": last_them["text"],
            "last_inbound_at": _iso(last_them["date"]),
            "last_user_reply_at": _iso(last_user_action["date"]) if last_user_action else None,
        })

    return out


def compute_buckets(conversations, rolling, fade_hours=72):
    """Pre-group threads into (reply_needed, ball_in_court, fading)."""
    reply_needed = []
    ball_in_court = []
    fading = []

    for c in conversations:
        entry = {
            "handle": c.get("handle"),
            "contact": c["contact"],
            "thread": c["thread"],
            "msg_count": c["msg_count"],
            "last_inbound_text": c.get("last_inbound_text"),
            "last_inbound_at": c.get("last_inbound_at"),
            "last_user_reply_at": c.get("last_user_reply_at"),
        }
        if c["unanswered"]:
            reply_needed.append(entry)
        else:
            ball_in_court.append(entry)

    for r in rolling:
        hours = int(r["last_msg_time"].replace("h ago", "").replace("h", ""))
        entry = {
            "handle": r.get("handle"),
            "contact": f"{r['contact']} ({r['last_msg_time']})",
            "thread": r["thread"],
            "last_inbound_text": r.get("last_inbound_text"),
            "last_inbound_at": r.get("last_inbound_at"),
            "last_user_reply_at": r.get("last_user_reply_at"),
        }
        if hours <= fade_hours:
            reply_needed.append(entry)
        else:
            fading.append(entry)

    def base_name(contact):
        return contact.split(' (')[0].strip()

    seen = set()
    reply_needed = [x for x in reply_needed if not (base_name(x["contact"]) in seen or seen.add(base_name(x["contact"])))]
    ball_in_court = [x for x in ball_in_court if not (base_name(x["contact"]) in seen or seen.add(base_name(x["contact"])))]
    fading = [x for x in fading if not (base_name(x["contact"]) in seen or seen.add(base_name(x["contact"])))]

    return reply_needed, ball_in_court, fading
