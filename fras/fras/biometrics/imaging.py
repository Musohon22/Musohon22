"""Image decoding and quality metrics (numpy + Pillow only)."""

from __future__ import annotations

import base64
import io
from dataclasses import dataclass

import numpy as np
from PIL import Image, ImageOps

MAX_SIDE = 1280


def decode(data: bytes | str) -> np.ndarray:
    """Decode JPEG/PNG bytes or a data URL into an RGB uint8 array (EXIF orientation applied)."""
    if isinstance(data, str):
        if data.startswith("data:"):
            data = data.split(",", 1)[1]
        data = base64.b64decode(data)
    if len(data) > 4 * 1024 * 1024:
        raise ValueError("image larger than 4 MB")
    img = Image.open(io.BytesIO(data))
    img = ImageOps.exif_transpose(img).convert("RGB")
    if max(img.size) > MAX_SIDE:
        img.thumbnail((MAX_SIDE, MAX_SIDE))
    return np.asarray(img, dtype=np.uint8)


def encode_jpeg(arr: np.ndarray, quality: int = 85) -> bytes:
    buf = io.BytesIO()
    Image.fromarray(arr).save(buf, format="JPEG", quality=quality)
    return buf.getvalue()


def gray(arr: np.ndarray) -> np.ndarray:
    return (0.299 * arr[..., 0] + 0.587 * arr[..., 1] + 0.114 * arr[..., 2]).astype(np.float32)


def laplacian_var(g: np.ndarray) -> float:
    """Variance of a 3x3 Laplacian — standard sharpness proxy (low = blurry)."""
    if g.shape[0] < 3 or g.shape[1] < 3:
        return 0.0
    lap = (-4 * g[1:-1, 1:-1] + g[:-2, 1:-1] + g[2:, 1:-1] + g[1:-1, :-2] + g[1:-1, 2:])
    return float(lap.var())


@dataclass
class Quality:
    brightness: float      # 0..255 mean of the face crop
    uniformity: float      # 0..1, 1 = evenly lit (left/right halves similar)
    sharpness: float       # Laplacian variance
    face_ratio: float      # face height / frame height
    eye_distance_px: float
    yaw_deg: float
    pitch_deg: float
    score: float           # 0..1 combined
    issues: list[str]


def assess(arr: np.ndarray, bbox: tuple[float, float, float, float], landmarks: np.ndarray | None) -> Quality:
    h, w = arr.shape[:2]
    x0, y0, x1, y1 = [int(round(v)) for v in bbox]
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(w, x1), min(h, y1)
    crop = gray(arr[y0:y1, x0:x1]) if x1 > x0 and y1 > y0 else np.zeros((1, 1), np.float32)
    brightness = float(crop.mean())
    half = crop.shape[1] // 2
    left, right = crop[:, :half].mean() if half else 0, crop[:, half:].mean() if half else 0
    uniformity = 1.0 - min(1.0, abs(float(left) - float(right)) / 80.0)
    sharp = laplacian_var(crop)
    face_ratio = (y1 - y0) / max(1, h)
    eye_px = yaw = pitch = 0.0
    if landmarks is not None and len(landmarks) >= 5:
        le, re, nose, lm, rm = landmarks[:5]
        eye_px = float(np.linalg.norm(re - le))
        mid_eye = (le + re) / 2
        # nose offset from the eye midline approximates yaw; vertical ratio approximates pitch
        yaw = float(np.degrees(np.arctan2((nose[0] - mid_eye[0]), max(eye_px, 1.0) * 0.9)))
        mouth = (lm + rm) / 2
        ratio = (nose[1] - mid_eye[1]) / max(1.0, (mouth[1] - mid_eye[1]))
        pitch = float((ratio - 0.55) * 90)
    issues = []
    if brightness < 60:
        issues.append("too_dark")
    elif brightness > 210:
        issues.append("too_bright")
    if uniformity < 0.6:
        issues.append("uneven_light")
    if sharp < 40:
        issues.append("blurry")
    if eye_px and eye_px < 80:
        issues.append("too_far")
    if face_ratio > 0.85:
        issues.append("too_close")
    if abs(yaw) > 15:
        issues.append("turn_to_camera")
    if abs(pitch) > 15:
        issues.append("look_straight")
    parts = [
        1 - min(1, abs(brightness - 135) / 135),
        uniformity,
        min(1.0, sharp / 150.0),
        min(1.0, (eye_px or 80) / 80.0),
        1 - min(1, abs(yaw) / 45),
    ]
    score = float(np.clip(np.mean(parts), 0, 1))
    return Quality(brightness, uniformity, sharp, face_ratio, eye_px, yaw, pitch, score, issues)
