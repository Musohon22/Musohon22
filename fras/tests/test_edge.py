"""Edge agent: activation, local recognition, gate, offline outbox, resync without duplicates, commands."""

import json
import sys
import tempfile
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "edge"))

from fras.biometrics.providers import DevProvider  # noqa: E402
from fras_edge.agent import Agent, SimulatedRelay  # noqa: E402
from fras_edge.store import Store  # noqa: E402
from fras_edge.transport import Gateway, TransportError  # noqa: E402
from tests.helpers import Client, FrasTestCase  # noqa: E402
from tests.test_flows import frames_for  # noqa: E402


class AsgiTransport:
    """Sends device requests straight into the ASGI app; `down=True` simulates a network outage."""

    def __init__(self, app):
        self.client = Client(app)
        self.down = False
        self.drop_response = False

    def send(self, method, path, body, headers):
        if self.down:
            raise TransportError(None, "network down")
        r = self.client.request(method, path, raw=body if body else None, headers=headers)
        if self.drop_response:
            self.drop_response = False
            raise TransportError(None, "response lost")
        return r.status, r.json() if r.body else {}


class EdgeTests(FrasTestCase):
    def setUp(self):
        super().setUp()
        self.make_org()
        self.make_shift()
        self.emp = self.make_employee("A-1001", card_no="CARD-1", pin="4826")
        self.other = self.make_employee("A-1002")
        pdf = "JVBERi0xLjQgdGVzdA=="
        self.hr.post("/api/v1/biometrics/consents", {"employee_id": self.emp["id"], "decision": "granted",
                                                     "method": "paper_scan", "document": pdf, "explained": True})
        r = self.hr.post("/api/v1/biometrics/enrollments", {"employee_id": self.emp["id"], "frames": frames_for(11)})
        self.assertEqual(r.status, 201, r)
        reg = self.admin.post("/api/v1/devices", {"name": "T-edge", "type": "terminal", "site_id": self.site_id,
                                                  "access_point_id": self.ap_id, "direction": "both"})
        self.code = reg.json()["activation_code"]
        self.dir = tempfile.mkdtemp()
        self.transport = AsgiTransport(self.env.app)
        self.relay = SimulatedRelay()
        self.agent = Agent(Store(f"{self.dir}/edge.db"), Gateway(self.transport), DevProvider(), self.relay,
                           data_dir=self.dir)
        self.agent.activate(self.code, "SN-EDGE")

    def server_events(self):
        return self.hr.get("/api/v1/attendance/events", query={"from": date.today().isoformat()}).json()

    def test_recognize_open_gate_and_sync(self):
        self.assertEqual(len(self.agent.gallery.allowed), 2)
        res = self.agent.attempt(frames_for(11), "in")
        self.assertEqual(res["state"], "TRM-05", res)
        self.assertTrue(res["open_gate"])
        self.assertTrue(res["name"].endswith("."))                  # first name + initial only
        self.assertEqual(len(self.relay.openings), 1)
        stats = self.agent.sync_once()
        self.assertEqual(stats["uploaded"], 1)
        ev = self.server_events()["items"][0]
        self.assertEqual((ev["employee_id"], ev["result"], ev["method"]), (self.emp["id"], "accepted", "face"))
        # second pass within debounce → TRM-07, gate still opens, logged as duplicate
        again = self.agent.attempt(frames_for(11), "in")
        self.assertEqual(again["state"], "TRM-07")

    def test_photo_and_unknown_person(self):
        pad = self.agent.attempt(frames_for(11, still=True), "in")
        self.assertEqual(pad["state"], "TRM-09")
        self.assertFalse(pad["open_gate"])
        unk = self.agent.attempt(frames_for(999), "in")
        self.assertEqual(unk["state"], "TRM-08")
        self.assertEqual(self.relay.openings, [])
        self.agent.sync_once()
        results = sorted(e["result"] for e in self.server_events()["items"])
        self.assertEqual(results, ["pad", "unknown"])
        self.assertTrue(all(e["has_capture"] for e in self.server_events()["items"]))   # suspicious → capture kept

    def test_offline_then_resync_without_duplicates(self):
        self.transport.down = True
        with self.assertRaises(TransportError):
            self.agent.sync_once()
        self.assertFalse(self.agent.online)
        self.assertEqual(self.agent.attempt(frames_for(11), "in")["state"], "TRM-05")   # still works offline
        self.assertEqual(self.agent.card_pin("CARD-1", "4826", "out")["state"], "TRM-06")
        self.assertEqual(self.agent.store.pending_count(), 2)
        self.transport.down = False
        self.transport.drop_response = True       # server stores the batch but the ACK is lost
        with self.assertRaises(TransportError):
            self.agent.sync_once()
        self.assertEqual(self.agent.store.pending_count(), 2)   # not acked → will be resent
        stats = self.agent.sync_once()
        self.assertEqual(self.agent.store.pending_count(), 0)
        self.assertEqual(self.server_events()["total"], 2)       # idempotent: nothing stored twice
        self.assertGreaterEqual(stats["duplicates"] + stats["uploaded"], 2)

    def test_card_pin_and_lockout(self):
        self.assertEqual(self.agent.card_pin("CARD-1", "0000")["state"], "TRM-12")
        self.agent.card_pin("CARD-1", "0001")
        self.agent.card_pin("CARD-1", "0002")
        self.assertEqual(self.agent.card_pin("CARD-1", "4826")["state"], "TRM-10")   # locked 15 min
        self.assertEqual(self.agent.card_pin("NOPE", "1")["state"], "TRM-08")

    def test_deactivation_reaches_terminal(self):
        self.hr.post(f"/api/v1/employees/{self.emp['id']}/deactivate", {"effective_date": date.today().isoformat(),
                                                                        "reason": "dismissed"})
        self.agent.sync_once()
        res = self.agent.attempt(frames_for(11), "in")
        self.assertIn(res["state"], ("TRM-08", "TRM-10"))
        self.assertFalse(res["open_gate"])

    def test_commands_config_and_decommission(self):
        r = self.admin.patch(f"/api/v1/devices/{self.agent.gw.device_id}", {"config_override": {"relay_open_ms": 4500}})
        self.assertEqual(r.status, 200, r)
        self.admin.post(f"/api/v1/devices/{self.agent.gw.device_id}/commands", {"type": "diagnostic", "test": "relay"})
        self.agent.sync_once()
        self.assertEqual(self.agent.config["relay_open_ms"], 4500)
        dev = self.admin.get(f"/api/v1/devices/{self.agent.gw.device_id}").json()
        self.assertFalse(dev["config_drift"])
        self.assertTrue(all(c["status"] == "acked" for c in dev["commands"]))
        self.admin.post(f"/api/v1/devices/{self.agent.gw.device_id}/decommission", {"confirm_name": "T-edge"})
        with self.assertRaises(TransportError):
            self.agent.sync_once()      # decommissioned devices are refused
        self.assertEqual(json.dumps(self.agent.store.get("device_id")), json.dumps(self.agent.gw.device_id))
