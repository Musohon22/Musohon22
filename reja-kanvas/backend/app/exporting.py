"""Getting data out (JSON backup, CSV for spreadsheets, iCalendar feed) and back in (JSON import)."""

import csv
import io
import json
import secrets
from datetime import timedelta

from pydantic import ValidationError

from . import timeutil
from .errors import ApiError
from .plans import create, serialize
from .sanitize import html_to_text
from .schemas import PlanCreate

EXPORT_VERSION = 1


def export_json(conn, user) -> dict:
    rows = conn.execute(
        "SELECT * FROM plans WHERE owner_id = ? AND deleted_at IS NULL ORDER BY created_at", (user["id"],)
    ).fetchall()
    plans = []
    for r in rows:
        p = serialize(conn, r, user["id"], detail=True)
        p["comments"] = [
            dict(c) for c in conn.execute(
                """SELECT c.body, c.created_at, u.name AS author FROM comments c LEFT JOIN users u ON u.id = c.user_id
                   WHERE c.plan_id = ? ORDER BY c.created_at""",
                (r["id"],),
            )
        ]
        plans.append(p)
    return {"version": EXPORT_VERSION, "exported_at": timeutil.to_iso(timeutil.now()), "user": {"name": user["name"], "email": user["email"]}, "plans": plans}


CSV_COLUMNS = ["title", "status", "priority", "tag", "due_at", "completed_at", "late_minutes", "steps_done", "steps_total", "tracked_minutes", "goal", "notes"]


def export_csv(conn, user) -> str:
    buf = io.StringIO()
    buf.write("\ufeff")  # BOM so Excel opens UTF-8 (Cyrillic, oʻ) correctly
    writer = csv.writer(buf)
    writer.writerow(CSV_COLUMNS)
    for p in export_json(conn, user)["plans"]:
        row = [
            p["title"], p["status"], p["priority"], p["tag"] or "", p["due_at"] or "", p["completed_at"] or "",
            p["late_minutes"] if p["late_minutes"] is not None else "",
            p["progress"]["done"], p["progress"]["total"], round(p["tracked_seconds"] / 60),
            p["goal"], html_to_text(p["body_html"])[:2000],
        ]
        # Neutralise spreadsheet formula injection in user-written cells.
        writer.writerow([f"'{v}" if isinstance(v, str) and v[:1] in ("=", "+", "-", "@") else v for v in row])
    return buf.getvalue()


def import_json(conn, user, data) -> dict:
    """Restores plans from an export. Every plan gets a new id, so importing twice duplicates
    rather than overwrites; approvers are not carried over (they may not exist here)."""
    created, skipped = 0, 0
    for item in data.plans:
        if not str(item.get("title") or "").strip():
            skipped += 1
            continue
        steps = [s.get("text", "") for s in item.get("steps", []) if isinstance(s, dict)]
        try:
            plan = PlanCreate(
                title=str(item["title"]).strip()[:200],
                body_html=item.get("body_html", "") or "",
                tag=item.get("tag"),
                color=item.get("color", "yellow"),
                x=item.get("x", 0),
                y=item.get("y", 0),
                due_at=item.get("due_at"),
                remind_minutes=item.get("remind_minutes"),
                goal=item.get("goal", "") or "",
                done_criteria=item.get("done_criteria", "") or "",
                priority=item.get("priority", "normal"),
                recurrence=item.get("recurrence"),
                steps=steps[:50],
            )
        except (ValidationError, TypeError, ValueError):
            skipped += 1
            continue
        create(conn, user["id"], plan)
        created += 1
    return {"created": created, "skipped": skipped}


# ---- iCalendar ------------------------------------------------------------------------------

def ics_token(conn, user, rotate: bool = False) -> str:
    if user["ics_token"] and not rotate:
        return user["ics_token"]
    token = secrets.token_urlsafe(24)
    conn.execute("UPDATE users SET ics_token = ? WHERE id = ?", (token, user["id"]))
    return token


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\r\n", "\\n").replace("\n", "\\n")


def _fold(line: str) -> str:
    """RFC 5545: lines longer than 75 octets continue on the next line after a space."""
    raw = line.encode()
    if len(raw) <= 75:
        return line
    parts, chunk = [], b""
    for ch in line:
        b = ch.encode()
        if len(chunk) + len(b) > (75 if not parts else 74):
            parts.append(chunk.decode())
            chunk = b""
        chunk += b
    parts.append(chunk.decode())
    return "\r\n ".join(parts)


def _ics_time(iso: str) -> str:
    return iso.replace("-", "").replace(":", "")


def calendar_feed(conn, token: str) -> str:
    user = conn.execute("SELECT * FROM users WHERE ics_token = ?", (token,)).fetchone()
    if user is None or not token:
        raise ApiError(404, "calendar_not_found")
    rows = conn.execute(
        """SELECT id, title, due_at, status, goal, updated_at FROM plans WHERE owner_id = ? AND deleted_at IS NULL
           AND due_at IS NOT NULL AND status != 'cancelled' ORDER BY due_at""",
        (user["id"],),
    ).fetchall()
    stamp = _ics_time(timeutil.to_iso(timeutil.now()))
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Reja Kanvas//UZ", "CALSCALE:GREGORIAN", "METHOD:PUBLISH", f"X-WR-CALNAME:{_escape('Reja — ' + user['name'])}"]
    for r in rows:
        start = timeutil.parse_iso(r["due_at"])
        end = start + timedelta(minutes=30)
        lines += [
            "BEGIN:VEVENT",
            f"UID:{r['id']}@reja",
            f"DTSTAMP:{stamp}",
            f"DTSTART:{_ics_time(timeutil.to_iso(start))}",
            f"DTEND:{_ics_time(timeutil.to_iso(end))}",
            f"SUMMARY:{_escape(('✓ ' if r['status'] == 'done' else '') + r['title'])}",
            f"DESCRIPTION:{_escape(r['goal'] or '')}",
            "STATUS:CONFIRMED",
            f"LAST-MODIFIED:{_ics_time(r['updated_at'])}",
            "END:VEVENT",
        ]
    lines.append("END:VCALENDAR")
    return "\r\n".join(_fold(line) for line in lines) + "\r\n"
