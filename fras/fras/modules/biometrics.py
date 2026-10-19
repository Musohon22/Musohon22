"""Consent, enrolment, quality guidance, revoke, duplicate-face review (SCR-20 … SCR-23)."""

from __future__ import annotations

import base64

from pydantic import BaseModel, Field

from .. import db as dbm
from ..biometrics.providers import get_provider
from ..errors import conflict, not_found, unprocessable
from ..http import Ctx, route
from ..security import crypto
from ..services import biometric_svc, gallery, notify, settings_svc
from ..util import new_id, now_iso
from .employees import get_employee


class ConsentIn(BaseModel):
    employee_id: str
    decision: str = Field(pattern="^(granted|declined)$")
    method: str = Field(pattern="^(paper_scan|e_signature)$")
    document: str | None = Field(default=None, max_length=7_000_000)   # base64 or data URL (PDF/JPG ≤ 5 MB)
    explained: bool = False
    alt_card_no: str | None = Field(default=None, max_length=32)
    alt_pin: str | None = None


class FrameIn(BaseModel):
    frame: str = Field(max_length=6_000_000)


class EnrollIn(BaseModel):
    employee_id: str
    frames: list[str] = Field(min_length=1, max_length=6)


class RevokeIn(BaseModel):
    reason: str = Field(pattern="^(consent_withdrawn|wrong_profile|security|other)$")
    confirm: str


class ReviewDecisionIn(BaseModel):
    decision: str = Field(pattern="^(same_person|different)$")
    comment: str = Field(min_length=5, max_length=500)


def latest_consent(conn, employee_id: str) -> dict | None:
    return dbm.one(conn, "SELECT * FROM biometric_consents WHERE employee_id = ? ORDER BY created_at DESC LIMIT 1",
                   (employee_id,))


@route("GET", "/api/v1/biometrics/policy-text", perm="biometric.enroll")
def policy_text(ctx: Ctx):
    policy = settings_svc.get(ctx.conn, ctx.tenant_id, "biometric_policy")
    retention = settings_svc.get(ctx.conn, ctx.tenant_id, "retention")
    tenant = dbm.one(ctx.conn, "SELECT name FROM tenants WHERE id = ?", (ctx.tenant_id,))
    text = {
        "uz": (f"{tenant['name']} davomatni qayd etish uchun yuzingizning matematik shablonidan foydalanadi. "
               "Suratingiz saqlanmaydi: shablon yaratilgandan so'ng darhol o'chiriladi. Shablon shifrlangan holda "
               "saqlanadi va faqat kirish nuqtalarida sizni tanish uchun ishlatiladi. Rozilik ixtiyoriy: rad etsangiz, "
               "karta va PIN-kod orqali o'tasiz. Rozilikni istalgan vaqtda xodim portalida qaytarib olishingiz mumkin. "
               f"Ishdan bo'shaganingizdan so'ng shablon {retention['template_after_termination_days']} kun ichida "
               "o'chiriladi."),
        "ru": (f"{tenant['name']} использует математический шаблон вашего лица для учёта посещаемости. Фото не "
               "хранится: оно удаляется сразу после создания шаблона. Шаблон хранится в зашифрованном виде и "
               "используется только для распознавания на проходных. Согласие добровольное: при отказе вы проходите по "
               "карте и PIN-коду. Согласие можно отозвать в любой момент в портале сотрудника. После увольнения "
               f"шаблон удаляется в течение {retention['template_after_termination_days']} дней."),
    }
    return {"version": policy["consent_policy_version"], "text": text}


