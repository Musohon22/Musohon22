"""Face detection / embedding / liveness providers.

* `OnnxProvider` runs a SCRFD-style detector and an ArcFace-style recognizer
  through onnxruntime. Model files are supplied by the operator (their
  licence must allow commercial use — spec risk R-08); they are not shipped.
* `DevProvider` exists for automated tests and UI demos only. It is NOT a face
  recognizer: it treats the central region of the frame as "the face" and
  derives a vector from its pixels. `load_settings` refuses it in prod.

No accuracy figure is claimed for either; thresholds must be calibrated on
real enrolment data (PoC, document D-02).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

import numpy as np

from . import imaging

# ArcFace canonical 5-point template for 112x112 crops.
ARCFACE_DST = np.array([[38.2946, 51.6963], [73.5318, 51.5014], [56.0252, 71.7366],
                        [41.5493, 92.3655], [70.7299, 92.2041]], dtype=np.float32)


@dataclass
class Face:
    bbox: tuple[float, float, float, float]
    score: float
    landmarks: np.ndarray | None


class Provider:
    model_version = "base"
    is_dev = False

    def detect(self, img: np.ndarray) -> list[Face]:
        raise NotImplementedError

    def embed(self, img: np.ndarray, face: Face) -> np.ndarray:
        raise NotImplementedError

    def liveness(self, frames: list[np.ndarray], faces: list[Face]) -> tuple[float, str]:
        """Returns (score 0..1, method)."""
        raise NotImplementedError


def similarity_transform(src: np.ndarray, dst: np.ndarray) -> np.ndarray:
    """Umeyama estimate of a 2x3 similarity transform mapping src points to dst."""
    src = src.astype(np.float64)
    dst = dst.astype(np.float64)
    n = src.shape[0]
    mu_s, mu_d = src.mean(0), dst.mean(0)
    s_c, d_c = src - mu_s, dst - mu_d
    cov = d_c.T @ s_c / n
    u, sig, vt = np.linalg.svd(cov)
    d = np.ones(2)
    if np.linalg.det(cov) < 0:
        d[-1] = -1
    r = u @ np.diag(d) @ vt
    var_s = (s_c ** 2).sum() / n
    scale = (sig * d).sum() / var_s
    t = mu_d - scale * r @ mu_s
    return np.hstack([scale * r, t[:, None]]).astype(np.float32)


def warp_affine(img: np.ndarray, m: np.ndarray, size: int = 112) -> np.ndarray:
    """Bilinear inverse warp (no OpenCV dependency)."""
    full = np.vstack([m, [0, 0, 1]])
    inv = np.linalg.inv(full)[:2]
    ys, xs = np.mgrid[0:size, 0:size].astype(np.float32)
    sx = inv[0, 0] * xs + inv[0, 1] * ys + inv[0, 2]
    sy = inv[1, 0] * xs + inv[1, 1] * ys + inv[1, 2]
    h, w = img.shape[:2]
    x0 = np.clip(np.floor(sx).astype(int), 0, w - 1)
    y0 = np.clip(np.floor(sy).astype(int), 0, h - 1)
    x1, y1 = np.clip(x0 + 1, 0, w - 1), np.clip(y0 + 1, 0, h - 1)
    fx, fy = (sx - np.floor(sx))[..., None], (sy - np.floor(sy))[..., None]
    a, b = img[y0, x0].astype(np.float32), img[y0, x1].astype(np.float32)
    c, d = img[y1, x0].astype(np.float32), img[y1, x1].astype(np.float32)
    out = a * (1 - fx) * (1 - fy) + b * fx * (1 - fy) + c * (1 - fx) * fy + d * fx * fy
    return np.clip(out, 0, 255).astype(np.uint8)


class OnnxProvider(Provider):
    is_dev = False

    def __init__(self, detector_path: str, recognizer_path: str, pad_path: str | None = None, det_size: int = 640,
                 det_threshold: float = 0.5):
        import onnxruntime as ort
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = 2
        self.det = ort.InferenceSession(detector_path, opts, providers=["CPUExecutionProvider"])
        self.rec = ort.InferenceSession(recognizer_path, opts, providers=["CPUExecutionProvider"])
        self.pad = ort.InferenceSession(pad_path, opts, providers=["CPUExecutionProvider"]) if pad_path else None
        self.det_size = det_size
        self.det_threshold = det_threshold
        with open(recognizer_path, "rb") as f:
            self.model_version = "onnx-" + hashlib.sha256(f.read()).hexdigest()[:12]

    # -- SCRFD decoding (3 strides x {scores, boxes, kps}, 2 anchors per cell)
    def detect(self, img: np.ndarray) -> list[Face]:
        h, w = img.shape[:2]
        scale = self.det_size / max(h, w)
        nh, nw = int(round(h * scale)), int(round(w * scale))
        from PIL import Image
        resized = np.asarray(Image.fromarray(img).resize((nw, nh)))
        canvas = np.zeros((self.det_size, self.det_size, 3), np.float32)
        canvas[:nh, :nw] = resized
        blob = ((canvas - 127.5) / 128.0).transpose(2, 0, 1)[None].astype(np.float32)
        outs = self.det.run(None, {self.det.get_inputs()[0].name: blob})
        strides = (8, 16, 32)
        n = len(strides)
        boxes_all, scores_all, kps_all = [], [], []
        for i, stride in enumerate(strides):
            scores = outs[i].reshape(-1)
            deltas = outs[i + n].reshape(-1, 4) * stride
            kps = outs[i + 2 * n].reshape(-1, 10) * stride if len(outs) >= 3 * n else None
            fh = fw = self.det_size // stride
            centers = np.stack(np.mgrid[:fh, :fw][::-1], axis=-1).reshape(-1, 2).astype(np.float32) * stride
            centers = np.repeat(centers, 2, axis=0)
            keep = scores >= self.det_threshold
            c = centers[keep]
            d = deltas[keep]
            boxes = np.stack([c[:, 0] - d[:, 0], c[:, 1] - d[:, 1], c[:, 0] + d[:, 2], c[:, 1] + d[:, 3]], -1)
            boxes_all.append(boxes)
            scores_all.append(scores[keep])
            if kps is not None:
                k = kps[keep].reshape(-1, 5, 2) + c[:, None, :]
                kps_all.append(k)
        if not boxes_all or sum(len(b) for b in boxes_all) == 0:
            return []
        boxes = np.concatenate(boxes_all) / scale
        scores = np.concatenate(scores_all)
        kps = np.concatenate(kps_all) / scale if kps_all else None
        order = _nms(boxes, scores, 0.4)
        return [Face(tuple(boxes[i].tolist()), float(scores[i]), kps[i] if kps is not None else None) for i in order]

    def embed(self, img: np.ndarray, face: Face) -> np.ndarray:
        if face.landmarks is None:
            raise ValueError("detector returned no landmarks")
        m = similarity_transform(face.landmarks, ARCFACE_DST)
        crop = warp_affine(img, m, 112).astype(np.float32)
        blob = ((crop - 127.5) / 127.5).transpose(2, 0, 1)[None]
        vec = self.rec.run(None, {self.rec.get_inputs()[0].name: blob})[0][0].astype(np.float32)
        return vec / (np.linalg.norm(vec) + 1e-9)

    def liveness(self, frames: list[np.ndarray], faces: list[Face]) -> tuple[float, str]:
        if self.pad is None:
            return _motion_liveness(frames, faces), "passive_motion"
        scores = []
        for img, face in zip(frames, faces):
            x0, y0, x1, y1 = [int(v) for v in face.bbox]
            from PIL import Image
            crop = np.asarray(Image.fromarray(img[max(0, y0):y1, max(0, x0):x1]).resize((80, 80)), np.float32)
            blob = (crop / 255.0).transpose(2, 0, 1)[None].astype(np.float32)
            out = self.pad.run(None, {self.pad.get_inputs()[0].name: blob})[0].reshape(-1)
            prob = np.exp(out) / np.exp(out).sum() if out.size > 1 else 1 / (1 + np.exp(-out))
            scores.append(float(prob[1] if out.size > 1 else prob[0]))
        return float(np.mean(scores)), "pad_model"


def _nms(boxes: np.ndarray, scores: np.ndarray, thr: float) -> list[int]:
    order = scores.argsort()[::-1]
    keep = []
    while order.size:
        i = order[0]
        keep.append(int(i))
        xx1 = np.maximum(boxes[i, 0], boxes[order[1:], 0])
        yy1 = np.maximum(boxes[i, 1], boxes[order[1:], 1])
        xx2 = np.minimum(boxes[i, 2], boxes[order[1:], 2])
        yy2 = np.minimum(boxes[i, 3], boxes[order[1:], 3])
        inter = np.maximum(0, xx2 - xx1) * np.maximum(0, yy2 - yy1)
        area = (boxes[:, 2] - boxes[:, 0]) * (boxes[:, 3] - boxes[:, 1])
        iou = inter / (area[i] + area[order[1:]] - inter + 1e-9)
        order = order[1:][iou < thr]
    return keep


def _motion_liveness(frames: list[np.ndarray], faces: list[Face]) -> float:
    """Weak passive signal: a live face shows small natural motion and fine texture between
    frames; a still photo shows almost none. This is NOT presentation-attack detection —
    real deployments need IR/depth hardware or a certified PAD model (spec section 4)."""
    if len(frames) < 2:
        return 0.0
    crops = []
    for img, f in zip(frames, faces):
        x0, y0, x1, y1 = [int(v) for v in f.bbox]
        g = imaging.gray(img[max(0, y0):max(y0 + 1, y1), max(0, x0):max(x0 + 1, x1)])
        from PIL import Image
        crops.append(np.asarray(Image.fromarray(g.astype(np.uint8)).resize((64, 64)), np.float32))
    diffs = [float(np.abs(crops[i] - crops[i - 1]).mean()) for i in range(1, len(crops))]
    motion = float(np.mean(diffs))
    texture = float(np.mean([imaging.laplacian_var(c) for c in crops]))
    # motion between ~1.5 and ~25 grey levels and some texture look live; a frozen image (photo held
    # perfectly still, replayed still frame) scores low, and so does violent change (frame swapping)
    if motion < 1.5:
        m_score = 0.3 * motion / 1.5
    elif motion <= 25:
        m_score = 1.0
    else:
        m_score = max(0.0, 1 - (motion - 25) / 25)
    t_score = min(1.0, texture / 60.0)
    return round(0.7 * m_score + 0.3 * t_score, 3)


class DevProvider(Provider):
    """Test/demo stand-in — NOT a face recognizer (see module docstring)."""

    model_version = "dev-0 (not biometric)"
    is_dev = True

    def detect(self, img: np.ndarray) -> list[Face]:
        h, w = img.shape[:2]
        g = imaging.gray(img)
        if float(g.std()) < 4:          # blank frame: "no face"
            return []
        side = min(h, w) * 0.6
        x0, y0 = (w - side) / 2, (h - side) / 2
        cx, cy = w / 2, h / 2
        lm = np.array([[cx - side * 0.18, cy - side * 0.12], [cx + side * 0.18, cy - side * 0.12],
                       [cx, cy + side * 0.02], [cx - side * 0.14, cy + side * 0.2], [cx + side * 0.14, cy + side * 0.2]],
                      dtype=np.float32)
        return [Face((x0, y0, x0 + side, y0 + side), 0.99, lm)]

    def embed(self, img: np.ndarray, face: Face) -> np.ndarray:
        from PIL import Image
        x0, y0, x1, y1 = [int(v) for v in face.bbox]
        crop = imaging.gray(img[y0:y1, x0:x1])
        small = np.asarray(Image.fromarray(crop.astype(np.uint8)).resize((16, 16)), np.float32).reshape(-1)
        small = (small - small.mean()) / (small.std() + 1e-6)
        rng = np.random.default_rng(1234)
        proj = rng.standard_normal((256, 128)).astype(np.float32)
        vec = small @ proj
        return vec / (np.linalg.norm(vec) + 1e-9)

    def liveness(self, frames: list[np.ndarray], faces: list[Face]) -> tuple[float, str]:
        return _motion_liveness(frames, faces), "dev_motion"


_provider: Provider | None = None


def get_provider(settings) -> Provider:
    global _provider
    if _provider is None:
        if settings.biometric_provider == "onnx":
            if not (settings.detector_model and settings.recognizer_model):
                raise RuntimeError("FRAS_DETECTOR_MODEL and FRAS_RECOGNIZER_MODEL must point to ONNX files")
            _provider = OnnxProvider(settings.detector_model, settings.recognizer_model, settings.pad_model)
        else:
            _provider = DevProvider()
    return _provider


def set_provider(p: Provider | None) -> None:
    global _provider
    _provider = p
