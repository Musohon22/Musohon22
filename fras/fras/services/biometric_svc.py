"""Biometric profile lifecycle: enrolment, duplicate search, revoke, gallery packages.

Enrolment frames are processed in memory and discarded (policy "0 days").
Templates are encrypted with a key derived from the tenant DEK under the label
"biometric", separate from the key used for ordinary personal data.
"""

from __future__ import annotations

import base64
import json

import numpy as np

from .. import db as dbm
from ..biometrics import imaging
from ..biometrics.providers import Provider
from ..errors import unprocessable
from ..security import crypto
from ..util import new_id, now_iso
from . import gallery, settings_svc


def template_key(dek: bytes) -> bytes:
    return crypto.derive(dek, "biometric-template")


def seal_template(dek: bytes, vec: np.ndarray, profile_id: str) -> bytes:
    return crypto.seal(template_key(dek), vec.astype(np.float32).tobytes(), aad=profile_id.encode())


def open_template(dek: bytes, blob: bytes, profile_id: str) -> np.ndarray:
    return np.frombuffer(crypto.open_sealed(template_key(dek), blob, aad=profile_id.encode()), dtype=np.float32)


def active_templates(conn, dek: bytes, tenant_id: str, exclude_employee: str | None = None) -> list[tuple[dict, np.ndarray]]:
    rows = dbm.all_(conn, "SELECT p.id, p.employee_id, p.template_enc FROM biometric_profiles p JOIN employees e "
                          "ON e.id = p.employee_id WHERE p.tenant_id = ? AND p.status IN ('active','review') "
                          "AND p.template_enc IS NOT NULL", (tenant_id,))
    out = []
    for r in rows:
        if r["employee_id"] == exclude_employee:
            continue
        out.append((r, open_template(dek, r["template_enc"], r["id"])))
    return out


def analyse_frame(provider: Provider, frame) -> dict:
    """Detection + quality report for one frame (used for real-time guidance)."""
    img = imaging.decode(frame)
    faces = provider.detect(img)
    if not faces:
        return {"faces": 0, "ok": False, "issues": ["no_face"], "score": 0.0}
    if len(faces) > 1:
        return {"faces": len(faces), "ok": False, "issues": ["multiple_faces"], "score": 0.0}
    q = imaging.assess(img, faces[0].bbox, faces[0].landmarks)
    return {"faces": 1, "ok": not q.issues, "issues": q.issues, "score": round(q.score, 3),
            "brightness": round(q.brightness, 1), "sharpness": round(q.sharpness, 1),
            "eye_distance_px": round(q.eye_distance_px, 1), "yaw": round(q.yaw_deg, 1), "pitch": round(q.pitch_deg, 1),
            "bbox": [round(v, 1) for v in faces[0].bbox], "frame_size": [img.shape[1], img.shape[0]]}


def build_template(provider: Provider, frames: list, policy: dict) -> dict:
    if len(frames) < policy.get("min_frames", 3):
        raise unprocessable(f"At least {policy.get('min_frames', 3)} frames are required", "ENR-E10")
    imgs, faces, vecs, scores = [], [], [], []
    for i, fr in enumerate(frames):
        try:
            img = imaging.decode(fr)
        except Exception:  # noqa: BLE001 - bad image data
            raise unprocessable(f"Frame {i + 1} is not a valid image", "ENR-E10", frame=i + 1)
        found = provider.detect(img)
        if len(found) != 1:
            raise unprocessable(f"Frame {i + 1}: exactly one face must be visible", "ENR-E10", frame=i + 1,
                                faces=len(found))
        q = imaging.assess(img, found[0].bbox, found[0].landmarks)
        if q.score < policy.get("min_quality", 0.55):
            raise unprocessable(f"Frame {i + 1}: quality too low", "ENR-E10", frame=i + 1, issues=q.issues,
                                score=round(q.score, 3))
        imgs.append(img)
        faces.append(found[0])
        vecs.append(provider.embed(img, found[0]))
        scores.append(q.score)
    live_score, live_method = provider.liveness(imgs, faces)
    if policy.get("liveness_required", True) and live_score < policy.get("liveness_min", 0.6):
        raise unprocessable("Liveness check failed", "ENR-E20", liveness=live_score, method=live_method)
    mean = np.mean(np.stack(vecs), axis=0)
    template = mean / (np.linalg.norm(mean) + 1e-9)
    consistency = float(np.min([float(v @ template) for v in vecs]))
    return {"template": template.astype(np.float32), "quality": float(np.mean(scores)), "liveness": live_score,
            "liveness_method": live_method, "frames": len(frames), "consistency": consistency}


