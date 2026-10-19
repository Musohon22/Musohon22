"""SaaS operator panel (/platform): tenants, plans, invoices, payments, dunning, MRR, churn, tickets, audit."""

from __future__ import annotations

from datetime import date, timedelta

from pydantic import BaseModel, Field

from .. import db as dbm
from ..errors import conflict, forbidden, not_found, unprocessable
from ..http import Ctx, invalidate_subscription_cache, route
from ..services import billing_svc, tenancy
from ..util import dumps, iso, loads, local_today, now_iso, utcnow


class TenantIn(BaseModel):
    slug: str = Field(min_length=2, max_length=32, pattern=r"^[a-z0-9\-]+$")
    name: str = Field(min_length=2, max_length=120)
    legal_name: str | None = Field(default=None, max_length=200)
    tin: str | None = Field(default=None, pattern=r"^\d{9}$")
    plan_code: str
    billing_cycle: str = Field(default="annual", pattern="^(monthly|annual)$")
    trial_days: int = Field(default=0, ge=0, le=60)
    deployment: str = Field(default="cloud", pattern="^(cloud|onprem)$")
    admin_email: str = Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    admin_name: str = Field(min_length=2, max_length=120)


class PlanChangeIn(BaseModel):
    plan_code: str
    discount_pct: int = Field(default=0, ge=0, le=50)


class DaysIn(BaseModel):
    days: int = Field(ge=1, le=60)
    note: str = Field(min_length=5, max_length=300)


class PaymentIn(BaseModel):
    amount_cents: int = Field(gt=0)
    method: str = Field(pattern="^(bank_transfer|card|cash|other)$")
    reference: str = Field(min_length=3, max_length=120)


class PlanPriceIn(BaseModel):
    price_cents: int = Field(gt=0)
    min_monthly_cents: int = Field(ge=0)
    limits: dict
    features: list[str]


class TicketPatchIn(BaseModel):
    status: str | None = Field(default=None, pattern="^(open|in_progress|resolved|closed)$")
    priority: str | None = Field(default=None, pattern="^(low|normal|high|critical)$")
    assignee: str | None = None


def _need(ctx: Ctx, perm: str) -> None:
    if not ctx.can(perm):
        raise forbidden(f"Platform permission {perm} required")


def _audit(ctx: Ctx, action: str, obj_type: str, obj_id: str | None, after: dict | None = None) -> None:
    ctx.audit(action, obj_type, obj_id, after=after, tenant_id=None)


@route("GET", "/api/v1/platform/dashboard", auth="platform")
def dashboard(ctx: Ctx):
    _need(ctx, "platform.read")
    subs = dbm.all_(ctx.conn, "SELECT s.* FROM subscriptions s WHERE s.created_at = (SELECT MAX(created_at) FROM "
                              "subscriptions x WHERE x.tenant_id = s.tenant_id)")
    mrr = {s["tenant_id"]: billing_svc.mrr_cents(ctx.conn, s) for s in subs}
    month_start = local_today().replace(day=1).isoformat()
    new_tenants = {t["id"] for t in dbm.all_(ctx.conn, "SELECT id FROM tenants WHERE created_at >= ?", (month_start,))}
    churned = dbm.all_(ctx.conn, "SELECT tenant_id FROM subscriptions WHERE status IN ('cancelled','archived') AND "
                                 "updated_at >= ?", (month_start,))
    statuses = {}
    for s in subs:
        statuses[s["status"]] = statuses.get(s["status"], 0) + 1
    total = sum(mrr.values())
    tickets = dbm.scalar(ctx.conn, "SELECT COUNT(*) FROM support_tickets WHERE status IN ('open','in_progress')")
    breached = dbm.scalar(ctx.conn, "SELECT COUNT(*) FROM support_tickets WHERE status IN ('open','in_progress') AND "
                                    "sla_due_at < ?", (now_iso(),))
    return {"mrr_cents": total, "arr_cents": total * 12,
            "new_mrr_cents": sum(v for k, v in mrr.items() if k in new_tenants),
            "churned_tenants_this_month": len(churned), "tenants_by_status": statuses,
            "tenants": len(subs), "open_tickets": tickets, "sla_breached": breached,
            "offline_devices": dbm.scalar(ctx.conn, "SELECT COUNT(*) FROM devices WHERE status = 'offline'"),
            "overdue_invoices": dbm.scalar(ctx.conn, "SELECT COUNT(*) FROM invoices WHERE status = 'overdue'")}


