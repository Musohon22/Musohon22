"""Short-lived JWT access tokens plus opaque refresh tokens stored hashed in `sessions`."""

from __future__ import annotations

import hashlib
import time

import jwt

ALGO = "HS256"


def issue_access(secret: str, *, sub: str, realm: str, tenant_id: str | None, session_id: str,
                 mfa: bool, ttl_s: int) -> str:
    now = int(time.time())
    payload = {
        "sub": sub,
        "realm": realm,          # tenant | platform | device
        "tid": tenant_id,
        "sid": session_id,
        "mfa": mfa,
        "iat": now,
        "exp": now + ttl_s,
    }
    return jwt.encode(payload, secret, algorithm=ALGO)


def decode_access(secret: str, token: str) -> dict:
    return jwt.decode(token, secret, algorithms=[ALGO], options={"require": ["exp", "sub", "sid"]})


def hash_token(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()