@route("POST", "/api/v1/biometrics/consents", perm="biometric.enroll")
def record_consent(ctx: Ctx, body: ConsentIn):
    emp = get_employee(ctx, body.employee_id, "biometric.enroll")
    if emp["status"] != "active":
        raise conflict("Employee is not active", "EMPLOYEE_INACTIVE")
    if not body.explained:
        raise unprocessable("Confirm that the policy was explained to the employee", "CONSENT_NOT_EXPLAINED",
                            field="explained")
    doc_hash = None
    if body.document:
        raw = body.document.split(",", 1)[1] if body.document.startswith("data:") else body.document
        data = base64.b64decode(raw)
        if len(data) > 5 * 1024 * 1024:
            raise unprocessable("Document is larger than 5 MB", "FILE_TOO_LARGE")
        if not (data[:4] == b"%PDF" or data[:3] == b"\xff\xd8\xff" or data[:8] == b"\x89PNG\r\n\x1a\n"):
            raise unprocessable("Document must be PDF, JPG or PNG", "FILE_TYPE")
        doc_hash = crypto.sha256_hex(data)
    elif body.method == "paper_scan":
        raise unprocessable("Upload the signed consent form", "DOCUMENT_REQUIRED", field="document")
    policy = settings_svc.get(ctx.conn, ctx.tenant_id, "biometric_policy")
    row = {"id": new_id(), "tenant_id": ctx.tenant_id, "employee_id": emp["id"], "decision": body.decision,
           "policy_version": policy["consent_policy_version"], "method": body.method, "document_hash": doc_hash,
           "recorded_by": ctx.actor, "created_at": now_iso()}
    dbm.insert(ctx.conn, "biometric_consents", row)
    if body.decision == "declined":
        if not (body.alt_card_no or body.alt_pin or emp["card_no"]):
            raise unprocessable("An alternative method (card or PIN) is required when consent is declined",
                                "ALT_METHOD_REQUIRED")
        from .employees import _secrets
        data: dict = {}
        _secrets(ctx, data, None, body.alt_pin, body.alt_card_no, emp["id"])
        data["biometric_status"] = "declined"
        data["updated_at"] = now_iso()
        dbm.update(ctx.conn, "employees", {"id": emp["id"]}, data)
        biometric_svc.revoke(ctx.conn, ctx.tenant_id, emp["id"], "consent_withdrawn")
        ctx.audit("consent.declined", "employee", emp["id"], after={"method": body.method})
    else:
        ctx.audit("consent.recorded", "employee", emp["id"], after={"method": body.method, "document_hash": doc_hash,
                                                                    "policy_version": row["policy_version"]})
    return 201, row


@route("POST", "/api/v1/biometrics/quality", perm="biometric.enroll", rate="read")
def quality(ctx: Ctx, body: FrameIn):
    provider = get_provider(ctx.settings)
    try:
        report = biometric_svc.analyse_frame(provider, body.frame)
    except ValueError as e:
        raise unprocessable(str(e), "IMAGE_INVALID")
    report["provider"] = {"model_version": provider.model_version, "dev": provider.is_dev}
    return report


@route("POST", "/api/v1/biometrics/enrollments", perm="biometric.enroll", billing="write")
def enroll(ctx: Ctx, body: EnrollIn):
    emp = get_employee(ctx, body.employee_id, "biometric.enroll")
    if emp["status"] != "active":
        raise conflict("Employee is not active", "EMPLOYEE_INACTIVE")
    consent = latest_consent(ctx.conn, emp["id"])
    if not consent or consent["decision"] != "granted":
        raise unprocessable("Consent must be recorded before enrolment", "CONSENT_REQUIRED")
    provider = get_provider(ctx.settings)
    policy = settings_svc.get(ctx.conn, ctx.tenant_id, "biometric_policy")
    try:
        built = biometric_svc.build_template(provider, body.frames, policy)
    except Exception as e:
        if getattr(e, "code", "") == "ENR-E20":
            from ..services.alerts import raise_alert
            ctx.keep_on_error = True
            raise_alert(ctx.conn, ctx.tenant_id, "pad_attempt", "medium",
                        {"context": "enrollment", "employee_id": emp["id"], "operator": ctx.actor},
                        site_id=emp["site_id"])
            ctx.audit("biometric.enrollment_failed", "employee", emp["id"], after={"reason": "liveness"},
                      result="failure")
        raise
    result = biometric_svc.enroll(ctx.conn, tenant_id=ctx.tenant_id, dek=ctx.dek(), employee=emp, built=built,
                                  provider=provider, actor=ctx.actor)
    ctx.audit("biometric.enrolled", "employee", emp["id"],
              after={"profile_id": result["profile_id"], "status": result["status"], "quality": result["quality"],
                     "liveness": result["liveness"], "model_version": result["model_version"]})
    if result["status"] == "review":
        # the operator must not learn who the other person is
        return 201, {"status": "review", "profile_id": result["profile_id"],
                     "message": "Xavfsizlik tekshiruvi talab qilinadi", "provider_dev": provider.is_dev}
    return 201, {**result, "message": "Profil faol. Terminallarga 5 daqiqa ichida yetkaziladi",
                 "provider_dev": provider.is_dev}


