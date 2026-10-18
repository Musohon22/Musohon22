"""Import from other tools: generic CSV (any of Uzbek/Russian/English headers), Todoist CSV
export and Trello JSON export. Nothing is fetched from those services; the user uploads the file."""

import csv
import io
import json
from datetime import datetime

from pydantic import ValidationError

from . import timeutil
from .errors import ApiError
from .plans import create
from .schemas import PlanCreate

MAX_ROWS = 2000
HEADERS = {
    "title": {"title", "name", "task", "content", "nomi", "sarlavha", "reja", "vazifa", "название", "задача", "заголовок"},
    "due": {"due", "due date", "date", "deadline", "muddat", "sana", "срок", "дата"},
    "tag": {"tag", "tags", "label", "labels", "teg", "тег", "метка"},
    "priority": {"priority", "ustuvorlik", "приоритет"},
    "notes": {"notes", "description", "desc", "izoh", "qayd", "описание", "заметки"},
}
PRIORITY_WORDS = {
    "urgent": "urgent", "shoshilinch": "urgent", "срочно": "urgent", "1": "urgent", "p1": "urgent",
    "high": "high", "yuqori": "high", "высокий": "high", "2": "high", "p2": "high",
    "low": "low", "past": "low", "низкий": "low", "4": "low", "p4": "low",
}


def _parse_date(value: str, tz: str) -> str | None:
    value = (value or "").strip()
    if not value:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%d %H:%M", "%Y-%m-%d", "%d.%m.%Y %H:%M", "%d.%m.%Y", "%d/%m/%Y"):
        try:
            dt = datetime.strptime(value.replace("Z", "+0000"), fmt)
        except ValueError:
            continue
        if dt.tzinfo is None:
            hour, minute = (dt.hour, dt.minute) if ("%H" in fmt) else (9, 0)
            dt = timeutil.at_local(dt.date(), hour, minute, tz)
        return timeutil.to_iso(dt)
    return None


def _make(conn, user, rows: list[dict]) -> dict:
    created = skipped = 0
    x, y = 40, 90
    for i, row in enumerate(rows[:MAX_ROWS]):
        title = (row.get("title") or "").strip()[:200]
        if not title:
            skipped += 1
            continue
        try:
            plan = PlanCreate(
                title=title,
                body_html=f"<p>{row['notes']}</p>" if row.get("notes") else "",
                tag=(row.get("tag") or None) and row["tag"][:30],
                priority=PRIORITY_WORDS.get(str(row.get("priority") or "").strip().lower(), "normal"),
                due_at=row.get("due"),
                steps=[s[:300] for s in row.get("steps", [])][:50],
                x=x + (i // 12) * 360,
                y=y + (i % 12) * 200,
            )
        except (ValidationError, ValueError):
            skipped += 1
            continue
        create(conn, user["id"], plan)
        created += 1
    skipped += max(0, len(rows) - MAX_ROWS)
    return {"created": created, "skipped": skipped}


def _from_csv(text: str, tz: str) -> list[dict]:
    reader = csv.reader(io.StringIO(text.lstrip("﻿")))
    try:
        header = [h.strip().lower() for h in next(reader)]
    except StopIteration:
        return []
    index = {field: next((i for i, h in enumerate(header) if h in names), None) for field, names in HEADERS.items()}
    if index["title"] is None:
        raise ApiError(400, "import_no_title_column")
    rows = []
    for cells in reader:
        get = lambda f: cells[index[f]].strip() if index[f] is not None and index[f] < len(cells) else ""
        rows.append({"title": get("title"), "due": _parse_date(get("due"), tz), "tag": get("tag").split(",")[0].strip(),
                     "priority": get("priority"), "notes": get("notes")})
    return rows


def _from_todoist(text: str, tz: str) -> list[dict]:
    """Todoist CSV: TYPE,CONTENT,DESCRIPTION,PRIORITY,INDENT,...,DATE. Sub-tasks (INDENT>1) become steps.
    Todoist's PRIORITY 4 is its highest."""
    reader = csv.DictReader(io.StringIO(text.lstrip("﻿")))
    rows: list[dict] = []
    for r in reader:
        r = {k.strip().upper(): (v or "").strip() for k, v in r.items() if k}
        if r.get("TYPE", "task") != "task" or not r.get("CONTENT"):
            continue
        content = r["CONTENT"]
        labels = [w[1:] for w in content.split() if w.startswith("@")]
        title = " ".join(w for w in content.split() if not w.startswith("@"))
        if r.get("INDENT", "1") not in ("", "1") and rows:
            rows[-1]["steps"].append(title)
            continue
        prio = {"4": "urgent", "3": "high", "2": "normal", "1": "normal"}.get(r.get("PRIORITY", ""), "normal")
        rows.append({"title": title, "notes": r.get("DESCRIPTION", ""), "priority": prio,
                     "tag": labels[0] if labels else "", "due": _parse_date(r.get("DATE", ""), tz), "steps": []})
    return rows


def _from_trello(text: str, tz: str) -> list[dict]:
    try:
        board = json.loads(text)
    except json.JSONDecodeError:
        raise ApiError(400, "import_bad_file")
    if not isinstance(board, dict) or not isinstance(board.get("cards"), list):
        raise ApiError(400, "import_bad_file")
    checklists = {c["id"]: c for c in board.get("checklists", []) if isinstance(c, dict) and "id" in c}
    rows = []
    for card in board["cards"]:
        if not isinstance(card, dict) or card.get("closed"):
            continue
        steps = []
        for cid in card.get("idChecklists", []):
            steps += [i.get("name", "") for i in checklists.get(cid, {}).get("checkItems", []) if i.get("name")]
        labels = [label.get("name") for label in card.get("labels", []) if isinstance(label, dict) and label.get("name")]
        rows.append({"title": card.get("name", ""), "notes": card.get("desc", ""), "tag": labels[0] if labels else "",
                     "due": _parse_date(card.get("due") or "", tz), "steps": steps})
    return rows


def run(conn, user, fmt: str, content: str) -> dict:
    parser = {"csv": _from_csv, "todoist": _from_todoist, "trello": _from_trello}[fmt]
    return _make(conn, user, parser(content, user["tz"]))
