"""ROI calculator (business tab, section 5): public calculator, PDF lead, in-app ROI dashboard.

Rules: values the user did not enter are never silently assumed. Optional
fields left empty are excluded and reported; "after" values default to
visible coefficients flagged as assumptions.
"""

from __future__ import annotations

import io
from datetime import date, timedelta

from pydantic import BaseModel, Field
from starlette.responses import Response

from .. import db as dbm
from ..errors import forbidden
from ..http import Ctx, route
from ..util import dumps, iso, loads, new_id, now_iso, utcnow

DEFAULT_COEFFICIENTS = {"H": 0.20, "K": 0.35, "L": 0.20, "E": 0.30}


class RoiIn(BaseModel):
    employees: int = Field(ge=10, le=100_000)
    payroll_monthly: float = Field(gt=0)
    hr_hour_cost: float = Field(gt=0, le=100)
    hr_hours_now: float = Field(ge=0)
    fix_hours_now: float = Field(ge=0)
    leakage_pct_now: float | None = Field(default=None, ge=0, le=10)
    other_costs_now: float = Field(default=0, ge=0)
    hr_hours_after: float | None = Field(default=None, ge=0)
    fix_hours_after: float | None = Field(default=None, ge=0)
    leakage_pct_after: float | None = Field(default=None, ge=0, le=10)
    other_costs_after: float | None = Field(default=None, ge=0)
    subscription_monthly: float = Field(ge=0)
    devices_cost: float = Field(ge=0)
    install_cost: float = Field(ge=0)
    integration_cost: float = Field(default=0, ge=0)
    maintenance_monthly: float = Field(default=0, ge=0)


class LeadIn(BaseModel):
    email: str = Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    company: str | None = Field(default=None, max_length=200)
    inputs: RoiIn


def calculate(i: RoiIn) -> dict:
    assumptions, excluded = [], []

    def after(value, now, key, label):
        if value is not None:
            return value
        assumptions.append({"field": label, "coefficient": DEFAULT_COEFFICIENTS[key],
                            "text": f"{label}: hozirgi qiymatning {int(DEFAULT_COEFFICIENTS[key] * 100)}% (taxmin)"})
        return now * DEFAULT_COEFFICIENTS[key]

    h1 = after(i.hr_hours_after, i.hr_hours_now, "H", "HR tabel vaqti (keyin)")
    k1 = after(i.fix_hours_after, i.fix_hours_now, "K", "Tuzatish vaqti (keyin)")
    e1 = after(i.other_costs_after, i.other_costs_now, "E", "Boshqa xato xarajatlari (keyin)")
    if i.leakage_pct_now is None:
        excluded.append("Ortiqcha to'lov ulushi (L0) kiritilmagan — natijaga kirmadi. Pilotda o'lchash tavsiya etiladi.")
        l0 = l1 = 0.0
    else:
        l0 = i.leakage_pct_now / 100
        l1 = (after(i.leakage_pct_after, i.leakage_pct_now, "L", "Ortiqcha to'lov ulushi (keyin)") / 100) \
            if i.leakage_pct_after is None else i.leakage_pct_after / 100
    c_now = i.hr_hour_cost * (i.hr_hours_now + i.fix_hours_now) + i.payroll_monthly * l0 + i.other_costs_now
    c_after = i.hr_hour_cost * (h1 + k1) + i.payroll_monthly * l1 + e1 + i.subscription_monthly + i.maintenance_monthly
    monthly = c_now - c_after
    one_time = i.devices_cost + i.install_cost + i.integration_cost
    payback = round(one_time / monthly, 1) if monthly > 0 else None
    sensitivity = []
    for pct in (0, 0.25, 0.5, 1.0):
        lp_now = i.payroll_monthly * pct / 100
        lp_after = lp_now * DEFAULT_COEFFICIENTS["L"]
        m = (i.hr_hour_cost * (i.hr_hours_now + i.fix_hours_now) + lp_now + i.other_costs_now) - \
            (i.hr_hour_cost * (h1 + k1) + lp_after + e1 + i.subscription_monthly + i.maintenance_monthly)
        sensitivity.append({"leakage_pct": pct, "monthly_saving": round(m, 2),
                            "payback_months": round(one_time / m, 1) if m > 0 else None})
    return {"cost_now_monthly": round(c_now, 2), "cost_after_monthly": round(c_after, 2),
            "net_saving_monthly": round(monthly, 2), "net_saving_yearly": round(monthly * 12, 2),
            "one_time_investment": round(one_time, 2), "payback_months": payback,
            "first_year_result": round(monthly * 12 - one_time, 2), "assumptions": assumptions, "excluded": excluded,
            "sensitivity": sensitivity,
            "verdict": "pays_back" if payback is not None and payback <= 24 else "weak" if payback else "does_not_pay_back"}


@route("POST", "/api/v1/public/roi/calculate", auth="public", rate="public")
def public_calc(ctx: Ctx, body: RoiIn):
    return calculate(body)


