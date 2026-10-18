"""Sessions, two-factor sign-in (TOTP), password reset and personal API keys."""

import base64
import hashlib
import hmac
import json
import os
import secrets
import struct
import uuid
from datetime import timedelta
from urllib.parse import quote

from . import mailer, security, timeutil
from .errors import ApiError, not_found
from .plans import stamp

SESSION_TOUCH_SECONDS = 300
RESET_TTL = timedelta(hours=1)
RECOVERY_CODES = 8
API_KEY_PREFIX = "rk_"


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


# ---- sessions --------------------------------------------------------------------------------

def start_session(conn, user, request) -> str:
    sid = str(uuid.uuid4())
    now = stamp()
    ua = (request.headers.get("user-agent") or "")[:200]
    ip = request.client.host if request.client else ""
    conn.execute(
        "INSERT INTO sessions(id, user_id, user_agent, ip, created_at, last_seen_at) VALUES (?,?,?,?,?,?)",
        (sid, user["id"], ua, ip, now, now),
    )
    return security.create_token(user["id"], user["token_version"], sid)


def check_session(conn, sid: str, user_id: str) -> None:
    row = conn.execute("SELECT user_id, revoked_at, last_seen_at FROM sessions WHERE id = ?", (sid,)).fetchone()
    if row is None or row["revoked_at"] or row["user_id"] != user_id:
        raise ApiError(401, "session_revoked")
    if (timeutil.now() - timeutil.parse_iso(row["last_seen_at"])).total_seconds() > SESSION_TOUCH_SECONDS:
        conn.execute("UPDATE sessions SET last_seen_at = ? WHERE id = ?", (stamp(), sid))


def list_sessions(conn, user_id: str, current: str | None) -> list[dict]:
    return [
        {**dict(r), "current": r["id"] == current}
        for r in conn.execute(
            "SELECT id, user_agent, ip, created_at, last_seen_at FROM sessions WHERE user_id = ? AND revoked_at IS NULL ORDER BY last_seen_at DESC",
            (user_id,),
        )
    ]


def revoke_session(conn, user_id: str, sid: str) -> None:
    if not conn.execute("UPDATE sessions SET revoked_at = ? WHERE id = ? AND user_id = ? AND revoked_at IS NULL", (stamp(), sid, user_id)).rowcount:
        raise not_found("session")


def revoke_other_sessions(conn, user_id: str, keep: str | None) -> int:
    return conn.execute(
        "UPDATE sessions SET revoked_at = ? WHERE user_id = ? AND revoked_at IS NULL AND id IS NOT ?",
        (stamp(), user_id, keep),
    ).rowcount


# ---- TOTP (RFC 6238) ---------------------------------------------------------------------------

def _totp(secret_b32: str, counter: int) -> str:
    key = base64.b32decode(secret_b32 + "=" * (-len(secret_b32) % 8))
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    code = (struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF) % 1_000_000
    return f"{code:06d}"


