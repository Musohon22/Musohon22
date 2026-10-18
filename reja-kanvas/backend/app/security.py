import base64
import hashlib
import hmac
import secrets
import threading
import time
from datetime import timedelta

import jwt

from . import config, timeutil
from .errors import ApiError

_ITERATIONS = 240_000
_secret: str | None = None


def _key() -> str:
    global _secret
    if _secret is None:
        _secret = config.secret_key()
    return _secret


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _ITERATIONS)
    return "pbkdf2_sha256${}${}${}".format(
        _ITERATIONS, base64.b64encode(salt).decode(), base64.b64encode(digest).decode()
    )


def verify_password(password: str, stored: str) -> bool:
    try:
        _, iterations, salt_b64, digest_b64 = stored.split("$")
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), base64.b64decode(salt_b64), int(iterations)
        )
        return hmac.compare_digest(digest, base64.b64decode(digest_b64))
    except (ValueError, TypeError):
        return False


def create_token(user_id: str, version: int = 0, session_id: str | None = None) -> str:
    issued = timeutil.now()
    payload = {
        "sub": user_id,
        "ver": version,
        "sid": session_id,
        "iat": int(issued.timestamp()),
        "exp": int((issued + timedelta(days=config.TOKEN_TTL_DAYS)).timestamp()),
    }
    return jwt.encode(payload, _key(), algorithm="HS256")


def decode_token(token: str) -> tuple[str, int, str | None]:
    try:
        payload = jwt.decode(token, _key(), algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        raise ApiError(401, "token_expired")
    except jwt.PyJWTError:
        raise ApiError(401, "invalid_token")
    return payload["sub"], int(payload.get("ver", 0)), payload.get("sid")


class LoginLimiter:
    """In-memory brute-force guard: too many failures for one email locks it for a while."""

    def __init__(self):
        self._failures: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def _recent(self, key: str) -> list[float]:
        cutoff = time.monotonic() - config.LOGIN_WINDOW_SECONDS
        hits = [t for t in self._failures.get(key, []) if t > cutoff]
        self._failures[key] = hits
        return hits

    def check(self, key: str) -> None:
        with self._lock:
            if len(self._recent(key)) >= config.LOGIN_MAX_FAILURES:
                raise ApiError(429, "too_many_attempts")

    def fail(self, key: str) -> None:
        with self._lock:
            self._recent(key).append(time.monotonic())

    def reset(self, key: str) -> None:
        with self._lock:
            self._failures.pop(key, None)


login_limiter = LoginLimiter()
