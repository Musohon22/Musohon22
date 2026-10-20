"""WebAuthn (passkey / Windows Hello) relying-party checks — registration and assertion.

What this proves: the private key that never leaves the employee's laptop (TPM-backed for
Windows Hello) signed our one-time challenge, and the authenticator reports that it verified
the user (UV flag: Windows Hello face with its IR camera, fingerprint, or the Hello PIN).
What it cannot prove: *which* of those methods Hello used — the protocol does not say —
nor anything about the face itself, which never leaves the device.

Attestation statements are not verified (we request attestation "none"), so the authenticator
model is not proven; device binding is enforced from the backup flags instead.
"""

from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import dataclass

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, ed25519, padding, rsa

from . import cbor

FLAG_UP, FLAG_UV, FLAG_BE, FLAG_BS, FLAG_AT = 0x01, 0x04, 0x08, 0x10, 0x40
ALG_ES256, ALG_EDDSA, ALG_RS256 = -7, -8, -257
SUPPORTED_ALGS = (ALG_ES256, ALG_EDDSA, ALG_RS256)   # Windows Hello registers RS256 or ES256

# AAGUIDs published for Windows Hello. Without verified attestation these are a label, not proof.
KNOWN_AAGUIDS = {
    "08987058-cadc-4b81-b6e1-30de50dcbe96": "Windows Hello",
    "9ddd1817-af5a-4672-a2b9-3e3dd95000a9": "Windows Hello",
    "6028b017-b1d4-4c02-b4b3-afcdafc96bb2": "Windows Hello",
    "adce0002-35bc-c60a-648b-0b25f1f05503": "Chrome (Mac)",
    "fbfc3007-154e-4ecc-8c0b-6e020557d7bd": "iCloud Keychain",
    "ea9b8d66-4d01-1d21-3ce4-b6b48cb575d4": "Google Password Manager",
}


class WebAuthnError(ValueError):
    def __init__(self, message: str, code: str):
        super().__init__(message)
        self.code = code


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def b64url_decode(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


@dataclass
class AuthData:
    rp_id_hash: bytes
    flags: int
    sign_count: int
    aaguid: str | None = None
    credential_id: bytes | None = None
    cose_key: dict | None = None

    @property
    def user_verified(self) -> bool:
        return bool(self.flags & FLAG_UV)

    @property
    def backup_eligible(self) -> bool:
        return bool(self.flags & FLAG_BE)


def parse_auth_data(raw: bytes) -> AuthData:
    if len(raw) < 37:
        raise WebAuthnError("authenticatorData too short", "WEBAUTHN_MALFORMED")
    ad = AuthData(raw[:32], raw[32], int.from_bytes(raw[33:37], "big"))
    if ad.flags & FLAG_AT:
        if len(raw) < 55:
            raise WebAuthnError("attested credential data truncated", "WEBAUTHN_MALFORMED")
        g = raw[37:53].hex()
        ad.aaguid = f"{g[:8]}-{g[8:12]}-{g[12:16]}-{g[16:20]}-{g[20:]}"
        n = int.from_bytes(raw[53:55], "big")
        ad.credential_id = raw[55:55 + n]
        if len(ad.credential_id) != n or not n:
            raise WebAuthnError("credential id truncated", "WEBAUTHN_MALFORMED")
        try:
            ad.cose_key, _ = cbor.decode(raw[55 + n:])
        except cbor.CBORError as e:
            raise WebAuthnError(f"bad COSE key: {e}", "WEBAUTHN_MALFORMED") from e
    return ad


def cose_to_public_key(cose: dict) -> tuple[int, bytes]:
    """COSE_Key → (alg, SubjectPublicKeyInfo DER)."""
    kty, alg = cose.get(1), cose.get(3)
    if kty == 2 and alg == ALG_ES256 and cose.get(-1) == 1:
        x, y = cose.get(-2), cose.get(-3)
        if not (isinstance(x, bytes) and isinstance(y, bytes) and len(x) == len(y) == 32):
            raise WebAuthnError("bad EC2 key", "WEBAUTHN_KEY_UNSUPPORTED")
        key = ec.EllipticCurvePublicNumbers(int.from_bytes(x, "big"), int.from_bytes(y, "big"), ec.SECP256R1()).public_key()
    elif kty == 3 and alg == ALG_RS256:
        n, e = cose.get(-1), cose.get(-2)
        if not (isinstance(n, bytes) and isinstance(e, bytes)) or len(n) < 256:
            raise WebAuthnError("RSA key must be at least 2048 bits", "WEBAUTHN_KEY_UNSUPPORTED")
        key = rsa.RSAPublicNumbers(int.from_bytes(e, "big"), int.from_bytes(n, "big")).public_key()
    elif kty == 1 and alg == ALG_EDDSA and cose.get(-1) == 6:
        key = ed25519.Ed25519PublicKey.from_public_bytes(cose.get(-2))
    else:
        raise WebAuthnError(f"unsupported key (kty={kty}, alg={alg})", "WEBAUTHN_KEY_UNSUPPORTED")
    return alg, key.public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)


