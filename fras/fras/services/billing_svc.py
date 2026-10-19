"""Subscription billing: invoicing, payments, dunning (business tab, section 6.3).

Billing state never touches attendance: terminals keep passing people and
events keep being accepted in every subscription status. Restrictions only
apply to growth actions (new employees/devices) and, when suspended, to
admin-panel writes. Data export always stays available.
"""

from __future__ import annotations

from datetime import date, timedelta

from .. import db as dbm
from ..util import dumps, iso, new_id, now_iso, parse_dt, utcnow
from . import notify, tenancy

# days overdue → status (section 6.3)
DUNNING = [(180, "archived"), (90, "cancelled"), (30, "suspended"), (15, "restricted"), (0, "past_due")]


def monthly_price_cents(plan: dict, employees: int, billing_cycle: str, discount_pct: int = 0) -> int:
    if plan["price_model"] == "flat":
        base = plan["price_cents"]
    else:
        base = max(plan["min_monthly_cents"], plan["price_cents"] * employees)
    if billing_cycle == "monthly":
        base = round(base * (100 + plan.get("monthly_markup_pct", 15)) / 100)
    return round(base * (100 - discount_pct) / 100)


def billable_employees(conn, tenant_id: str) -> int:
    return dbm.scalar(conn, "SELECT COUNT(*) FROM employees WHERE tenant_id = ? AND status = 'active'", (tenant_id,))


def current_subscription(conn, tenant_id: str) -> dict | None:
    return dbm.one(conn, "SELECT * FROM subscriptions WHERE tenant_id = ? ORDER BY created_at DESC LIMIT 1", (tenant_id,))


def mrr_cents(conn, sub: dict) -> int:
    if sub["status"] in ("trialing", "cancelled", "archived"):
        return 0
    plan = tenancy.plan(conn, sub["plan_code"])
    return monthly_price_cents(plan, billable_employees(conn, sub["tenant_id"]), sub["billing_cycle"], sub["discount_pct"])


def next_invoice_number(conn) -> str:
    year = date.today().year
    n = dbm.scalar(conn, "SELECT COUNT(*) FROM invoices WHERE number LIKE ?", (f"FRAS-{year}-%",)) + 1
    return f"FRAS-{year}-{n:05d}"


def issue_invoice(conn, sub: dict, period_start: date, period_end: date) -> dict | None:
    if dbm.one(conn, "SELECT 1 AS x FROM invoices WHERE subscription_id = ? AND period_start = ?",
               (sub["id"], period_start.isoformat())):
        return None
    plan = tenancy.plan(conn, sub["plan_code"])
    emp = billable_employees(conn, sub["tenant_id"])
    months = 12 if sub["billing_cycle"] == "annual" else 1
    monthly = monthly_price_cents(plan, emp, sub["billing_cycle"], sub["discount_pct"])
    lines = [{"description": f"{plan['name']} obunasi ({emp} faol xodim)", "months": months,
              "unit_cents": monthly, "amount_cents": monthly * months}]
    amount = sum(line["amount_cents"] for line in lines)
    inv = {"id": new_id(), "tenant_id": sub["tenant_id"], "subscription_id": sub["id"],
           "number": next_invoice_number(conn), "period_start": period_start.isoformat(),
           "period_end": period_end.isoformat(), "lines": dumps(lines), "amount_cents": amount, "currency": "USD",
           "status": "issued", "issued_at": now_iso(), "due_at": iso(utcnow() + timedelta(days=10)), "paid_at": None}
    dbm.insert(conn, "invoices", inv)
    for u in notify.users_with_permission(conn, sub["tenant_id"], "billing.read"):
        notify.notify_user(conn, sub["tenant_id"], u["id"], "invoice_issued", "Yangi hisob-faktura",
                           f"{inv['number']}: ${amount / 100:,.2f}", "/app/settings/billing", ("in_app", "email"))
    return inv


def record_payment(conn, invoice: dict, amount_cents: int, method: str, reference: str | None, actor: str) -> dict:
    dbm.insert(conn, "payments", {"id": new_id(), "tenant_id": invoice["tenant_id"], "invoice_id": invoice["id"],
                                  "amount_cents": amount_cents, "method": method, "reference": reference,
                                  "recorded_by": actor, "created_at": now_iso()})
    paid = dbm.scalar(conn, "SELECT COALESCE(SUM(amount_cents), 0) FROM payments WHERE invoice_id = ?", (invoice["id"],))
    if paid >= invoice["amount_cents"]:
        conn.execute("UPDATE invoices SET status = 'paid', paid_at = ? WHERE id = ?", (now_iso(), invoice["id"]))
    reconcile_status(conn, invoice["tenant_id"])
    return {"paid_cents": paid, "fully_paid": paid >= invoice["amount_cents"]}


def overdue_days(conn, tenant_id: str) -> int:
    row = dbm.one(conn, "SELECT MIN(due_at) AS due FROM invoices WHERE tenant_id = ? AND status IN ('issued','overdue')",
                  (tenant_id,))
    if not row or not row["due"]:
        return -1
    days = (utcnow() - parse_dt(row["due"])).days
    return days if utcnow() > parse_dt(row["due"]) else -1


