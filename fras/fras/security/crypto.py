"""Envelope encryption and signatures.

* The master key (from FRAS_MASTER_KEY / KMS) wraps one data key (DEK) per tenant.
* Tenant DEKs encrypt sensitive columns (PINFL, TOTP secrets, webhook secrets)
  and biometric templates. Templates use a key derived from the DEK with a
  distinct label, so biometric data never shares a key with ordinary PII.
* Devices sign event batches with Ed25519; the gateway verifies them.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF


def new_key() -> bytes:
    return os.urandom(32)


def seal(key: bytes, plaintext: bytes, aad: bytes = b"") -> bytes:
    """AES-256-GCM; output = nonce(12) || ciphertext+tag."""
    nonce = os.urandom(12)
    return nonce + AESGCM(key).encrypt(nonce, plaintext, aad)


def open_sealed(key: bytes, blob: bytes, aad: bytes = b"") -> bytes:
    return AESGCM(key).decrypt(blob[:12], blob[12:], aad)


def wrap_dek(master_key: bytes, dek: bytes, tenant_id: str) -> bytes:
    return seal(master_key, dek, aad=b"dek:" + tenant_id.encode())


def unwrap_dek(master_key: bytes, wrapped: bytes, tenant_id: str) -> bytes:
    return open_sealed(master_key, wrapped, aad=b"dek:" + tenant_id.encode())


def derive(key: bytes, label: str) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=label.encode()).derive(key)


def keyed_hash(key: bytes, value: str) -> str:
    """Deterministic keyed hash for equality search on encrypted fields."""
    return hmac.new(derive(key, "search"), value.encode(), hashlib.sha256).hexdigest()


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ------------------------------------------------------------ device keys

def generate_device_keys() -> tuple[bytes, bytes]:
    """Returns (private_raw, public_raw) Ed25519."""
    from cryptography.hazmat.primitives import serialization

    priv = Ed25519PrivateKey.generate()
    priv_raw = priv.private_bytes(
        serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption()
    )
    pub_raw = priv.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return priv_raw, pub_raw


def sign(private_raw: bytes, message: bytes) -> str:
    return base64.b64encode(Ed25519PrivateKey.from_private_bytes(private_raw).sign(message)).decode()


def verify(public_raw: bytes, message: bytes, signature_b64: str) -> bool:
    try:
        Ed25519PublicKey.from_public_bytes(public_raw).verify(base64.b64decode(signature_b64), message)
        return True
    except (InvalidSignature, ValueError):
        return False


# ------------------------------------------------------------ gallery packages
# A gallery package is encrypted to one device: ephemeral X25519 key agreement
# with the device's X25519 key (derived from its Ed25519 seed on the device).

def seal_for_device(device_x25519_pub: bytes, plaintext: bytes) -> dict:
    eph = X25519PrivateKey.generate()
    shared = eph.exchange(X25519PublicKey.from_public_bytes(device_x25519_pub))
    key = derive(shared, "gallery-package")
    from cryptography.hazmat.primitives import serialization

    eph_pub = eph.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return {
        "ephemeral_pub": base64.b64encode(eph_pub).decode(),
        "ciphertext": base64.b64encode(seal(key, plaintext, aad=b"gallery")).decode(),
    }


def open_device_package(device_x25519_priv: bytes, package: dict) -> bytes:
    priv = X25519PrivateKey.from_private_bytes(device_x25519_priv)
    shared = priv.exchange(X25519PublicKey.from_public_bytes(base64.b64decode(package["ephemeral_pub"])))
    key = derive(shared, "gallery-package")
    return open_sealed(key, base64.b64decode(package["ciphertext"]), aad=b"gallery")


def x25519_from_seed(seed: bytes) -> tuple[bytes, bytes]:
    """Device-side: deterministic X25519 keypair from the device secret seed."""
    from cryptography.hazmat.primitives import serialization

    priv = X25519PrivateKey.from_private_bytes(derive(seed, "x25519"))
    pub = priv.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    priv_raw = priv.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption())
    return priv_raw, pub
