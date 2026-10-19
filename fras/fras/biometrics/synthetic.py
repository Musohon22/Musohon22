"""Synthetic camera frames for the DEV provider (tests, demo seed, kiosk demo).

They are textured noise images, not faces: the DEV provider treats the whole frame as one
"face" and derives a deterministic vector from its pixels. Nothing here says anything about
how a real face model performs.
"""

from __future__ import annotations

import base64
import io

import numpy as np
from PIL import Image, ImageFilter


def frames_for(seed: int, n: int = 3, still: bool = False) -> list[str]:
    """n JPEG data-URLs of the same synthetic "person"; small shifts between frames pass the
    motion liveness check, identical frames (still=True) imitate a printed photo."""
    rng = np.random.default_rng(seed)
    base = Image.fromarray((rng.random((520, 680)) * 255).astype("uint8")).filter(ImageFilter.GaussianBlur(3))
    arr = np.asarray(base).astype(np.float32)
    arr = (arr - arr.mean()) / arr.std() * 40 + 135
    out = []
    for i in range(n):
        shift = 0 if still else i
        a = np.roll(arr, (shift * 2, shift * 3), axis=(0, 1))[20:500, 20:660]
        img = Image.fromarray(np.stack([a, a, a], -1).clip(0, 255).astype("uint8"))
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=92)
        out.append("data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode())
    return out
