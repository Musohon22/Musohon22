"""Starter templates for an empty canvas. Plans land in the zone columns of the canvas."""

from datetime import timedelta

from . import timeutil
from .plans import create
from .schemas import PlanCreate

# Canvas zone columns (world coordinates); the frontend draws the same columns.
ZONE_X = {"today": 40, "tomorrow": 400, "week": 760, "later": 1120}
ZONE_TOP = 90
ROW_GAP = 200

TEMPLATES = {
    "work_week": {
        "plans": [
            ("today", 0, (10, 0), "Ish", "yellow", "Haftalik yig'ilishga tayyorlanish", ["Kun tartibini yozish", "Hisobotni yangilash"]),
            ("today", 0, (16, 0), "Ish", "sky", "Pochtani tartibga keltirish", ["Muhim xatlarga javob", "Arxivlash"]),
            ("tomorrow", 1, (11, 0), "Ish", "peach", "Mijoz bilan uchrashuv", ["Taqdimot", "Savollar ro'yxati"]),
            ("week", 4, (17, 0), "Ish", "lilac", "Haftalik hisobot", ["Natijalar", "Kechikkan vazifalar", "Keyingi hafta rejasi"]),
        ],
    },
    "student": {
        "plans": [
            ("today", 0, (19, 0), "O'qish", "lilac", "Uy vazifasi: matematika", ["1–10 misollar", "Tekshirish"]),
            ("today", 0, (21, 0), "O'qish", "yellow", "Kitob: 30 sahifa", []),
            ("tomorrow", 1, (8, 30), "O'qish", "sky", "Nazorat ishiga tayyorgarlik", ["Mavzularni takrorlash", "Test yechish"]),
            ("week", 5, (12, 0), "O'qish", "mint", "Loyiha ishi", ["Mavzu tanlash", "Reja", "Taqdimot"]),
        ],
    },
    "sport": {
        "plans": [
            ("today", 0, (7, 0), "Sog'liq", "mint", "Ertalabki yugurish — 3 km", []),
            ("tomorrow", 1, (18, 0), "Sog'liq", "mint", "Sport zal: kuch mashqlari", ["Isinish", "Asosiy mashqlar", "Cho'zilish"]),
            ("week", 3, (7, 0), "Sog'liq", "peach", "Haftalik vaznni o'lchash", []),
        ],
    },
    "family": {
        "plans": [
            ("today", 0, (18, 0), "Uy", "peach", "Bozorlik", ["Non", "Meva", "Sut mahsulotlari"]),
            ("tomorrow", 1, (19, 0), "Uy", "yellow", "Oilaviy kechki ovqat", []),
            ("week", 6, (11, 0), "Uy", "sky", "Dam olish kuni sayohat", ["Joy tanlash", "Yo'l rejasi"]),
        ],
    },
}


def catalog() -> list[dict]:
    return [{"key": k, "count": len(v["plans"])} for k, v in TEMPLATES.items()]


def apply(conn, user, key: str) -> list[dict]:
    template = TEMPLATES.get(key)
    if template is None:
        from .errors import ApiError
        raise ApiError(404, "template_not_found")
    tz = user["tz"]
    today = timeutil.local_today(tz)
    rows_used: dict[str, int] = {}
    existing = conn.execute(
        "SELECT x, y FROM plans WHERE owner_id = ? AND deleted_at IS NULL", (user["id"],)
    ).fetchall()
    out = []
    for zone, offset, (hour, minute), tag, color, title, steps in template["plans"]:
        x = ZONE_X[zone]
        # Start below anything already in this column so templates never stack on existing cards.
        column_bottom = max((r["y"] for r in existing if abs(r["x"] - x) < 200), default=ZONE_TOP - ROW_GAP)
        row = rows_used.get(zone, 0)
        y = max(ZONE_TOP, column_bottom + ROW_GAP) + row * ROW_GAP
        rows_used[zone] = row + 1
        due = timeutil.at_local(today + timedelta(days=offset), hour, minute, tz)
        out.append(create(conn, user["id"], PlanCreate(
            title=title, tag=tag, color=color, x=x, y=y, due_at=due, steps=steps,
        )))
    return out
