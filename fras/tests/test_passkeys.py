"""Laptop self check-in with passkeys: a software authenticator plays Windows Hello's role."""

import hashlib
import json
import os

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec, padding, rsa

from fras.security import cbor
from fras.security import webauthn as wa
from tests.helpers import FrasTestCase

ORIGIN, RP_ID = "http://localhost:8000", "localhost"


class SoftAuthenticator:
    def __init__(self, alg=wa.ALG_ES256, uv=True, backup=False, origin=ORIGIN, rp_id=RP_ID):
        self.alg, self.uv, self.backup, self.origin, self.rp_id = alg, uv, backup, origin, rp_id
        self.key = ec.generate_private_key(ec.SECP256R1()) if alg == wa.ALG_ES256 else rsa.generate_private_key(65537, 2048)
        self.cred_id = os.urandom(32)
        self.count = 0

    def _flags(self, attested=False):
        f = wa.FLAG_UP | (wa.FLAG_UV if self.uv else 0) | (wa.FLAG_BE | wa.FLAG_BS if self.backup else 0)
        return f | (wa.FLAG_AT if attested else 0)

    def _cose(self):
        pub = self.key.public_key().public_numbers()
        if self.alg == wa.ALG_ES256:
            return {1: 2, 3: -7, -1: 1, -2: pub.x.to_bytes(32, "big"), -3: pub.y.to_bytes(32, "big")}
        return {1: 3, 3: -257, -1: pub.n.to_bytes(256, "big"), -2: pub.e.to_bytes(3, "big")}

    def _client_data(self, kind, challenge):
        return json.dumps({"type": kind, "challenge": challenge, "origin": self.origin, "crossOrigin": False}).encode()

    def register(self, options, label="Ish noutbuki"):
        auth = (hashlib.sha256(self.rp_id.encode()).digest() + bytes([self._flags(True)]) + self.count.to_bytes(4, "big")
                + bytes.fromhex("08987058cadc4b81b6e130de50dcbe96") + len(self.cred_id).to_bytes(2, "big") + self.cred_id
                + cbor.dumps(self._cose()))
        att = cbor.dumps({"fmt": "none", "attStmt": {}, "authData": auth})
        return {"credential_id": wa.b64url(self.cred_id), "client_data_json": wa.b64url(self._client_data("webauthn.create", options["challenge"])),
                "attestation_object": wa.b64url(att), "label": label}

    def assert_(self, options, count_step=1):
        self.count += count_step
        auth = hashlib.sha256(self.rp_id.encode()).digest() + bytes([self._flags()]) + self.count.to_bytes(4, "big")
        cdj = self._client_data("webauthn.get", options["challenge"])
        data = auth + hashlib.sha256(cdj).digest()
        sig = (self.key.sign(data, ec.ECDSA(hashes.SHA256())) if self.alg == wa.ALG_ES256
               else self.key.sign(data, padding.PKCS1v15(), hashes.SHA256()))
        return {"credential_id": wa.b64url(self.cred_id), "client_data_json": wa.b64url(cdj),
                "authenticator_data": wa.b64url(auth), "signature": wa.b64url(sig)}