@route("GET", "/api/v1/platform/tenants", auth="platform")
def tenants(ctx: Ctx):
    _need(ctx, "platform.read")
    rows = dbm.all_(ctx.conn, "SELECT t.id, t.slug, t.name, t.plan_code, t.deployment, t.created_at, t.status AS tenant_status "
                              "FROM tenants t ORDER BY t.name")
    for t in rows:
        sub = billing_svc.current_subscription(ctx.conn, t["id"])
        t["status"] = sub["status"] if sub else "none"
        t["mrr_cents"] = billing_svc.mrr_cents(ctx.conn, sub) if sub else 0
        t["usage"] = tenancy.usage(ctx.conn, t["id"])
        t["limits"] = tenancy.plan(ctx.conn, t["plan_code"])["limits"]
        t["health"] = billing_svc.tenant_health(ctx.conn, t["id"])["score"]
    q = (ctx.q("q") or "").lower()
    if q:
        rows = [r for r in rows if q in r["name"].lower() or q in r["slug"]]
    if ctx.q("status"):
        rows = [r for r in rows if r["status"] == ctx.q("status")]
    return {"items": rows}


@route("POST", "/api/v1/platform/tenants", auth="platform")
def create_tenant(ctx: Ctx, body: TenantIn):
    _need(ctx, "platform.tenants")
    res = tenancy.create_tenant(ctx.conn, ctx.settings.master_key, slug=body.slug, name=body.name,
                                plan_code=body.plan_code, admin_email=body.admin_email, admin_name=body.admin_name,
                                legal_name=body.legal_name, tin=body.tin, trial_days=body.trial_days,
                                deployment=body.deployment, billing_cycle=body.billing_cycle)
    _audit(ctx, "platform.tenant_created", "tenant", res["tenant_id"], {**body.model_dump(), "invite": "issued"})
    return 201, {"tenant_id": res["tenant_id"],
                 "invite_link": f"{ctx.settings.public_base_url}/app/invite?org={body.slug}&token={res['invite_token']}"}


def _tenant(ctx: Ctx) -> dict:
    t = dbm.one(ctx.conn, "SELECT id, slug, name, legal_name, tin, plan_code, deployment, status, created_at FROM tenants "
                          "WHERE id = ?", (ctx.path["id"],))
    if not t:
        raise not_found("Tenant")
    return t


@route("GET", "/api/v1/platform/tenants/{id}", auth="platform")
def tenant_card(ctx: Ctx):
    _need(ctx, "platform.read")
    t = _tenant(ctx)
    sub = billing_svc.current_subscription(ctx.conn, t["id"])
    invoices = dbm.all_(ctx.conn, "SELECT id, number, period_start, period_end, amount_cents, status, issued_at, due_at, paid_at "
                                  "FROM invoices WHERE tenant_id = ? ORDER BY issued_at DESC", (t["id"],))
    devices = dbm.all_(ctx.conn, "SELECT status, COUNT(*) AS n FROM devices WHERE tenant_id = ? GROUP BY status", (t["id"],))
    tickets = dbm.all_(ctx.conn, "SELECT * FROM support_tickets WHERE tenant_id = ? ORDER BY created_at DESC LIMIT 50",
                       (t["id"],))
    # platform staff see metadata only — no employee data
    return {"tenant": t, "subscription": sub, "mrr_cents": billing_svc.mrr_cents(ctx.conn, sub) if sub else 0,
            "usage": tenancy.usage(ctx.conn, t["id"]), "plan": tenancy.plan(ctx.conn, t["plan_code"]),
            "invoices": invoices, "devices": devices, "tickets": tickets,
            "health": billing_svc.tenant_health(ctx.conn, t["id"])}