def enroll(conn, *, tenant_id: str, dek: bytes, employee: dict, built: dict, provider: Provider, actor: str) -> dict:
    policy = settings_svc.get(conn, tenant_id, "biometric_policy")
    tmpl = built["template"]
    # 1:N duplicate search across the whole tenant
    best = None
    for row, vec in active_templates(conn, dek, tenant_id, exclude_employee=employee["id"]):
        s = float(vec @ tmpl)
        if best is None or s > best[1]:
            best = (row, s)
    # retire previous profile of this employee (re-enrolment)
    for old in dbm.all_(conn, "SELECT id FROM biometric_profiles WHERE employee_id = ? AND status IN ('active','review')",
                        (employee["id"],)):
        conn.execute("UPDATE biometric_profiles SET status = 'revoked', template_enc = NULL, revoked_at = ?, "
                     "revoke_reason = 're-enrolled' WHERE id = ?", (now_iso(), old["id"]))
    profile_id = new_id()
    dup = best is not None and best[1] >= policy["duplicate_threshold"]
    version = gallery.bump(conn, tenant_id)
    dbm.insert(conn, "biometric_profiles", {
        "id": profile_id, "tenant_id": tenant_id, "employee_id": employee["id"],
        "status": "review" if dup else "active", "template_enc": seal_template(dek, tmpl, profile_id),
        "template_nonce": None, "model_version": provider.model_version, "quality_score": round(built["quality"], 4),
        "liveness_score": built["liveness"], "frames": built["frames"], "gallery_version": version,
        "created_by": actor, "created_at": now_iso(), "revoked_at": None, "revoke_reason": None})
    conn.execute("UPDATE employees SET biometric_status = ?, updated_at = ? WHERE id = ?",
                 ("review" if dup else "active", now_iso(), employee["id"]))
    result = {"profile_id": profile_id, "status": "review" if dup else "active", "gallery_version": version,
              "quality": round(built["quality"], 3), "liveness": built["liveness"], "model_version": provider.model_version}
    if dup:
        dbm.insert(conn, "biometric_reviews", {"id": new_id(), "tenant_id": tenant_id, "profile_id": profile_id,
                                               "matched_profile_id": best[0]["id"], "score": round(best[1], 4),
                                               "status": "open", "comment": None, "decided_by": None, "decided_at": None,
                                               "created_at": now_iso()})
        from .alerts import raise_alert
        raise_alert(conn, tenant_id, "duplicate_face", "medium", {"profile_id": profile_id, "employee_id": employee["id"]},
                    site_id=employee["site_id"])
    return result


def revoke(conn, tenant_id: str, employee_id: str, reason: str) -> int:
    n = 0
    for p in dbm.all_(conn, "SELECT id FROM biometric_profiles WHERE tenant_id = ? AND employee_id = ? AND status <> 'revoked'",
                      (tenant_id, employee_id)):
        # crypto-erase: the ciphertext is removed; without it the template cannot be recovered
        conn.execute("UPDATE biometric_profiles SET status = 'revoked', template_enc = NULL, revoked_at = ?, "
                     "revoke_reason = ? WHERE id = ?", (now_iso(), reason, p["id"]))
        n += 1
    conn.execute("UPDATE employees SET biometric_status = ? WHERE id = ?",
                 ("declined" if reason == "consent_withdrawn" else "revoked", employee_id))
    gallery.bump(conn, tenant_id)
    return n


def display_name(emp: dict) -> str:
    return f"{emp['first_name']} {emp['last_name'][:1]}."


def gallery_payload(conn, dek: bytes, device: dict) -> dict:
    """What a terminal needs to decide on its own while offline: templates of employees allowed at
    its access point, display names (first name + initial only), card numbers and PIN hashes."""
    tenant_id = device["tenant_id"]
    if device.get("access_point_id"):
        emps = dbm.all_(conn, "SELECT e.* FROM employees e JOIN employee_access_points eap ON eap.employee_id = e.id "
                              "WHERE eap.access_point_id = ? AND e.status = 'active'", (device["access_point_id"],))
    else:
        emps = dbm.all_(conn, "SELECT * FROM employees WHERE tenant_id = ? AND site_id = ? AND status = 'active'",
                        (tenant_id, device["site_id"]))
    profiles = {r["employee_id"]: r for r in dbm.all_(
        conn, "SELECT id, employee_id, template_enc FROM biometric_profiles WHERE tenant_id = ? AND status = 'active' "
              "AND template_enc IS NOT NULL", (tenant_id,))}
    blocked = [r["id"] for r in dbm.all_(conn, "SELECT id FROM employees WHERE tenant_id = ? AND status <> 'active'",
                                         (tenant_id,))]
    people = []
    for e in emps:
        p = profiles.get(e["id"])
        tmpl = None
        if p:
            tmpl = base64.b64encode(open_template(dek, p["template_enc"], p["id"]).astype(np.float16).tobytes()).decode()
        people.append({"employee_id": e["id"], "name": display_name(e), "language": e["language"], "template": tmpl,
                       "card_no": e["card_no"], "pin_hash": e["pin_hash"]})
    policy = settings_svc.get(conn, tenant_id, "biometric_policy")
    rules = settings_svc.get(conn, tenant_id, "attendance_rules")
    return {"version": gallery.current(conn, tenant_id), "people": people, "blocked": blocked,
            "thresholds": settings_svc.thresholds(policy), "liveness_required": policy["liveness_required"],
            "liveness_min": policy["liveness_min"], "debounce_min": rules["debounce_min"],
            "border_action": policy["border_action"]}


def sealed_gallery(conn, dek: bytes, device: dict) -> dict:
    payload = gallery_payload(conn, dek, device)
    if not device.get("enc_public_key"):
        raise unprocessable("Device has no encryption key; re-activate it", "DEVICE_NO_ENC_KEY")
    package = crypto.seal_for_device(device["enc_public_key"], json.dumps(payload).encode())
    return {"version": payload["version"], "package": package, "people": len(payload["people"])}