class PasskeyTests(FrasTestCase):
    def setUp(self):
        super().setUp()
        self.make_org()
        self.emp = self.make_employee("A-2001")
        self.env.add_user("a-2001", "employee", "self", self.emp["id"], employee_id=self.emp["id"])
        self.me = self.env.login("a-2001")

    def policy(self, **kw):
        value = {"enabled": True, "allowed_networks": ["127.0.0.0/8"], "outside_network": "deny", "require_approval": True, **kw}
        r = self.hr.put("/api/v1/settings/self_checkin", {"value": value})
        self.assertEqual(r.status, 200, r)

    def enroll(self, auth, approve=True):
        opts = self.me.post("/api/v1/portal/passkeys/options").json()
        r = self.me.post("/api/v1/portal/passkeys", auth.register(opts))
        self.assertEqual(r.status, 201, r)
        if approve:
            self.assertEqual(self.hr.post(f"/api/v1/passkeys/{r.json()['id']}/approve").status, 200)
        return r.json()

    def checkin(self, auth, direction="in", **kw):
        opts = self.me.post("/api/v1/portal/checkin/options", {"direction": direction})
        self.assertEqual(opts.status, 200, opts)
        return self.me.post("/api/v1/portal/checkin", auth.assert_(opts.json(), **kw)), opts.json()

    def test_disabled_by_default(self):
        r = self.me.post("/api/v1/portal/passkeys/options")
        self.assertEqual(r.json()["error"]["code"], "SELF_CHECKIN_DISABLED")

    def test_register_approve_checkin_and_duplicate(self):
        self.policy()
        auth = SoftAuthenticator()
        cred = self.enroll(auth, approve=False)
        self.assertEqual((cred["status"], cred["authenticator"]), ("pending", "Windows Hello"))
        # not usable until HR approves
        self.assertEqual(self.me.post("/api/v1/portal/checkin/options", {"direction": "in"}).json()["error"]["code"],
                         "NO_ACTIVE_PASSKEY")
        self.assertEqual(self.me.get("/api/v1/passkeys").status, 403)          # employees cannot manage others' keys
        self.assertEqual(self.hr.get("/api/v1/passkeys", query={"status": "pending"}).json()["items"][0]["id"], cred["id"])
        self.hr.post(f"/api/v1/passkeys/{cred['id']}/approve")
        r, _ = self.checkin(auth)
        self.assertEqual(r.json()["result"], "accepted", r)
        ev = self.hr.get("/api/v1/attendance/events").json()["items"][0]
        self.assertEqual((ev["method"], ev["direction"]), ("passkey", "in"))
        r, _ = self.checkin(auth)
        self.assertEqual(r.json()["result"], "duplicate")
        r, _ = self.checkin(auth, "out")
        self.assertEqual(r.json()["result"], "accepted")

    def test_rs256_windows_hello_key(self):
        self.policy(require_approval=False)
        auth = SoftAuthenticator(alg=wa.ALG_RS256)
        self.assertEqual(self.enroll(auth, approve=False)["status"], "active")
        self.assertEqual(self.checkin(auth)[0].json()["result"], "accepted")

    def test_user_verification_required(self):
        self.policy()
        auth = SoftAuthenticator(uv=False)          # touch only, Hello did not verify the person
        opts = self.me.post("/api/v1/portal/passkeys/options").json()
        r = self.me.post("/api/v1/portal/passkeys", auth.register(opts))
        self.assertEqual(r.json()["error"]["code"], "WEBAUTHN_UV_REQUIRED")

    def test_synced_passkey_refused(self):
        self.policy()
        opts = self.me.post("/api/v1/portal/passkeys/options").json()
        r = self.me.post("/api/v1/portal/passkeys", SoftAuthenticator(backup=True).register(opts))
        self.assertEqual(r.json()["error"]["code"], "PASSKEY_SYNCED_NOT_ALLOWED")

    def test_wrong_origin_and_rp(self):
        self.policy()
        opts = self.me.post("/api/v1/portal/passkeys/options").json()
        r = self.me.post("/api/v1/portal/passkeys", SoftAuthenticator(origin="https://evil.example").register(opts))
        self.assertEqual(r.json()["error"]["code"], "WEBAUTHN_ORIGIN")
        opts = self.me.post("/api/v1/portal/passkeys/options").json()
        r = self.me.post("/api/v1/portal/passkeys", SoftAuthenticator(rp_id="evil.example").register(opts))
        self.assertEqual(r.json()["error"]["code"], "WEBAUTHN_RP")

    def test_replay_and_forged_signature(self):
        self.policy()
        auth = SoftAuthenticator()
        self.enroll(auth)
        r, opts = self.checkin(auth)
        self.assertEqual(r.json()["result"], "accepted")
        again = self.me.post("/api/v1/portal/checkin", auth.assert_(opts))            # same challenge
        self.assertEqual(again.json()["error"]["code"], "WEBAUTHN_CHALLENGE")
        opts = self.me.post("/api/v1/portal/checkin/options", {"direction": "out"}).json()
        body = auth.assert_(opts)
        body["signature"] = wa.b64url(SoftAuthenticator().key.sign(b"x", ec.ECDSA(hashes.SHA256())))
        self.assertEqual(self.me.post("/api/v1/portal/checkin", body).json()["error"]["code"], "WEBAUTHN_SIGNATURE")

    def test_cloned_key_is_blocked(self):
        self.policy()
        auth = SoftAuthenticator()
        cred = self.enroll(auth)
        self.checkin(auth, count_step=5)
        r, _ = self.checkin(auth, "out", count_step=-3)       # counter went backwards
        self.assertEqual(r.json()["error"]["code"], "PASSKEY_CLONED")
        items = self.hr.get("/api/v1/passkeys", query={"status": "revoked"}).json()["items"]
        self.assertEqual(items[0]["id"], cred["id"])
        with self.env.db.tx() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) AS n FROM security_alerts WHERE kind = 'passkey_clone'").fetchone()["n"], 1)

    def test_outside_office_network(self):
        self.policy()
        auth = SoftAuthenticator()
        self.enroll(auth)
        self.policy(allowed_networks=["10.20.0.0/16"])          # we are on 127.0.0.1 = "home"
        r, _ = self.checkin(auth)
        self.assertEqual(r.json()["result"], "denied")
        self.policy(allowed_networks=["10.20.0.0/16"], outside_network="review")
        r, _ = self.checkin(auth, "out")
        self.assertEqual(r.json()["result"], "review")
        # registering a new laptop from outside is refused
        self.assertEqual(self.me.post("/api/v1/portal/passkeys/options").json()["error"]["code"], "OUTSIDE_OFFICE_NETWORK")

    def test_invalid_network_setting(self):
        r = self.hr.put("/api/v1/settings/self_checkin", {"value": {"allowed_networks": ["10.0.0.0/33"]}})
        self.assertEqual(r.status, 422)

    def test_employee_removes_own_laptop(self):
        self.policy()
        auth = SoftAuthenticator()
        cred = self.enroll(auth)
        self.assertEqual(self.me.delete(f"/api/v1/portal/passkeys/{cred['id']}").status, 200)
        self.assertEqual(self.me.post("/api/v1/portal/checkin/options", {"direction": "in"}).json()["error"]["code"],
                         "NO_ACTIVE_PASSKEY")