@route("POST", "/api/v1/platform/tenants/{id}/plan", auth="platform")
def change_plan(ctx: Ctx, body: PlanChangeIn):
    _need(ctx, "platform.billing")
    t = _tenant(ctx)
    new_plan = tenancy.plan(ctx.conn, body.plan_code)
    usage = tenancy.usage(ctx.conn, t["id"])
    over = {k: (usage[k], new_plan["limits"].get(k)) for k in usage
            if new_plan["limits"].get(k) is not None and usage[k] > new_plan["limits"][k]}
    if over:
        raise conflict("Current usage exceeds the target plan limits", "PLAN_DOWNGRADE_BLOCKED", over=over)
    if body.discount_pct > 20 and ctx.p.platform_role != "owner":
        raise forbidden("Discounts above 20% need the platform owner")
    ctx.conn.execute("UPDATE tenants SET plan_code = ? WHERE id = ?", (body.plan_code, t["id"]))
    ctx.conn.execute("UPDATE subscriptions SET plan_code = ?, discount_pct = ?, updated_at = ? WHERE id = "
                     "(SELECT id FROM subscriptions WHERE tenant_id = ? ORDER BY created_at DESC LIMIT 1)",
                     (body.plan_code, body.discount_pct, now_iso(), t["id"]))
    invalidate_subscription_cache(t["id"])
    _audit(ctx, "platform.plan_changed", "tenant", t["id"], {"from": t["plan_code"], **body.model_dump()})
    return {"ok": True}


@route("POST", "/api/v1/platform/tenants/{id}/trial-extend", auth="platform")
def trial_extend(ctx: Ctx, body: DaysIn):
    _need(ctx, "platform.billing")
    t = _tenant(ctx)
    sub = billing_svc.current_subscription(ctx.conn, t["id"])
    if sub["status"] != "trialing":
        raise conflict("Subscription is not in trial", "NOT_TRIALING")
    from ..util import parse_dt
    new_end = iso(parse_dt(sub["trial_ends_at"]) + timedelta(days=body.days))
    ctx.conn.execute("UPDATE subscriptions SET trial_ends_at = ?, updated_at = ? WHERE id = ?", (new_end, now_iso(), sub["id"]))
    _audit(ctx, "platform.trial_extended", "tenant", t["id"], body.model_dump())
    return {"trial_ends_at": new_end}


@route("POST", "/api/v1/platform/tenants/{id}/payment-pending", auth="platform")
def payment_pending(ctx: Ctx, body: DaysIn):
    _need(ctx, "platform.billing")
    t = _tenant(ctx)
    until = iso(utcnow() + timedelta(days=min(body.days, 14)))
    ctx.conn.execute("UPDATE subscriptions SET payment_pending_until = ?, updated_at = ? WHERE id = "
                     "(SELECT id FROM subscriptions WHERE tenant_id = ? ORDER BY created_at DESC LIMIT 1)",
                     (until, now_iso(), t["id"]))
    _audit(ctx, "platform.payment_pending", "tenant", t["id"], body.model_dump())
    return {"payment_pending_until": until}


@route("GET", "/api/v1/platform/plans", auth="platform")
def plans(ctx: Ctx):
    _need(ctx, "platform.read")
    rows = dbm.all_(ctx.conn, "SELECT * FROM plans ORDER BY price_cents DESC")
    for r in rows:
        r["limits"] = loads(r["limits"], {})
        r["features"] = loads(r["features"], [])
        r["tenants"] = dbm.scalar(ctx.conn, "SELECT COUNT(*) FROM tenants WHERE plan_code = ?", (r["code"],))
    return {"items": rows}


