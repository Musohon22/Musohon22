"""Tenant-side subscription view, plan change, cancellation, support tickets."""

from __future__ import annotations

from datetime import timedelta

from pydantic import BaseModel, Field

from .. import db as dbm
from ..errors import conflict
from ..http import Ctx, invalidate_subscription_cache, route
from ..services import billing_svc, tenancy
from ..util import iso, loads, new_id, now_iso, utcnow

SLA_HOURS = {"starter": 24, "business": 4, "professional": 2, "enterprise": 0.5}


class ChangePlanIn(BaseModel):
    plan_code: str
    billing_cycle: str | None = Field(default=None, pattern="^(monthly|annual)$")


class CancelIn(BaseModel):
    reason: str = Field(pattern="^(price|missing_feature|quality|company_closed|other_system|other)$")
    comment: str | None = Field(default=None, max_length=2000)


class TicketIn(BaseModel):
    subject: str = Field(min_length=5, max_length=200)
    body: str = Field(min_length=10, max_length=5000)
    priority: str = Field(default="normal", pattern="^(low|normal|high|critical)$")


@route("GET", "/api/v1/billing", perm="billing.read", mfa_exempt=True)
def overview(ctx: Ctx):
    sub = billing_svc.current_subscription(ctx.conn, ctx.tenant_id)
    plan = tenancy.tenant_plan(ctx.conn, ctx.tenant_id)
    invoices = dbm.all_(ctx.conn, "SELECT id, number, period_start, period_end, amount_cents, currency, status, issued_at, "
                                  "due_at, paid_at FROM invoices WHERE tenant_id = ? ORDER BY issued_at DESC", (ctx.tenant_id,))
    plans = []
    for p in dbm.all_(ctx.conn, "SELECT * FROM plans WHERE active = 1 ORDER BY price_cents DESC"):
        p["limits"] = loads(p["limits"], {})
        p["features"] = loads(p["features"], [])
        plans.append(p)
    return {"subscription": sub, "plan": plan, "usage": tenancy.usage(ctx.conn, ctx.tenant_id),
            "mrr_cents": billing_svc.mrr_cents(ctx.conn, sub) if sub else 0, "invoices": invoices, "plans": plans,
            "guarantee": "To'lov muammosi davomat ma'lumotlariga va terminallar ishiga ta'sir qilmaydi; eksport har doim ochiq."}


@route("POST", "/api/v1/billing/change-plan", perm="billing.manage")
def change_plan(ctx: Ctx, body: ChangePlanIn):
    new = tenancy.plan(ctx.conn, body.plan_code)
    usage = tenancy.usage(ctx.conn, ctx.tenant_id)
    over = {k: [usage[k], new["limits"].get(k)] for k in usage
            if new["limits"].get(k) is not None and usage[k] > new["limits"][k]}
    if over:
        raise conflict("Your usage exceeds the target plan limits", "PLAN_DOWNGRADE_BLOCKED", over=over)
    if body.plan_code == "enterprise":
        raise conflict("Enterprise is contracted individually — contact sales", "ENTERPRISE_CONTACT_SALES")
    sub = billing_svc.current_subscription(ctx.conn, ctx.tenant_id)
    ctx.conn.execute("UPDATE tenants SET plan_code = ? WHERE id = ?", (body.plan_code, ctx.tenant_id))
    ctx.conn.execute("UPDATE subscriptions SET plan_code = ?, billing_cycle = COALESCE(?, billing_cycle), updated_at = ? "
                     "WHERE id = ?", (body.plan_code, body.billing_cycle, now_iso(), sub["id"]))
    invalidate_subscription_cache(ctx.tenant_id)
    ctx.audit("billing.plan_changed", "subscription", sub["id"], before={"plan": sub["plan_code"]},
              after=body.model_dump())
    return {"ok": True, "plan_code": body.plan_code}


@route("POST", "/api/v1/billing/cancel", perm="billing.manage", mfa_exempt=False)
def cancel(ctx: Ctx, body: CancelIn):
    sub = billing_svc.current_subscription(ctx.conn, ctx.tenant_id)
    if sub["status"] in ("cancelled", "archived"):
        raise conflict("Subscription already cancelled", "ALREADY_CANCELLED")
    dbm.insert(ctx.conn, "cancellation_feedback", {"id": new_id(), "tenant_id": ctx.tenant_id, "reason": body.reason,
                                                   "comment": body.comment, "created_at": now_iso()})
    ctx.conn.execute("UPDATE subscriptions SET cancel_at = period_end, cancel_reason = ?, updated_at = ? WHERE id = ?",
                     (body.reason, now_iso(), sub["id"]))
    ctx.audit("billing.cancel_requested", "subscription", sub["id"], after=body.model_dump())
    return {"ok": True, "cancel_at": sub["period_end"],
            "note": "Obuna joriy davr oxirigacha ishlaydi. To'liq eksport istalgan vaqtda: Sozlamalar → Backup."}


@route("GET", "/api/v1/support/tickets", perm="settings.read")
def my_tickets(ctx: Ctx):
    return {"items": dbm.all_(ctx.conn, "SELECT * FROM support_tickets WHERE tenant_id = ? ORDER BY created_at DESC",
                              (ctx.tenant_id,))}


@route("POST", "/api/v1/support/tickets", perm="settings.read")
def open_ticket(ctx: Ctx, body: TicketIn):
    plan = tenancy.tenant_plan(ctx.conn, ctx.tenant_id)
    hours = SLA_HOURS.get(plan["code"], 24)
    if body.priority == "critical":
        hours = min(hours, 1)
    row = {"id": new_id(), "tenant_id": ctx.tenant_id, "subject": body.subject, "body": body.body,
           "priority": body.priority, "status": "open", "channel": "portal", "created_by": ctx.actor, "assignee": None,
           "sla_due_at": iso(utcnow() + timedelta(hours=hours)), "created_at": now_iso(), "updated_at": now_iso()}
    dbm.insert(ctx.conn, "support_tickets", row)
    ctx.audit("support.ticket_opened", "ticket", row["id"], after={"subject": body.subject, "priority": body.priority})
    return 201, row