def reconcile_status(conn, tenant_id: str) -> str:
    """Move a subscription along the dunning ladder (or back to active once paid)."""
    from ..http import invalidate_subscription_cache
    sub = current_subscription(conn, tenant_id)
    if not sub:
        return "none"
    if sub["status"] in ("trialing",):
        if sub["trial_ends_at"] and parse_dt(sub["trial_ends_at"]) < utcnow():
            new = "past_due" if overdue_days(conn, tenant_id) >= 0 else "active"
        else:
            return sub["status"]
    elif sub["status"] == "cancelled" and sub["cancel_at"] and overdue_days(conn, tenant_id) < 0:
        return sub["status"]   # voluntary cancellation is not reversed by payments
    else:
        days = overdue_days(conn, tenant_id)
        pending = sub["payment_pending_until"] and parse_dt(sub["payment_pending_until"]) > utcnow()
        if days < 0:
            new = "active"
        elif pending:
            new = sub["status"] if sub["status"] in ("past_due", "active") else "past_due"
        else:
            new = next(status for threshold, status in DUNNING if days >= threshold)
    if new != sub["status"]:
        conn.execute("UPDATE subscriptions SET status = ?, updated_at = ? WHERE id = ?", (new, now_iso(), sub["id"]))
        conn.execute("UPDATE invoices SET status = 'overdue' WHERE tenant_id = ? AND status = 'issued' AND due_at < ?",
                     (tenant_id, now_iso()))
        invalidate_subscription_cache(tenant_id)
        messages = {
            "past_due": "To'lov muddati o'tdi. Davomat ishlashda davom etadi.",
            "restricted": "Obuna cheklangan: yangi xodim va qurilma qo'shish to'xtatildi. Davomat ishlaydi.",
            "suspended": "Admin panel faqat o'qish rejimida. Terminallar va eksport ishlaydi.",
            "cancelled": "Obuna bekor qilindi. Ma'lumotlar 90 kun saqlanadi, eksport ochiq.",
            "archived": "Ma'lumotlar o'chirish uchun rejalashtirildi (30 kunlik ogohlantirish).",
            "active": "To'lov qabul qilindi. Barcha imkoniyatlar tiklandi.",
        }
        for u in notify.users_with_permission(conn, tenant_id, "billing.read"):
            notify.notify_user(conn, tenant_id, u["id"], "billing_status", f"Obuna holati: {new}",
                               messages.get(new, new), "/app/settings/billing", ("in_app", "email", "telegram"))
    return new


def run_billing(conn, today: date | None = None) -> dict:
    today = today or date.today()
    issued = 0
    for sub in dbm.all_(conn, "SELECT s.* FROM subscriptions s WHERE s.created_at = (SELECT MAX(created_at) FROM "
                              "subscriptions x WHERE x.tenant_id = s.tenant_id) AND s.status NOT IN ('cancelled','archived')"):
        if sub["status"] == "trialing" and sub["trial_ends_at"] and parse_dt(sub["trial_ends_at"]).date() > today:
            continue
        start = parse_dt(sub["period_start"]).date()
        months = 12 if sub["billing_cycle"] == "annual" else 1
        # current billing period containing today
        while True:
            y, m = divmod(start.month - 1 + months, 12)
            nxt = start.replace(year=start.year + y, month=m + 1, day=min(start.day, 28))
            if nxt > today:
                break
            start = nxt
        end = nxt - timedelta(days=1)
        if issue_invoice(conn, sub, start, end):
            issued += 1
    changed = 0
    for t in dbm.all_(conn, "SELECT id FROM tenants WHERE status = 'active'"):
        before = (current_subscription(conn, t["id"]) or {}).get("status")
        if reconcile_status(conn, t["id"]) != before:
            changed += 1
    return {"invoices_issued": issued, "status_changes": changed}


def tenant_health(conn, tenant_id: str) -> dict:
    """Health score (business tab 7.2). Weights are an initial hypothesis."""
    active = billable_employees(conn, tenant_id) or 0
    with_events = dbm.scalar(conn, "SELECT COUNT(DISTINCT employee_id) FROM attendance_events WHERE tenant_id = ? AND "
                                   "captured_at >= ?", (tenant_id, iso(utcnow() - timedelta(days=30))))
    enrolled = dbm.scalar(conn, "SELECT COUNT(*) FROM employees WHERE tenant_id = ? AND status = 'active' AND "
                                "(biometric_status = 'active' OR card_no IS NOT NULL OR pin_hash IS NOT NULL)", (tenant_id,))
    admins_active = dbm.scalar(conn, "SELECT COUNT(DISTINCT user_id) FROM login_history WHERE tenant_id = ? AND success = 1 "
                                     "AND created_at >= ?", (tenant_id, iso(utcnow() - timedelta(days=7))))
    closed_recent = dbm.scalar(conn, "SELECT COUNT(*) FROM periods WHERE tenant_id = ? AND status = 'closed' AND closed_at >= ?",
                               (tenant_id, iso(utcnow() - timedelta(days=45))))
    devices = dbm.all_(conn, "SELECT status FROM devices WHERE tenant_id = ? AND status <> 'decommissioned'", (tenant_id,))
    dev_ok = (sum(1 for d in devices if d["status"] in ("online", "degraded")) / len(devices)) if devices else 0
    critical = dbm.scalar(conn, "SELECT COUNT(*) FROM support_tickets WHERE tenant_id = ? AND status IN ('open','in_progress') "
                                "AND priority IN ('high','critical')", (tenant_id,))
    parts = {
        "active_ratio": (with_events / active) if active else 0,
        "biometric_coverage": (enrolled / active) if active else 0,
        "hr_activity": min(1.0, admins_active / 2),
        "timesheet_from_system": 1.0 if closed_recent else 0.0,
        "technical": dev_ok,
        "support": 1.0 if not critical else 0.3,
    }
    weights = {"active_ratio": 25, "biometric_coverage": 15, "hr_activity": 15, "timesheet_from_system": 20,
               "technical": 15, "support": 10}
    score = round(sum(parts[k] * w for k, w in weights.items()))
    return {"score": score, "parts": {k: round(v, 2) for k, v in parts.items()}, "weights": weights}