@route("PUT", "/api/v1/platform/plans/{code}", auth="platform")
def update_plan(ctx: Ctx, body: PlanPriceIn):
    if ctx.p.platform_role != "owner":
        raise forbidden("Only the platform owner can change prices")
    p = dbm.one(ctx.conn, "SELECT * FROM plans WHERE code = ?", (ctx.path["code"],))
    if not p:
        raise not_found("Plan")
    # Existing tenants keep their price until renewal (grandfathering) — the new version applies to new invoices.
    ctx.conn.execute("UPDATE plans SET price_cents = ?, min_monthly_cents = ?, limits = ?, features = ?, version = version + 1 "
                     "WHERE code = ?", (body.price_cents, body.min_monthly_cents, dumps(body.limits), dumps(body.features),
                                        p["code"]))
    _audit(ctx, "platform.plan_updated", "plan", p["code"], body.model_dump())
    return {"ok": True, "version": p["version"] + 1}


@route("GET", "/api/v1/platform/invoices", auth="platform")
def invoices(ctx: Ctx):
    _need(ctx, "platform.read")
    where, params = ["1=1"], []
    if ctx.q("status"):
        where.append("i.status = ?")
        params.append(ctx.q("status"))
    rows = dbm.all_(ctx.conn, f"SELECT i.*, t.name AS tenant_name, (SELECT COALESCE(SUM(amount_cents),0) FROM payments p "
                              f"WHERE p.invoice_id = i.id) AS paid_cents FROM invoices i JOIN tenants t ON t.id = i.tenant_id "
                              f"WHERE {' AND '.join(where)} ORDER BY i.issued_at DESC LIMIT 500", params)
    for r in rows:
        r["lines"] = loads(r["lines"], [])
    return {"items": rows}


@route("POST", "/api/v1/platform/invoices/run", auth="platform")
def run_billing(ctx: Ctx):
    _need(ctx, "platform.billing")
    res = billing_svc.run_billing(ctx.conn)
    _audit(ctx, "platform.billing_run", "billing", None, res)
    return res


@route("POST", "/api/v1/platform/invoices/{id}/payments", auth="platform")
def add_payment(ctx: Ctx, body: PaymentIn):
    _need(ctx, "platform.billing")
    inv = dbm.one(ctx.conn, "SELECT * FROM invoices WHERE id = ?", (ctx.path["id"],))
    if not inv:
        raise not_found("Invoice")
    if inv["status"] in ("paid", "void"):
        raise conflict("Invoice is already settled", "INVOICE_SETTLED")
    res = billing_svc.record_payment(ctx.conn, inv, body.amount_cents, body.method, body.reference, ctx.actor)
    _audit(ctx, "platform.payment_recorded", "invoice", inv["id"], body.model_dump())
    return res


@route("POST", "/api/v1/platform/invoices/{id}/void", auth="platform")
def void_invoice(ctx: Ctx):
    _need(ctx, "platform.billing")
    inv = dbm.one(ctx.conn, "SELECT * FROM invoices WHERE id = ?", (ctx.path["id"],))
    if not inv or inv["status"] == "paid":
        raise unprocessable("Only unpaid invoices can be voided (issue a credit note for paid ones)", "INVOICE_NOT_VOIDABLE")
    ctx.conn.execute("UPDATE invoices SET status = 'void' WHERE id = ?", (inv["id"],))
    billing_svc.reconcile_status(ctx.conn, inv["tenant_id"])
    _audit(ctx, "platform.invoice_voided", "invoice", inv["id"])
    return {"ok": True}


