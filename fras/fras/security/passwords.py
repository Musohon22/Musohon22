"""Password and PIN hashing with scrypt (stdlib), plus a password policy."""

from __future__ import annotations

import base64
import hashlib
import hmac
import os

N, R, P = 2 ** 14, 8, 1


def hash_secret(secret: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.scrypt(secret.encode(), salt=salt, n=N, r=R, p=P, dklen=32)
    return f"scrypt${N}${R}${P}${base64.b64encode(salt).decode()}${base64.b64encode(dk).decode()}"


def verify_secret(secret: str, stored: str | None) -> bool:
    if not stored:
        # Spend similar time so missing accounts are not distinguishable by timing.
        hashlib.scrypt(secret.encode(), salt=b"0" * 16, n=N, r=R, p=P, dklen=32)
        return False
    try:
        _, n, r, p, salt, dk = stored.split("$")
        calc = hashlib.scrypt(
            secret.encode(), salt=base64.b64decode(salt), n=int(n), r=int(r), p=int(p), dklen=32
        )
        return hmac.compare_digest(calc, base64.b64decode(dk))
    except ValueError:
        return False


def password_problems(password: str) -> list[str]:
    problems = []
    if len(password) < 10:
        problems.append("min_length_10")
    if password.lower() == password or password.upper() == password:
        problems.append("mixed_case")
    if not any(c.isdigit() for c in password):
        problems.append("digit")
    return problems


TRIVIAL_PINS = {"0000", "1111", "1234", "12345", "123456", "4321", "2222", "9999", "000000", "111111"}


def pin_problems(pin: str) -> list[str]:
    if not pin.isdigit() or not 4 <= len(pin) <= 6:
        return ["pin_format"]
    if pin in TRIVIAL_PINS or len(set(pin)) == 1:
        return ["pin_trivial"]
    return []
