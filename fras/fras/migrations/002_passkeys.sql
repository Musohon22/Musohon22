-- Self check-in from a laptop with a passkey (Windows Hello / platform authenticator).
CREATE TABLE webauthn_credentials (
    id              TEXT PRIMARY KEY,
    tenant_id       TEXT NOT NULL REFERENCES tenants(id),
    user_id         TEXT NOT NULL REFERENCES users(id),
    employee_id     TEXT NOT NULL REFERENCES employees(id),
    credential_id   TEXT NOT NULL UNIQUE,          -- base64url, as the browser reports it
    alg             INTEGER NOT NULL,              -- COSE algorithm (-7 ES256, -257 RS256, -8 EdDSA)
    public_key      BLOB NOT NULL,                 -- SubjectPublicKeyInfo DER
    sign_count      INTEGER NOT NULL DEFAULT 0,
    aaguid          TEXT,
    label           TEXT NOT NULL,
    backup_eligible INTEGER NOT NULL DEFAULT 0,    -- 1 = synced passkey (could live on many devices)
    status          TEXT NOT NULL,                 -- pending | active | revoked
    created_ip      TEXT,
    created_at      TEXT NOT NULL,
    approved_by     TEXT,
    approved_at     TEXT,
    last_used_at    TEXT,
    revoked_at      TEXT,
    revoked_by      TEXT,
    revoke_reason   TEXT
);
CREATE INDEX ix_webauthn_user ON webauthn_credentials(tenant_id, user_id);

CREATE TABLE webauthn_challenges (
    id          TEXT PRIMARY KEY,
    tenant_id   TEXT NOT NULL,
    user_id     TEXT NOT NULL,
    kind        TEXT NOT NULL,                     -- register | checkin:in | checkin:out
    challenge   TEXT NOT NULL UNIQUE,
    expires_at  TEXT NOT NULL,
    used_at     TEXT
);