@route("POST", "/api/v1/public/roi/report", auth="public", rate="public")
def public_report(ctx: Ctx, body: LeadIn):
    result = calculate(body.inputs)
    dbm.insert(ctx.conn, "leads", {"id": new_id(), "email": body.email.lower(), "company": body.company,
                                   "inputs": dumps(body.inputs.model_dump()), "result": dumps(result),
                                   "created_at": now_iso()})
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, title="FRAS ROI")
    st = getSampleStyleSheet()
    i = body.inputs.model_dump()
    story = [Paragraph(f"FRAS ROI hisob-kitobi{(' — ' + body.company) if body.company else ''}", st["Heading2"]),
             Paragraph("Kiritilgan qiymatlar", st["Heading4"]),
             Table([[k, "" if v is None else str(v)] for k, v in i.items()]), Spacer(1, 10),
             Paragraph("Natija", st["Heading4"]),
             Table([[k, str(v)] for k, v in result.items() if not isinstance(v, (list, dict))]), Spacer(1, 10),
             Paragraph("Taxminlar (kiritilmagan qiymatlar o'rniga)", st["Heading4"])]
    story += [Paragraph(a["text"], st["BodyText"]) for a in result["assumptions"]] or [Paragraph("Yo'q", st["BodyText"])]
    story += [Paragraph(x, st["BodyText"]) for x in result["excluded"]]
    story.append(Paragraph("Bu hisob-kitob va'da emas. Haqiqiy qiymat pilotda bazaviy o'lchov bilan aniqlanadi.",
                           st["Italic"]))
    doc.build(story)
    return Response(buf.getvalue(), media_type="application/pdf",
                    headers={"Content-Disposition": "attachment; filename=fras-roi.pdf"})


class BaselineIn(BaseModel):
    inputs: RoiIn


@route("GET", "/api/v1/roi/dashboard", perm="report.view")
def dashboard(ctx: Ctx):
    base = dbm.one(ctx.conn, "SELECT * FROM roi_baselines WHERE tenant_id = ?", (ctx.tenant_id,))
    since = iso(utcnow() - timedelta(days=30))
    measured = {
        "corrections_30d": dbm.scalar(ctx.conn, "SELECT COUNT(*) FROM corrections WHERE tenant_id = ? AND created_at >= ?",
                                      (ctx.tenant_id, since)),
        "disputes_30d": dbm.scalar(ctx.conn, "SELECT COUNT(*) FROM corrections WHERE tenant_id = ? AND source = "
                                             "'employee_dispute' AND created_at >= ?", (ctx.tenant_id, since)),
        "blocked_attempts_30d": dbm.scalar(ctx.conn, "SELECT COUNT(*) FROM attendance_events WHERE tenant_id = ? AND "
                                                     "result IN ('pad','unknown','denied') AND captured_at >= ?",
                                           (ctx.tenant_id, since)),
        "events_30d": dbm.scalar(ctx.conn, "SELECT COUNT(*) FROM attendance_events WHERE tenant_id = ? AND captured_at >= ?",
                                 (ctx.tenant_id, since)),
        "overtime_hours_30d": round((dbm.scalar(ctx.conn, "SELECT COALESCE(SUM(overtime_min),0) FROM daily_summaries WHERE "
                                                          "tenant_id = ? AND work_date >= ?",
                                                (ctx.tenant_id, (date.today() - timedelta(days=30)).isoformat())) or 0) / 60, 1),
        "late_minutes_30d": dbm.scalar(ctx.conn, "SELECT COALESCE(SUM(late_min),0) FROM daily_summaries WHERE tenant_id = ? "
                                                 "AND work_date >= ?", (ctx.tenant_id, (date.today() - timedelta(days=30)).isoformat())),
    }
    return {"baseline": loads(base["inputs"]) if base else None,
            "estimate": calculate(RoiIn(**loads(base["inputs"]))) if base else None, "measured": measured,
            "note": "O'lchangan qiymatlar tizimdan olinadi; baza va 'keyin' qiymatlari foydalanuvchi kiritgan yoki taxmin."}


@route("PUT", "/api/v1/roi/baseline", perm="settings.read")
def set_baseline(ctx: Ctx, body: BaselineIn):
    if not (ctx.can("report.export") or ctx.can("billing.read")):
        raise forbidden("Report export or billing access required")
    data = dumps(body.inputs.model_dump())
    ctx.conn.execute("INSERT INTO roi_baselines (tenant_id, inputs, updated_by, updated_at) VALUES (?,?,?,?) ON CONFLICT"
                     "(tenant_id) DO UPDATE SET inputs = excluded.inputs, updated_by = excluded.updated_by, updated_at = "
                     "excluded.updated_at", (ctx.tenant_id, data, ctx.actor, now_iso()))
    ctx.audit("roi.baseline_set", "roi", ctx.tenant_id, after=body.inputs.model_dump())
    return {"ok": True}
