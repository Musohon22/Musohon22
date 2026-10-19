"""Terminal core: activation, gallery, local decisions (spec H.2), relay, sync with the gateway."""

from __future__ import annotations

import base64
import json
import logging
import os
import shutil
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

import numpy as np

from fras.biometrics import imaging
from fras.biometrics.providers import Provider
from fras.engine.decision import decide
from fras.security import crypto, passwords

from .store import OutboxFull, Store
from .transport import Gateway, TransportError

log = logging.getLogger("fras.edge")

MESSAGES = {
    "TRM-05": {"uz": "Xush kelibsiz, {name}", "ru": "Добро пожаловать, {name}"},
    "TRM-06": {"uz": "Xayr, {name}", "ru": "До свидания, {name}"},
    "TRM-07": {"uz": "Siz allaqachon qayd etilgansiz {time}", "ru": "Вы уже отмечены {time}"},
    "TRM-08": {"uz": "Siz tanilmadingiz. Qayta urining yoki karta ishlating",
               "ru": "Вы не распознаны. Повторите или используйте карту"},
    "TRM-09": {"uz": "Tekshiruv o'tmadi. Xavfsizlik xodimiga murojaat qiling",
               "ru": "Проверка не пройдена. Обратитесь к охране"},
    "TRM-10": {"uz": "Bu darvozadan o'tish ruxsati yo'q. Qo'riqchiga murojaat qiling",
               "ru": "Нет доступа через этот проход. Обратитесь к охране"},
    "TRM-11": {"uz": "Iltimos, yana bir bor kameraga qarang", "ru": "Пожалуйста, посмотрите в камеру ещё раз"},
    "TRM-12": {"uz": "Kartani yaqinlashtiring yoki PIN kiriting", "ru": "Приложите карту или введите PIN"},
    "TRM-13": {"uz": "Qo'riqchi chaqirildi. Iltimos kuting", "ru": "Охрана вызвана. Пожалуйста, подождите"},
    "TRM-14": {"uz": "Terminal vaqtincha ishlamayapti. Karta ishlating",
               "ru": "Терминал временно не работает. Используйте карту"},
    "TRM-16": {"uz": "Terminal to'lgan. Qo'riqchiga murojaat qiling", "ru": "Память терминала заполнена"},
}
DURATIONS_MS = {"TRM-05": 2000, "TRM-06": 2000, "TRM-07": 2000, "TRM-08": 5000, "TRM-09": 5000, "TRM-10": 4000,
                "TRM-11": 1500, "TRM-12": 20000, "TRM-13": 60000, "TRM-14": 0, "TRM-16": 0}


class Relay:
    """Gate output. SimulatedRelay records openings; HttpRelay drives controllers with an HTTP API."""

    def open(self, ms: int) -> None:
        raise NotImplementedError

    def test(self) -> bool:
        return True


class SimulatedRelay(Relay):
    def __init__(self):
        self.openings: list[float] = []

    def open(self, ms: int) -> None:
        self.openings.append(time.time())
        log.info("relay: open for %s ms", ms)


class HttpRelay(Relay):
    def __init__(self, url: str):
        self.url = url

    def open(self, ms: int) -> None:
        import urllib.request
        urllib.request.urlopen(urllib.request.Request(f"{self.url}?ms={ms}", method="POST"), timeout=2).read()

    def test(self) -> bool:
        try:
            self.open(100)
            return True
        except Exception:  # noqa: BLE001
            return False


@dataclass
class Gallery:
    version: int = 0
    ids: list[str] = field(default_factory=list)
    names: dict[str, str] = field(default_factory=dict)
    languages: dict[str, str] = field(default_factory=dict)
    matrix: np.ndarray | None = None
    cards: dict[str, tuple[str, str | None]] = field(default_factory=dict)   # card_no -> (employee_id, pin_hash)
    blocked: set[str] = field(default_factory=set)
    allowed: set[str] = field(default_factory=set)
    thresholds: dict = field(default_factory=lambda: {"accept": 0.62, "review": 0.50})
    liveness_required: bool = True
    liveness_min: float = 0.6
    debounce_min: int = 2

    @classmethod
    def from_payload(cls, data: dict) -> "Gallery":
        g = cls(version=data["version"], thresholds=data["thresholds"], liveness_required=data["liveness_required"],
                liveness_min=data["liveness_min"], debounce_min=data.get("debounce_min", 2),
                blocked=set(data.get("blocked", [])))
        vecs = []
        for p in data["people"]:
            g.allowed.add(p["employee_id"])
            g.names[p["employee_id"]] = p["name"]
            g.languages[p["employee_id"]] = p.get("language", "uz")
            if p.get("card_no"):
                g.cards[p["card_no"]] = (p["employee_id"], p.get("pin_hash"))
            if p.get("template"):
                v = np.frombuffer(base64.b64decode(p["template"]), dtype=np.float16).astype(np.float32)
                g.ids.append(p["employee_id"])
                vecs.append(v / (np.linalg.norm(v) + 1e-9))
        g.matrix = np.stack(vecs) if vecs else None
        return g

    def match(self, vec: np.ndarray) -> tuple[str | None, float | None, float | None]:
        if self.matrix is None:
            return None, None, None
        scores = self.matrix @ vec
        order = np.argsort(scores)[::-1]
        best = int(order[0])
        second = float(scores[order[1]]) if len(order) > 1 else None
        return self.ids[best], float(scores[best]), second