@route("GET", "/api/v1/platform/dunning", auth="platform")
def dunning(ctx: Ctx):
    _need(ctx, "platform.read")
    rows = []
    for t in dbm.all_(ctx.conn, "SELECT id, name FROM tenants"):
        days = billing_svc.overdue_days(ctx.conn, t["id"])
        if days < 0:
            continue
        sub = billing_svc.current_subscription(ctx.conn, t["id"])
        nxt = next(((th, st) for th, st in sorted(billing_svc.DUNNING) if th > days), None)
        rows.append({"tenant_id": t["id"], "tenant": t["name"], "overdue_days": days, "status": sub["status"],
                     "next_step": nxt[1] if nxt else None, "next_step_in_days": (nxt[0] - days) if nxt else None,
                     "payment_pending_until": sub["payment_pending_until"],
                     "amount_cents": dbm.scalar(ctx.conn, "SELECT SUM(amount_cents) FROM invoices WHERE tenant_id = ? AND "
                                                          "status IN ('issued','overdue')", (t["id"],))})
    return {"items": sorted(rows, key=lambda r: -r["overdue_days"]), "policy": billing_svc.DUNNING}


@route("GET", "/api/v1/platform/churn", auth="platform")
def churn(ctx: Ctx):
    _need(ctx, "platform.read")
    reasons = dbm.all_(ctx.conn, "SELECT reason, COUNT(*) AS n FROM cancellation_feedback GROUP BY reason ORDER BY n DESC")
    recent = dbm.all_(ctx.conn, "SELECT c.*, t.name AS tenant FROM cancellation_feedback c JOIN tenants t ON t.id = c.tenant_id "
                                "ORDER BY c.created_at DESC LIMIT 50")
    cohorts = dbm.all_(ctx.conn, "SELECT substr(t.created_at, 1, 7) AS cohort, COUNT(*) AS tenants, SUM(CASE WHEN s.status "
                                 "IN ('cancelled','archived') THEN 1 ELSE 0 END) AS churned FROM tenants t JOIN subscriptions s "
                                 "ON s.tenant_id = t.id AND s.created_at = (SELECT MAX(created_at) FROM subscriptions x WHERE "
                                 "x.tenant_id = t.id) GROUP BY cohort ORDER BY cohort")
    return {"reasons": reasons, "recent": recent, "cohorts": cohorts}


@route("GET", "/api/v1/platform/tickets", auth="platform")
def tickets(ctx: Ctx):
    _need(ctx, "platform.read")
    rows = dbm.all_(ctx.conn, "SELECT s.*, t.name AS tenant FROM support_tickets s JOIN tenants t ON t.id = s.tenant_id "
                              "ORDER BY CASE s.status WHEN 'open' THEN 0 WHEN 'in_progress' THEN 1 ELSE 2 END, s.sla_due_at")
    for r in rows:
        r["sla_breached"] = r["status"] in ("open", "in_progress") and r["sla_due_at"] < now_iso()
    return {"items": rows}


@route("PATCH", "/api/v1/platform/tickets/{id}", auth="platform")
def update_ticket(ctx: Ctx, body: TicketPatchIn):
    _need(ctx, "platform.support")
    t = dbm.one(ctx.conn, "SELECT * FROM support_tickets WHERE id = ?", (ctx.path["id"],))
    if not t:
        raise not_found("Ticket")
    changes = {k: v for k, v in body.model_dump(exclude_unset=True).items() if v is not None}
    changes["updated_at"] = now_iso()
    dbm.update(ctx.conn, "support_tickets", {"id": t["id"]}, changes)
    _audit(ctx, "platform.ticket_updated", "ticket", t["id"], changes)
    return {**t, **changes}


@route("GET", "/api/v1/platform/audit", auth="platform")
def platform_audit(ctx: Ctx):
    _need(ctx, "platform.read")
    rows = dbm.all_(ctx.conn, "SELECT a.*, p.name AS actor_name FROM audit_logs a LEFT JOIN platform_users p ON p.id = "
                              "a.actor_id WHERE a.tenant_id IS NULL ORDER BY a.seq DESC LIMIT 500")
    from ..security import audit as auditlog
    return {"items": rows, "chain": auditlog.verify_chain(ctx.conn, None)}

