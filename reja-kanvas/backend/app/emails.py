"""Email notifications (chosen kinds, respecting quiet hours) and the optional morning digest."""

import json
from datetime import time, timedelta

from . import db, mailer, timeutil
from .plans import stamp

DEFAULT_EMAIL_KINDS = ["approval_requested", "returned", "mentioned", "approver_silent", "assigned"]
DIGEST_HOUR = 8
DELAY = timedelta(minutes=2)  # gives "undo" a chance before anything leaves the building

SUBJECTS = {
    "uz": {"approval_requested": "Tasdiq kutilmoqda", "returned": "Reja qaytarildi", "approved": "Reja tasdiqlandi",
           "mentioned": "Sizni eslatishdi", "approver_silent": "Tasdiqlovchi javob bermayapti", "assigned": "Sizga reja topshirildi",
           "due_soon": "Muddat yaqin", "commented": "Yangi izoh", "team_added": "Jamoaga qo'shildingiz", "digest": "Bugungi rejalar"},
    "ru": {"approval_requested": "Ждёт подтверждения", "returned": "План возвращён", "approved": "План подтверждён",
           "mentioned": "Вас упомянули", "approver_silent": "Подтверждающий не отвечает", "assigned": "Вам передан план",
           "due_soon": "Скоро срок", "commented": "Новый комментарий", "team_added": "Вас добавили в команду", "digest": "Планы на сегодня"},
    "en": {"approval_requested": "Waiting for your approval", "returned": "Plan returned", "approved": "Plan approved",
           "mentioned": "You were mentioned", "approver_silent": "Approver isn't answering", "assigned": "A plan was assigned to you",
           "due_soon": "Due soon", "commented": "New comment", "team_added": "You were added to a team", "digest": "Today's plans"},
}


def prefs_of(user) -> dict:
    prefs = json.loads(user["prefs"] or "{}")
    prefs.setdefault("email_kinds", DEFAULT_EMAIL_KINDS)
    return prefs


def in_quiet_hours(prefs: dict, tz: str, now=None) -> bool:
    start, end = prefs.get("quiet_start"), prefs.get("quiet_end")
    if not start or not end:
        return False
    local = (now or timeutil.now()).astimezone(timeutil.zone(tz)).time()
    s, e = time.fromisoformat(start), time.fromisoformat(end)
    return s <= local < e if s < e else (local >= s or local < e)


def _lang(user) -> str:
    return "ru" if user["lang"] == "ru" else "en" if user["lang"] == "en" else "uz"


def send_pending(frontend_url: str, limit: int = 100) -> int:
    cutoff = timeutil.to_iso(timeutil.now() - DELAY)
    with db.session() as conn:
        rows = conn.execute(
            """SELECT n.id, n.kind, n.data, n.plan_id, n.user_id FROM notifications n
               WHERE n.emailed_at IS NULL AND n.read_at IS NULL AND n.created_at <= ? ORDER BY n.id LIMIT ?""",
            (cutoff, limit),
        ).fetchall()
        outgoing, skip = [], []
        for r in rows:
            user = conn.execute("SELECT * FROM users WHERE id = ?", (r["user_id"],)).fetchone()
            prefs = prefs_of(user)
            if r["kind"] not in prefs["email_kinds"]:
                skip.append(r["id"])
                continue
            if in_quiet_hours(prefs, user["tz"]):
                continue  # try again after the quiet hours
            data = json.loads(r["data"])
            subject = f"Reja · {SUBJECTS[_lang(user)].get(r['kind'], r['kind'])}"
            link = f"{frontend_url.rstrip('/')}/plan/{r['plan_id']}" if r["plan_id"] else frontend_url
            text = f"{data.get('title') or data.get('team') or ''}\n{data.get('reason', '')}\n\n{link}\n"
            outgoing.append((r["id"], user["email"], subject, text))
        # Mark first so a crash never sends the same mail twice.
        stamp_now = stamp()
        for nid in skip + [o[0] for o in outgoing]:
            conn.execute("UPDATE notifications SET emailed_at = ? WHERE id = ?", (stamp_now, nid))
    for _, to, subject, text in outgoing:
        mailer.send(to, subject, text)
    return len(outgoing)


def send_digests(frontend_url: str) -> int:
    count = 0
    with db.session() as conn:
        users = conn.execute("SELECT * FROM users").fetchall()
        outgoing = []
        for user in users:
            prefs = prefs_of(user)
            if not prefs.get("digest"):
                continue
            local = timeutil.now().astimezone(timeutil.zone(user["tz"]))
            today = local.date().isoformat()
            if local.hour < DIGEST_HOUR or user["last_digest_on"] == today:
                continue
            start, end = (timeutil.to_iso(d) for d in timeutil.day_bounds_utc(local.date(), user["tz"]))
            plans = conn.execute(
                """SELECT title, due_at FROM plans WHERE owner_id = ? AND deleted_at IS NULL AND status IN ('active', 'returned')
                   AND due_at < ? ORDER BY due_at""",
                (user["id"], end),
            ).fetchall()
            overdue = [p for p in plans if p["due_at"] < start]
            todays = [p for p in plans if p["due_at"] >= start]
            conn.execute("UPDATE users SET last_digest_on = ? WHERE id = ?", (today, user["id"]))
            if not plans:
                continue
            lines = [f"• {timeutil.parse_iso(p['due_at']).astimezone(timeutil.zone(user['tz'])):%H:%M}  {p['title']}" for p in todays]
            if overdue:
                lines.append(f"\n⚠ {len(overdue)}: " + ", ".join(p["title"] for p in overdue[:5]))
            outgoing.append((user["email"], f"Reja · {SUBJECTS[_lang(user)]['digest']}", "\n".join(lines) + f"\n\n{frontend_url}\n"))
    for to, subject, text in outgoing:
        mailer.send(to, subject, text)
        count += 1
    return count