@route("POST", "/api/v1/biometrics/profiles/{employee_id}/revoke", perm="biometric.revoke")
def revoke(ctx: Ctx, body: RevokeIn):
    emp = get_employee(ctx, ctx.path["employee_id"], "biometric.revoke")
    if body.confirm.strip().upper() not in ("O'CHIRISH", "OʻCHIRISH", "DELETE", "УДАЛИТЬ"):
        raise unprocessable("Type O'CHIRISH to confirm", "CONFIRMATION_REQUIRED", field="confirm")
    n = biometric_svc.revoke(ctx.conn, ctx.tenant_id, emp["id"], body.reason)
    if not n:
        raise conflict("No active biometric profile", "NO_PROFILE")
    if body.reason == "consent_withdrawn":
        dbm.insert(ctx.conn, "biometric_consents", {"id": new_id(), "tenant_id": ctx.tenant_id, "employee_id": emp["id"],
                                                    "decision": "withdrawn", "policy_version": "-", "method": "e_signature",
                                                    "document_hash": None, "recorded_by": ctx.actor,
                                                    "created_at": now_iso()})
    ctx.audit("biometric.revoked", "employee", emp["id"], after={"reason": body.reason})
    needs_alt = not (emp["card_no"] or emp["pin_hash"])
    return {"ok": True, "needs_alternative_method": needs_alt}


@route("GET", "/api/v1/biometrics/reviews", perm="biometric.review")
def reviews(ctx: Ctx):
    rows = dbm.all_(ctx.conn, "SELECT r.*, pa.employee_id AS employee_a, pb.employee_id AS employee_b, "
                              "ea.personnel_no AS a_no, ea.last_name AS a_last, ea.first_name AS a_first, "
                              "eb.personnel_no AS b_no, eb.last_name AS b_last, eb.first_name AS b_first "
                              "FROM biometric_reviews r JOIN biometric_profiles pa ON pa.id = r.profile_id "
                              "JOIN biometric_profiles pb ON pb.id = r.matched_profile_id "
                              "JOIN employees ea ON ea.id = pa.employee_id JOIN employees eb ON eb.id = pb.employee_id "
                              "WHERE r.tenant_id = ? AND r.status = ? ORDER BY r.created_at",
                    (ctx.tenant_id, ctx.q("status", "open")))
    return {"items": rows}


@route("POST", "/api/v1/biometrics/reviews/{id}/decide", perm="biometric.review")
def decide(ctx: Ctx, body: ReviewDecisionIn):
    r = dbm.one(ctx.conn, "SELECT * FROM biometric_reviews WHERE id = ? AND tenant_id = ?", (ctx.path["id"], ctx.tenant_id))
    if not r:
        raise not_found("Review")
    if r["status"] != "open":
        raise conflict("Already decided", "ALREADY_DECIDED")
    profile = dbm.one(ctx.conn, "SELECT * FROM biometric_profiles WHERE id = ?", (r["profile_id"],))
    other = dbm.one(ctx.conn, "SELECT * FROM biometric_profiles WHERE id = ?", (r["matched_profile_id"],))
    dbm.update(ctx.conn, "biometric_reviews", {"id": r["id"]}, {"status": body.decision, "comment": body.comment,
                                                               "decided_by": ctx.actor, "decided_at": now_iso()})
    if body.decision == "different":
        ctx.conn.execute("UPDATE biometric_profiles SET status = 'active' WHERE id = ?", (profile["id"],))
        ctx.conn.execute("UPDATE employees SET biometric_status = 'active' WHERE id = ?", (profile["employee_id"],))
    else:
        for p in (profile, other):
            biometric_svc.revoke(ctx.conn, ctx.tenant_id, p["employee_id"], "security")
        a, b = sorted([profile["employee_id"], other["employee_id"]])
        if not dbm.one(ctx.conn, "SELECT 1 AS x FROM duplicate_candidates WHERE tenant_id = ? AND employee_a = ? AND "
                                 "employee_b = ? AND reason = 'face'", (ctx.tenant_id, a, b)):
            dbm.insert(ctx.conn, "duplicate_candidates", {"id": new_id(), "tenant_id": ctx.tenant_id, "employee_a": a,
                                                          "employee_b": b, "reason": "face", "score": r["score"],
                                                          "status": "open", "decided_by": None, "decided_at": None,
                                                          "created_at": now_iso()})
        notify.notify_permission(ctx.conn, ctx.tenant_id, "employee.merge", "duplicate_person",
                                 "Bir odam ikki marta ro'yxatda", "Xodimlarni birlashtirish talab qilinadi",
                                 "/app/employees/duplicates")
    gallery.bump(ctx.conn, ctx.tenant_id)
    ctx.audit("biometric.review_decided", "biometric_review", r["id"], after={"decision": body.decision,
                                                                              "comment": body.comment})
    return {"ok": True}


@route("GET", "/api/v1/biometrics/provider", perm="biometric.read")
def provider_info(ctx: Ctx):
    p = get_provider(ctx.settings)
    return {"model_version": p.model_version, "dev": p.is_dev,
            "warning": "DEV provider: not a real face recognizer, for testing only" if p.is_dev else None}
