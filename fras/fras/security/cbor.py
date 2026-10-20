"""Minimal CBOR (RFC 8949) for WebAuthn: attestation objects and COSE keys.

Decodes the subset authenticators emit (ints, byte/text strings, arrays, maps, simple values);
indefinite lengths, floats and tags are rejected. The encoder exists for tests that play
the authenticator's role.
"""

from __future__ import annotations


class CBORError(ValueError):
    pass


def decode(data: bytes) -> tuple[object, int]:
    """Returns (value, bytes consumed) — WebAuthn appends data after the COSE key."""
    return _item(memoryview(data), 0, 0)


def loads(data: bytes) -> object:
    value, used = decode(data)
    if used != len(data):
        raise CBORError("trailing bytes")
    return value


def _length(buf, pos: int, info: int) -> tuple[int, int]:
    if info < 24:
        return info, pos
    size = {24: 1, 25: 2, 26: 4, 27: 8}.get(info)
    if size is None:
        raise CBORError("indefinite or reserved length")
    if pos + size > len(buf):
        raise CBORError("truncated")
    return int.from_bytes(buf[pos:pos + size], "big"), pos + size


def _item(buf, pos: int, depth: int):
    if depth > 16:
        raise CBORError("nesting too deep")
    if pos >= len(buf):
        raise CBORError("truncated")
    major, info = buf[pos] >> 5, buf[pos] & 0x1F
    pos += 1
    if major == 7:
        simple = {20: False, 21: True, 22: None}
        if info in simple:
            return simple[info], pos
        raise CBORError("unsupported simple value / float")
    n, pos = _length(buf, pos, info)
    if major == 0:
        return n, pos
    if major == 1:
        return -1 - n, pos
    if major in (2, 3):
        if pos + n > len(buf):
            raise CBORError("truncated")
        raw = bytes(buf[pos:pos + n])
        return (raw if major == 2 else raw.decode("utf-8")), pos + n
    if major == 4:
        out = []
        for _ in range(n):
            v, pos = _item(buf, pos, depth + 1)
            out.append(v)
        return out, pos
    if major == 5:
        out = {}
        for _ in range(n):
            k, pos = _item(buf, pos, depth + 1)
            v, pos = _item(buf, pos, depth + 1)
            out[k] = v
        return out, pos
    raise CBORError("tags are not supported")


def dumps(value) -> bytes:
    def head(major: int, n: int) -> bytes:
        if n < 24:
            return bytes([major << 5 | n])
        for info, size in ((24, 1), (25, 2), (26, 4), (27, 8)):
            if n < 1 << (8 * size):
                return bytes([major << 5 | info]) + n.to_bytes(size, "big")
        raise CBORError("integer too large")

    if value is False or value is True or value is None:
        return bytes([0xF4 if value is False else 0xF5 if value is True else 0xF6])
    if isinstance(value, int):
        return head(0, value) if value >= 0 else head(1, -1 - value)
    if isinstance(value, bytes):
        return head(2, len(value)) + value
    if isinstance(value, str):
        raw = value.encode()
        return head(3, len(raw)) + raw
    if isinstance(value, (list, tuple)):
        return head(4, len(value)) + b"".join(dumps(v) for v in value)
    if isinstance(value, dict):
        return head(5, len(value)) + b"".join(dumps(k) + dumps(v) for k, v in value.items())
    raise CBORError(f"cannot encode {type(value).__name__}")