def totp_now(secret: str, at=None) -> str:
    t = (at or timeutil.now()).timestamp()
    return _totp(secret, int(t // 30))


def totp_valid(secret: str, code: str) -> bool:
    code = code.replace(" ", "")
    counter = int(timeutil.now().timestamp() // 30)
    # accept the previous and next 30-second window for clock drift
    return any(hmac.compare_digest(_totp(secret, counter + d), code) for d in (-1, 0, 1))


def totp_setup(conn, user) -> dict:
    if user["totp_enabled"]:
        raise ApiError(409, "totp_already_enabled")
    secret = base64.b32encode(os.urandom(20)).decode().rstrip("=")
    conn.execute("UPDATE users SET totp_secret = ? WHERE id = ?", (secret, user["id"]))
    uri = f"otpauth://totp/Reja:{quote(user['email'])}?secret={secret}&issuer=Reja&digits=6&period=30"
    return {"secret": secret, "uri": uri}


def totp_enable(conn, user, code: str) -> dict:
    if user["totp_enabled"]:
        raise ApiError(409, "totp_already_enabled")
    if not user["totp_secret"] or not totp_valid(user["totp_secret"], code):
        raise ApiError(400, "totp_invalid")
    codes = [secrets.token_hex(4) + "-" + secrets.token_hex(4) for _ in range(RECOVERY_CODES)]
    conn.execute(
        "UPDATE users SET totp_enabled = 1, recovery_codes = ? WHERE id = ?",
        (json.dumps([_sha(c) for c in codes]), user["id"]),
    )
    return {"recovery_codes": codes}


def totp_disable(conn, user, password: str, code: str) -> None:
    if not security.verify_password(password, user["password_hash"]):
        raise ApiError(403, "bad_password")
    if not second_factor_ok(conn, user, code):
        raise ApiError(400, "totp_invalid")
    conn.execute("UPDATE users SET totp_enabled = 0, totp_secret = NULL, recovery_codes = '[]' WHERE id = ?", (user["id"],))


def second_factor_ok(conn, user, code: str | None) -> bool:
    """A current TOTP code, or a one-time recovery code (which is then used up)."""
    if not code:
        return False
    if user["totp_secret"] and totp_valid(user["totp_secret"], code):
        return True
    hashes = json.loads(user["recovery_codes"] or "[]")
    h = _sha(code.strip().lower())
    if h in hashes:
        hashes.remove(h)
        conn.execute("UPDATE users SET recovery_codes = ? WHERE id = ?", (json.dumps(hashes), user["id"]))
        return True
    return False


# ---- password reset ---------------------------------------------------------------------------

def request_reset(conn, email: str, frontend_url: str) -> None:
    """Always succeeds from the caller's point of view, so it never reveals who has an account."""
    user = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    if user is None:
        return
    recent = conn.execute(
        "SELECT COUNT(*) FROM password_resets WHERE user_id = ? AND expires_at > ?",
        (user["id"], timeutil.to_iso(timeutil.now() + RESET_TTL - timedelta(minutes=15))),
    ).fetchone()[0]
    if recent >= 3:
        return  # at most 3 mails per 15 minutes
    token = secrets.token_urlsafe(32)
    conn.execute(
        "INSERT INTO password_resets(token_hash, user_id, expires_at) VALUES (?,?,?)",
        (_sha(token), user["id"], timeutil.to_iso(timeutil.now() + RESET_TTL)),
    )
    link = f"{frontend_url.rstrip('/')}/reset?token={token}"
    mailer.send(
        user["email"],
        "Reja: parolni tiklash / сброс пароля / password reset",
        f"{user['name']},\n\nParolni tiklash uchun havola (1 soat amal qiladi):\n{link}\n\n"
        "Agar buni siz so'ramagan bo'lsangiz, bu xatni e'tiborsiz qoldiring.\n",
    )


def reset_password(conn, token: str, password: str) -> None:
    row = conn.execute("SELECT * FROM password_resets WHERE token_hash = ?", (_sha(token),)).fetchone()
    if row is None or row["used_at"] or timeutil.parse_iso(row["expires_at"]) < timeutil.now():
        raise ApiError(400, "reset_invalid")
    conn.execute("UPDATE password_resets SET used_at = ? WHERE token_hash = ?", (stamp(), row["token_hash"]))
    conn.execute(
        "UPDATE users SET password_hash = ?, token_version = token_version + 1 WHERE id = ?",
        (security.hash_password(password), row["user_id"]),
    )
    revoke_other_sessions(conn, row["user_id"], None)


# ---- API keys ----------------------------------------------------------------------------------

def create_key(conn, user_id: str, name: str) -> dict:
    if conn.execute("SELECT COUNT(*) FROM api_keys WHERE user_id = ? AND revoked_at IS NULL", (user_id,)).fetchone()[0] >= 20:
        raise ApiError(400, "too_many_keys", limit=20)
    raw = API_KEY_PREFIX + secrets.token_urlsafe(32)
    kid = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO api_keys(id, user_id, name, prefix, key_hash, created_at) VALUES (?,?,?,?,?,?)",
        (kid, user_id, name, raw[:10], _sha(raw), stamp()),
    )
    # The full key is shown once; only its hash is stored.
    return {"id": kid, "name": name, "prefix": raw[:10], "key": raw, "created_at": stamp(), "last_used_at": None}


def list_keys(conn, user_id: str) -> list[dict]:
    return [
        dict(r)
        for r in conn.execute(
            "SELECT id, name, prefix, created_at, last_used_at FROM api_keys WHERE user_id = ? AND revoked_at IS NULL ORDER BY created_at DESC",
            (user_id,),
        )
    ]


def revoke_key(conn, user_id: str, key_id: str) -> None:
    if not conn.execute("UPDATE api_keys SET revoked_at = ? WHERE id = ? AND user_id = ? AND revoked_at IS NULL", (stamp(), key_id, user_id)).rowcount:
        raise not_found("api_key")


def user_for_key(conn, raw: str):
    row = conn.execute("SELECT * FROM api_keys WHERE key_hash = ? AND revoked_at IS NULL", (_sha(raw),)).fetchone()
    if row is None:
        raise ApiError(401, "invalid_token")
    if row["last_used_at"] is None or (timeutil.now() - timeutil.parse_iso(row["last_used_at"])).total_seconds() > SESSION_TOUCH_SECONDS:
        conn.execute("UPDATE api_keys SET last_used_at = ? WHERE id = ?", (stamp(), row["id"]))
    return conn.execute("SELECT * FROM users WHERE id = ?", (row["user_id"],)).fetchone()
