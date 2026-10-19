"""Tenant provisioning, plans catalogue and plan limits."""

from __future__ import annotations

from datetime import timedelta

from .. import db as dbm
from ..errors import conflict, payment_required, unprocessable
from ..security import crypto, passwords, tokens
from ..util import dumps, iso, loads, new_id, now_iso, token, utcnow

# Hypothesis pricing from the business tab (section 4). Cents, USD, annual billing.
PLANS = [
    {"code": "starter", "name": "Starter", "price_model": "flat", "price_cents": 9900, "min_monthly_cents": 9900,
     "limits": {"employees": 150, "sites": 1, "devices": 2, "admins": 3, "retention_days": 365,
                "audit_days": 90, "offline_hours": 72},
     "features": ["timesheet", "csv_export", "portal"]},
    {"code": "business", "name": "Business", "price_model": "per_employee", "price_cents": 90,
     "min_monthly_cents": 25000,
     "limits": {"employees": 1000, "sites": 2, "devices": 10, "admins": 15, "retention_days": 1095,
                "audit_days": 365, "offline_hours": 168},
     "features": ["timesheet", "csv_export", "portal", "xlsx_pdf", "rotations", "overtime_rules", "payroll_export",
                  "telegram"]},
    {"code": "professional", "name": "Professional", "price_model": "per_employee", "price_cents": 75,
     "min_monthly_cents": 90000,
     "limits": {"employees": 5000, "sites": 10, "devices": 50, "admins": 50, "retention_days": 1825,
                "audit_days": 1095, "offline_hours": 168},
     "features": ["timesheet", "csv_export", "portal", "xlsx_pdf", "rotations", "overtime_rules", "payroll_export",
                  "telegram", "api", "webhooks", "rule_simulator", "roi_dashboard", "scheduled_reports",
                  "security_alerts"]},
    {"code": "enterprise", "name": "Enterprise", "price_model": "contract", "price_cents": 50,
     "min_monthly_cents": 208300,
     "limits": {"employees": None, "sites": None, "devices": None, "admins": None, "retention_days": None,
                "audit_days": 2555, "offline_hours": 720},
     "features": ["timesheet", "csv_export", "portal", "xlsx_pdf", "rotations", "overtime_rules", "payroll_export",
                  "telegram", "api", "webhooks", "rule_simulator", "roi_dashboard", "scheduled_reports",
                  "security_alerts", "sso", "onprem"]},
]


def seed_plans(conn) -> None:
    for p in PLANS:
        if dbm.one(conn, "SELECT 1 AS x FROM plans WHERE code = ?", (p["code"],)):
            continue
        dbm.insert(conn, "plans", {**p, "version": 1, "monthly_markup_pct": 15, "limits": dumps(p["limits"]),
                                   "features": dumps(p["features"]), "active": 1})


def plan(conn, code: str) -> dict:
    row = dbm.one(conn, "SELECT * FROM plans WHERE code = ?", (code,))
    if not row:
        raise unprocessable(f"Unknown plan {code}", "PLAN_UNKNOWN")
    row["limits"] = loads(row["limits"], {})
    row["features"] = loads(row["features"], [])
    return row


def tenant_plan(conn, tenant_id: str) -> dict:
    t = dbm.one(conn, "SELECT plan_code FROM tenants WHERE id = ?", (tenant_id,))
    return plan(conn, t["plan_code"])


def usage(conn, tenant_id: str) -> dict:
    return {
        "employees": dbm.scalar(conn, "SELECT COUNT(*) FROM employees WHERE tenant_id = ? AND status = 'active'", (tenant_id,)),
        "sites": dbm.scalar(conn, "SELECT COUNT(*) FROM sites WHERE tenant_id = ? AND status = 'active'", (tenant_id,)),
        "devices": dbm.scalar(conn, "SELECT COUNT(*) FROM devices WHERE tenant_id = ? AND status <> 'decommissioned'", (tenant_id,)),
        "admins": dbm.scalar(conn, "SELECT COUNT(DISTINCT u.id) FROM users u JOIN user_roles r ON r.user_id = u.id "
                                   "WHERE u.tenant_id = ? AND u.status <> 'blocked' AND r.role_code <> 'employee'", (tenant_id,)),
    }


def check_limit(conn, tenant_id: str, resource: str, adding: int = 1) -> None:
    limits = tenant_plan(conn, tenant_id)["limits"]
    cap = limits.get(resource)
    if cap is None:
        return
    current = usage(conn, tenant_id)[resource]
    if current + adding > cap:
        raise payment_required(f"Plan limit reached for {resource}: {current}/{cap}. Upgrade the plan to add more.",
                               "PLAN_LIMIT")


def has_feature(conn, tenant_id: str, feature: str) -> bool:
    return feature in tenant_plan(conn, tenant_id)["features"]


def create_tenant(conn, master_key: bytes, *, slug: str, name: str, plan_code: str, admin_email: str,
                  admin_name: str, admin_password: str | None = None, legal_name: str | None = None,
                  tin: str | None = None, trial_days: int = 0, deployment: str = "cloud",
                  billing_cycle: str = "annual") -> dict:
    if dbm.one(conn, "SELECT 1 AS x FROM tenants WHERE slug = ?", (slug,)):
        raise conflict("Organisation code already in use", "TENANT_SLUG_TAKEN")
    plan(conn, plan_code)
    tenant_id = new_id()
    dek = crypto.new_key()
    now = now_iso()
    dbm.insert(conn, "tenants", {"id": tenant_id, "slug": slug, "name": name, "legal_name": legal_name, "tin": tin,
                                 "status": "active", "plan_code": plan_code, "deployment": deployment,
                                 "dek_wrapped": crypto.wrap_dek(master_key, dek, tenant_id), "created_at": now})
    start = utcnow()
    end = start + timedelta(days=365 if billing_cycle == "annual" else 30)
    dbm.insert(conn, "subscriptions", {
        "id": new_id(), "tenant_id": tenant_id, "plan_code": plan_code,
        "status": "trialing" if trial_days else "active", "billing_cycle": billing_cycle, "discount_pct": 0,
        "period_start": iso(start), "period_end": iso(end),
        "trial_ends_at": iso(start + timedelta(days=trial_days)) if trial_days else None,
        "payment_pending_until": None, "cancel_at": None, "cancel_reason": None, "created_at": now, "updated_at": now})
    dbm.insert(conn, "gallery_versions", {"tenant_id": tenant_id, "version": 0, "updated_at": now})

    user_id = new_id()
    invite = None
    user = {"id": user_id, "tenant_id": tenant_id, "login": admin_email.lower(), "email": admin_email.lower(),
            "name": admin_name, "status": "active" if admin_password else "invited", "mfa_enabled": 0,
            "created_at": now}
    if admin_password:
        problems = passwords.password_problems(admin_password)
        if problems:
            raise unprocessable("Password does not meet policy", "PASSWORD_WEAK", problems=problems)
        user["password_hash"] = passwords.hash_secret(admin_password)
    else:
        invite = token(24)
        user["invite_token_hash"] = tokens.hash_token(invite)
        user["invite_expires_at"] = iso(utcnow() + timedelta(hours=48))
    dbm.insert(conn, "users", user)
    dbm.insert(conn, "user_roles", {"id": new_id(), "tenant_id": tenant_id, "user_id": user_id,
                                    "role_code": "super_admin", "scope_type": "global", "scope_id": None,
                                    "valid_until": None, "created_by": None, "created_at": now})
    return {"tenant_id": tenant_id, "admin_user_id": user_id, "invite_token": invite}
