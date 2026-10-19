"""Signed transport to the FRAS gateway (Ed25519 over method, path, timestamp, body hash)."""

from __future__ import annotations

import base64
import hashlib
import json
import time
import urllib.error
import urllib.request

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


class TransportError(Exception):
    def __init__(self, status: int | None, message: str):
        super().__init__(message)
        self.status = status


def sign_headers(device_id: str, seed: bytes, method: str, path: str, body: bytes) -> dict:
    ts = str(int(time.time()))
    msg = f"{method}\n{path}\n{ts}\n{hashlib.sha256(body).hexdigest()}".encode()
    sig = base64.b64encode(Ed25519PrivateKey.from_private_bytes(seed).sign(msg)).decode()
    return {"X-Device-Id": device_id, "X-Device-Ts": ts, "X-Device-Sig": sig}


class HttpTransport:
    def __init__(self, base_url: str, timeout: float = 10.0):
        self.base = base_url.rstrip("/")
        self.timeout = timeout

    def send(self, method: str, path: str, body: bytes, headers: dict) -> tuple[int, dict]:
        req = urllib.request.Request(self.base + path, data=body if method != "GET" else None, method=method,
                                     headers={"Content-Type": "application/json", **headers})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                return r.status, json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            try:
                return e.code, json.loads(e.read() or b"{}")
            except json.JSONDecodeError:
                return e.code, {}
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise TransportError(None, f"network: {e}") from e


class Gateway:
    """Device-side API client. `transport` is HttpTransport in production, an in-process stub in tests."""

    def __init__(self, transport, device_id: str | None = None, seed: bytes | None = None):
        self.t = transport
        self.device_id = device_id
        self.seed = seed

    def activate(self, code: str, serial: str | None, public_key: bytes, enc_public_key: bytes, firmware: str) -> dict:
        body = json.dumps({"code": code, "serial": serial, "public_key": base64.b64encode(public_key).decode(),
                           "enc_public_key": base64.b64encode(enc_public_key).decode(), "firmware": firmware}).encode()
        status, data = self.t.send("POST", "/api/v1/gateway/activate", body, {})
        if status != 200:
            raise TransportError(status, data.get("error", {}).get("message", "activation failed"))
        return data

    def call(self, method: str, path: str, payload=None) -> dict:
        body = json.dumps(payload).encode() if payload is not None else b""
        status, data = self.t.send(method, path, body, sign_headers(self.device_id, self.seed, method, path, body))
        if status >= 400:
            raise TransportError(status, data.get("error", {}).get("code", f"HTTP {status}"))
        return data