class Agent:
    def __init__(self, store: Store, gateway: Gateway, provider: Provider, relay: Relay | None = None,
                 data_dir: str | None = None, firmware: str = "edge-0.1.0", clock=time.time):
        self.store = store
        self.gw = gateway
        self.provider = provider
        self.relay = relay or SimulatedRelay()
        self.data_dir = data_dir
        self.firmware = firmware
        self.clock = clock
        self.online = False
        self.last_sync: float | None = None
        self.camera_ok = True
        self.gallery = Gallery()
        self._last_pass: dict[tuple[str, str], float] = {}
        self._attempts: dict[str, int] = {}
        self._lock = threading.Lock()
        self.help_requests: list[dict] = []
        if store.get("device_id"):
            self.gw.device_id = store.get("device_id")
            self.gw.seed = base64.b64decode(store.get("seed"))
            self._load_gallery()

    # ------------------------------------------------------------ identity
    @property
    def activated(self) -> bool:
        return bool(self.store.get("device_id"))

    def activate(self, code: str, serial: str | None = None) -> dict:
        seed, pub = crypto.generate_device_keys()
        _, enc_pub = crypto.x25519_from_seed(seed)
        info = self.gw.activate(code, serial, pub, enc_pub, self.firmware)
        self.store.put("device_id", info["device_id"])
        self.store.put("seed", base64.b64encode(seed).decode())
        self.store.put("info", info)
        self.store.put("config", info.get("config", {}))
        self.gw.device_id, self.gw.seed = info["device_id"], seed
        self.online = True
        self.sync_gallery(force=True)
        return info

    @property
    def config(self) -> dict:
        return self.store.get("config", {}) or {}

    @property
    def direction_default(self) -> str:
        info = self.store.get("info", {}) or {}
        d = info.get("direction") or "in"
        return "in" if d == "both" else d

    # ------------------------------------------------------------ gallery
    def _load_gallery(self) -> None:
        pkg = self.store.get("gallery_package")
        if not pkg:
            return
        priv, _ = crypto.x25519_from_seed(self.gw.seed)
        data = json.loads(crypto.open_device_package(priv, pkg))
        with self._lock:
            self.gallery = Gallery.from_payload(data)

    def sync_gallery(self, force: bool = False, server_version: int | None = None) -> bool:
        if not force and server_version is not None and server_version == self.gallery.version:
            return False
        res = self.gw.call("GET", "/api/v1/gateway/gallery")
        self.store.put("gallery_package", res["package"])
        self._load_gallery()
        return True

    # ------------------------------------------------------------ decisions
    def _now_iso(self) -> str:
        return datetime.fromtimestamp(self.clock(), tz=timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")

    def _record(self, *, employee_id: str | None, direction: str, method: str, result: str, score=None,
                liveness=None, capture: np.ndarray | None = None) -> str | None:
        event = {"event_id": str(uuid.uuid4()), "employee_id": employee_id, "direction": direction, "method": method,
                 "result": result, "score": None if score is None else round(float(score), 4),
                 "liveness_score": None if liveness is None else round(float(liveness), 4),
                 "model_version": self.provider.model_version, "captured_at": self._now_iso(), "flags": []}
        if capture is not None and self.config.get("capture_suspicious", True) and result in ("pad", "unknown", "review",
                                                                                               "denied"):
            event["capture_jpeg"] = base64.b64encode(imaging.encode_jpeg(capture, 70)).decode()
        try:
            self.store.enqueue(event, self.clock())
        except OutboxFull:
            return None
        return event["event_id"]

    def _ui(self, state: str, code: str | None = None, employee_id: str | None = None, direction: str = "in",
            extra: dict | None = None) -> dict:
        lang = self.gallery.languages.get(employee_id, self.config.get("kiosk_language", "uz")) if employee_id else \
            self.config.get("kiosk_language", "uz")
        name = self.gallery.names.get(employee_id, "") if employee_id else ""
        local = datetime.fromtimestamp(self.clock()).strftime("%H:%M")
        tmpl = MESSAGES.get(state, {}).get(lang) or MESSAGES.get(state, {}).get("uz", "")
        out = {"state": state, "code": code, "message": tmpl.format(name=name, time=local), "name": name,
               "time": local, "direction": direction, "duration_ms": DURATIONS_MS.get(state, 2000),
               "open_gate": False, "offline": not self.online}
        out.update(extra or {})
        return out

    def _debounced(self, employee_id: str, direction: str) -> bool:
        last = self._last_pass.get((employee_id, direction))
        return last is not None and self.clock() - last < self.gallery.debounce_min * 60

    def _open(self, employee_id: str, direction: str) -> None:
        self._last_pass[(employee_id, direction)] = self.clock()
        self.relay.open(int(self.config.get("relay_open_ms", 3000)))

    def attempt(self, frames: list, direction: str | None = None, session: str = "default") -> dict:
        """One recognition attempt from 1–5 frames (spec H.2 states TRM-02 … TRM-12)."""
        direction = direction or self.direction_default
        if self.store.fill_ratio() >= 1.0:
            return self._ui("TRM-16", "T-116", direction=direction)
        try:
            imgs = [imaging.decode(f) if not isinstance(f, np.ndarray) else f for f in frames]
        except Exception:  # noqa: BLE001
            self.camera_ok = False
            return self._ui("TRM-14", "T-114", direction=direction)
        self.camera_ok = True
        faces = [self.provider.detect(i) for i in imgs]
        usable = [(i, f[0]) for i, f in zip(imgs, faces) if len(f) == 1]
        if not usable:
            many = any(len(f) > 1 for f in faces)
            return self._ui("TRM-02", None, direction=direction,
                            extra={"hint": "single_person" if many else "come_closer"})
        imgs_u, faces_u = [u[0] for u in usable], [u[1] for u in usable]
        q = imaging.assess(imgs_u[-1], faces_u[-1].bbox, faces_u[-1].landmarks)
        if q.issues and q.score < 0.5:
            return self._ui("TRM-02", None, direction=direction, extra={"hint": q.issues[0]})
        live, _method = self.provider.liveness(imgs_u, faces_u) if len(imgs_u) > 1 else (None, "single_frame")
        vec = self.provider.embed(imgs_u[-1], faces_u[-1])
        with self._lock:
            g = self.gallery
            emp, best, second = g.match(vec)
        attempt_no = self._attempts.get(session, 0)
        allowed = emp is not None and emp in g.allowed and emp not in g.blocked
        dup = emp is not None and self._debounced(emp, direction)
        d = decide(best_score=best, best_employee=emp, second_score=second, liveness_score=live,
                   thresholds=g.thresholds, liveness_required=g.liveness_required, liveness_min=g.liveness_min,
                   allowed=allowed, duplicate=dup, attempt=attempt_no, direction=direction)
        if d.result == "retry":
            self._attempts[session] = attempt_no + 1
            return self._ui(d.state, d.code, direction=direction)
        self._attempts.pop(session, None)
        event_emp = d.employee_id if d.result in ("accepted", "review", "denied", "duplicate") else None
        ev = self._record(employee_id=event_emp, direction=direction, method="face", result=d.result, score=best,
                          liveness=live, capture=imgs_u[-1])
        if ev is None:
            return self._ui("TRM-16", "T-116", direction=direction)
        if d.open_gate:
            self._open(d.employee_id, direction)
        return self._ui(d.state, d.code, employee_id=event_emp if d.open_gate or d.result == "denied" else None,
                        direction=direction, extra={"open_gate": d.open_gate, "event_id": ev})

    def card_pin(self, card_no: str, pin: str | None, direction: str | None = None) -> dict:
        direction = direction or self.direction_default
        entry = self.gallery.cards.get(card_no.strip())
        if not entry:
            self._record(employee_id=None, direction=direction, method="card_pin", result="unknown")
            return self._ui("TRM-08", "T-208", direction=direction)
        emp, pin_hash = entry
        fails = self.store.get(f"pin_fail:{card_no}", {"n": 0, "until": 0})
        if fails["until"] > self.clock():
            return self._ui("TRM-10", "T-212", direction=direction, extra={"locked": True})
        if pin_hash and not passwords.verify_secret(pin or "", pin_hash):
            fails["n"] += 1
            if fails["n"] >= 3:
                fails = {"n": 0, "until": self.clock() + 15 * 60}
            self.store.put(f"pin_fail:{card_no}", fails)
            return self._ui("TRM-12", "T-212", direction=direction, extra={"pin_error": True})
        self.store.put(f"pin_fail:{card_no}", {"n": 0, "until": 0})
        if emp in self.gallery.blocked or emp not in self.gallery.allowed:
            self._record(employee_id=emp, direction=direction, method="card_pin", result="denied")
            return self._ui("TRM-10", "T-210", employee_id=emp, direction=direction)
        if self._debounced(emp, direction):
            self._record(employee_id=emp, direction=direction, method="card_pin", result="duplicate")
            self._open(emp, direction)
            return self._ui("TRM-07", "T-207", employee_id=emp, direction=direction, extra={"open_gate": True})
        self._record(employee_id=emp, direction=direction, method="card_pin", result="accepted")
        self._open(emp, direction)
        return self._ui("TRM-05" if direction == "in" else "TRM-06", None, employee_id=emp, direction=direction,
                        extra={"open_gate": True})

    def call_help(self, direction: str | None = None) -> dict:
        self.help_requests.append({"at": self._now_iso(), "direction": direction or self.direction_default})
        return self._ui("TRM-13", "T-213", direction=direction or self.direction_default)

    # ------------------------------------------------------------ sync
    def health(self) -> dict:
        total, used, _free = shutil.disk_usage(self.data_dir or ".")
        load = os.getloadavg()[0] if hasattr(os, "getloadavg") else 0
        return {"camera_ok": self.camera_ok, "camera_fps": 25 if self.camera_ok else 0,
                "disk_pct": round(100 * used / total, 1), "load": round(load, 2),
                "outbox_fill_pct": round(100 * self.store.fill_ratio(), 2)}

    def sync_once(self) -> dict:
        """Heartbeat, commands, gallery refresh, outbox upload. Raises TransportError when offline."""
        stats = {"uploaded": 0, "duplicates": 0, "rejected": 0, "commands": 0}
        try:
            hb = self.gw.call("POST", "/api/v1/gateway/heartbeat", {
                "firmware": self.firmware, "health": self.health(), "outbox_size": self.store.pending_count(),
                "gallery_version": self.gallery.version, "applied_config_version": self.store.get("config_version", 0),
                "device_time": self._now_iso()})
        except TransportError:
            self.online = False
            raise
        self.online = True
        if hb.get("config"):
            self.store.put("config", hb["config"])
            self.store.put("config_version", hb["config_version"])
        for cmd in hb.get("commands", []):
            self._run_command(cmd)
            stats["commands"] += 1
            if cmd["type"] == "decommission":
                return stats
        self.sync_gallery(server_version=hb.get("gallery_version"))
        while True:
            batch = self.store.pending(500)
            if not batch:
                break
            res = self.gw.call("POST", "/api/v1/gateway/events", {"events": batch})
            rejected = {r["event_id"]: r["reason"] for r in res.get("rejected", [])}
            self.store.ack([e["event_id"] for e in batch if e["event_id"] not in rejected])
            for eid, reason in rejected.items():
                self.store.reject(eid, reason)
            stats["uploaded"] += res.get("accepted", 0)
            stats["duplicates"] += res.get("duplicates", 0)
            stats["rejected"] += len(rejected)
        self.last_sync = self.clock()
        return stats

    def _run_command(self, cmd: dict) -> None:
        result, status = {}, "acked"
        try:
            t = cmd["type"]
            if t == "apply_config":
                self.store.put("config", cmd["payload"].get("config", {}))
                self.store.put("config_version", cmd["payload"].get("config_version", 0))
            elif t == "open_gate":
                self.relay.open(5000)
            elif t == "gallery_sync":
                self.sync_gallery(force=True)
            elif t == "diagnostic":
                test = cmd["payload"].get("test")
                result = {"test": test, "ok": {"relay": self.relay.test(), "camera": self.camera_ok,
                                               "network": True, "gallery": self.gallery.version > 0}.get(test, False)}
            elif t == "restart":
                result = {"note": "process supervisor restarts the agent"}
            elif t == "ota":
                status, result = "failed", {"error": "OTA is handled by the device OS updater, not the agent"}
            elif t == "decommission":
                self.gw.call("POST", f"/api/v1/gateway/commands/{cmd['id']}/ack", {"status": "acked", "result": {}})
                self.store.wipe()
                self.gallery = Gallery()
                return
        except Exception as e:  # noqa: BLE001 - reported back to the server
            status, result = "failed", {"error": str(e)[:200]}
        self.gw.call("POST", f"/api/v1/gateway/commands/{cmd['id']}/ack", {"status": status, "result": result})

    def run_forever(self, stop: threading.Event | None = None) -> None:
        stop = stop or threading.Event()
        backoff = 5
        while not stop.is_set():
            try:
                self.sync_once()
                backoff = int(self.config.get("heartbeat_s", 30))
            except TransportError as e:
                log.warning("offline: %s", e)
                backoff = min(300, backoff * 2)
            except Exception:  # noqa: BLE001 - never let the sync loop die
                log.exception("sync failed")
            stop.wait(backoff)