def _client_data(raw: bytes, expected_type: str, challenge: str, origins: set[str]) -> None:
    try:
        cd = json.loads(raw)
    except (ValueError, UnicodeDecodeError) as e:
        raise WebAuthnError("clientDataJSON is not JSON", "WEBAUTHN_MALFORMED") from e
    if cd.get("type") != expected_type:
        raise WebAuthnError("wrong ceremony type", "WEBAUTHN_MALFORMED")
    if cd.get("challenge") != challenge:
        raise WebAuthnError("challenge mismatch", "WEBAUTHN_CHALLENGE")
    if cd.get("origin") not in origins:
        raise WebAuthnError(f"origin {cd.get('origin')!r} is not allowed", "WEBAUTHN_ORIGIN")
    if cd.get("crossOrigin"):
        raise WebAuthnError("cross-origin ceremonies are not allowed", "WEBAUTHN_ORIGIN")


def _check_rp_and_flags(ad: AuthData, rp_id: str) -> None:
    if ad.rp_id_hash != hashlib.sha256(rp_id.encode()).digest():
        raise WebAuthnError("credential belongs to another site", "WEBAUTHN_RP")
    if not ad.flags & FLAG_UP:
        raise WebAuthnError("user presence missing", "WEBAUTHN_UP")
    if not ad.flags & FLAG_UV:
        raise WebAuthnError("the authenticator did not verify the user (Windows Hello face, fingerprint or PIN)",
                            "WEBAUTHN_UV_REQUIRED")


@dataclass
class Registration:
    credential_id: bytes
    alg: int
    public_key: bytes
    sign_count: int
    aaguid: str | None
    backup_eligible: bool
    fmt: str


def verify_registration(*, client_data_json: bytes, attestation_object: bytes, challenge: str, rp_id: str,
                        origins: set[str]) -> Registration:
    _client_data(client_data_json, "webauthn.create", challenge, origins)
    try:
        att = cbor.loads(attestation_object)
    except cbor.CBORError as e:
        raise WebAuthnError(f"bad attestation object: {e}", "WEBAUTHN_MALFORMED") from e
    if not isinstance(att, dict) or not isinstance(att.get("authData"), bytes):
        raise WebAuthnError("attestation object without authData", "WEBAUTHN_MALFORMED")
    ad = parse_auth_data(att["authData"])
    _check_rp_and_flags(ad, rp_id)
    if not ad.credential_id or not ad.cose_key:
        raise WebAuthnError("no credential in attestation", "WEBAUTHN_MALFORMED")
    alg, spki = cose_to_public_key(ad.cose_key)
    return Registration(ad.credential_id, alg, spki, ad.sign_count, ad.aaguid, ad.backup_eligible, str(att.get("fmt")))


def verify_assertion(*, client_data_json: bytes, authenticator_data: bytes, signature: bytes, challenge: str,
                     rp_id: str, origins: set[str], alg: int, public_key: bytes) -> AuthData:
    _client_data(client_data_json, "webauthn.get", challenge, origins)
    ad = parse_auth_data(authenticator_data)
    _check_rp_and_flags(ad, rp_id)
    signed = authenticator_data + hashlib.sha256(client_data_json).digest()
    key = serialization.load_der_public_key(public_key)
    try:
        if alg == ALG_ES256:
            key.verify(signature, signed, ec.ECDSA(hashes.SHA256()))
        elif alg == ALG_RS256:
            key.verify(signature, signed, padding.PKCS1v15(), hashes.SHA256())
        elif alg == ALG_EDDSA:
            key.verify(signature, signed)
        else:
            raise WebAuthnError("unsupported algorithm", "WEBAUTHN_KEY_UNSUPPORTED")
    except InvalidSignature as e:
        raise WebAuthnError("signature is invalid", "WEBAUTHN_SIGNATURE") from e
    return ad
