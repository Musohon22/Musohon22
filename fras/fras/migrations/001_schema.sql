-- FRAS schema v1. SQLite dialect kept close to standard SQL so it can be
-- ported to PostgreSQL (see docs/ARCHITECTURE.md). All tenant data carries
-- tenant_id; every query in the repository layer filters by it.

PRAGMA foreign_keys = ON;

CREATE TABLE sys_flags (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
INSERT INTO sys_flags(key, value) VALUES ('retention_purge', '0');

-- ---------------------------------------------------------------- platform
CREATE TABLE plans (
    code              TEXT PRIMARY KEY,
    name              TEXT NOT NULL,
    version           INTEGER NOT NULL DEFAULT 1,
    price_model       TEXT NOT NULL,            -- flat | per_employee | contract
    price_cents       INTEGER NOT NULL,         -- flat price or per-employee price (annual billing)
    min_monthly_cents INTEGER NOT NULL DEFAULT 0,
    monthly_markup_pct INTEGER NOT NULL DEFAULT 15,
    limits            TEXT NOT NULL,            -- JSON: employees, sites, devices, admins, retention_days...
    features          TEXT NOT NULL,            -- JSON list of feature flags
    active            INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE tenants (
    id          TEXT PRIMARY KEY,
    slug        TEXT NOT NULL UNIQUE,
    name        TEXT NOT NULL,
    legal_name  TEXT,
    tin         TEXT,
    status      TEXT NOT NULL DEFAULT 'active',  -- active | archived
    plan_code   TEXT NOT NULL REFERENCES plans(code),
    deployment  TEXT NOT NULL DEFAULT 'cloud',   -- cloud | onprem
    dek_wrapped BLOB NOT NULL,                    -- tenant data key wrapped by master key
    created_at  TEXT NOT NULL
);

CREATE TABLE subscriptions (
    id             TEXT PRIMARY KEY,
    tenant_id      TEXT NOT NULL REFERENCES tenants(id),
    plan_code      TEXT NOT NULL REFERENCES plans(code),
    status         TEXT NOT NULL,     -- trialing | active | past_due | restricted | suspended | cancelled | archived
    billing_cycle  TEXT NOT NULL DEFAULT 'annual',  -- monthly | annual
    discount_pct   INTEGER NOT NULL DEFAULT 0,
    period_start   TEXT NOT NULL,
    period_end     TEXT NOT NULL,
    trial_ends_at  TEXT,
    payment_pending_until TEXT,
    cancel_at      TEXT,
    cancel_reason  TEXT,
    created_at     TEXT NOT NULL,
    updated_at     TEXT NOT NULL
);
CREATE INDEX ix_subscriptions_tenant ON subscriptions(tenant_id);

CREATE TABLE invoices (
    id              TEXT PRIMARY KEY,
    tenant_id       TEXT NOT NULL REFERENCES tenants(id),
    subscription_id TEXT REFERENCES subscriptions(id),
    number          TEXT NOT NULL UNIQUE,
    period_start    TEXT NOT NULL,
    period_end      TEXT NOT NULL,
    lines           TEXT NOT NULL,     -- JSON
    amount_cents    INTEGER NOT NULL,
    currency        TEXT NOT NULL DEFAULT 'USD',
    status          TEXT NOT NULL,     -- issued | paid | overdue | void
    issued_at       TEXT NOT NULL,
    due_at          TEXT NOT NULL,
    paid_at         TEXT
);
CREATE INDEX ix_invoices_tenant ON invoices(tenant_id, status);

CREATE TABLE payments (
    id           TEXT PRIMARY KEY,
    tenant_id    TEXT NOT NULL REFERENCES tenants(id),
    invoice_id   TEXT NOT NULL REFERENCES invoices(id),
    amount_cents INTEGER NOT NULL,
    method       TEXT NOT NULL,
    reference    TEXT,
    recorded_by  TEXT,
    created_at   TEXT NOT NULL
);

CREATE TABLE platform_users (
    id            TEXT PRIMARY KEY,
    email         TEXT NOT NULL UNIQUE,
    name          TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    role          TEXT NOT NULL,   -- owner | billing | success | support | security
    totp_secret   TEXT,
    mfa_enabled   INTEGER NOT NULL DEFAULT 0,
    status        TEXT NOT NULL DEFAULT 'active',
    created_at    TEXT NOT NULL
);

CREATE TABLE support_tickets (
    id          TEXT PRIMARY KEY,
    tenant_id   TEXT NOT NULL REFERENCES tenants(id),
    subject     TEXT NOT NULL,
    body        TEXT NOT NULL,
    priority    TEXT NOT NULL DEFAULT 'normal',  -- low | normal | high | critical
    status      TEXT NOT NULL DEFAULT 'open',    -- open | in_progress | resolved | closed
    channel     TEXT NOT NULL DEFAULT 'portal',
    created_by  TEXT,
    assignee    TEXT,
    sla_due_at  TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE TABLE cancellation_feedback (
    id         TEXT PRIMARY KEY,
    tenant_id  TEXT NOT NULL REFERENCES tenants(id),
    reason     TEXT NOT NULL,
    comment    TEXT,
    created_at TEXT NOT NULL
);

-- ---------------------------------------------------------------- org structure
CREATE TABLE sites (
    id         TEXT PRIMARY KEY,
    tenant_id  TEXT NOT NULL REFERENCES tenants(id),
    code       TEXT NOT NULL,
    name       TEXT NOT NULL,
    timezone   TEXT NOT NULL DEFAULT 'Asia/Tashkent',
    address    TEXT,
    status     TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL,
    UNIQUE (tenant_id, code)
);

CREATE TABLE buildings (
    id         TEXT PRIMARY KEY,
    tenant_id  TEXT NOT NULL REFERENCES tenants(id),
    site_id    TEXT NOT NULL REFERENCES sites(id),
    name       TEXT NOT NULL,
    status     TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL
);

CREATE TABLE zones (
    id          TEXT PRIMARY KEY,
    tenant_id   TEXT NOT NULL REFERENCES tenants(id),
    building_id TEXT NOT NULL REFERENCES buildings(id),
    name        TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'active',
    created_at  TEXT NOT NULL
);

CREATE TABLE access_points (
    id         TEXT PRIMARY KEY,
    tenant_id  TEXT NOT NULL REFERENCES tenants(id),
    site_id    TEXT NOT NULL REFERENCES sites(id),
    zone_id    TEXT REFERENCES zones(id),
    name       TEXT NOT NULL,
    direction  TEXT NOT NULL DEFAULT 'both',  -- in | out | both
    status     TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL
);

CREATE TABLE departments (
    id         TEXT PRIMARY KEY,
    tenant_id  TEXT NOT NULL REFERENCES tenants(id),
    site_id    TEXT NOT NULL REFERENCES sites(id),
    parent_id  TEXT REFERENCES departments(id),
    code       TEXT NOT NULL,
    name       TEXT NOT NULL,
    status     TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL,
    UNIQUE (tenant_id, site_id, code)
);

CREATE TABLE positions (
    id         TEXT PRIMARY KEY,
    tenant_id  TEXT NOT NULL REFERENCES tenants(id),
    name       TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (tenant_id, name)
);

-- ---------------------------------------------------------------- people
CREATE TABLE employees (
    id               TEXT PRIMARY KEY,
    tenant_id        TEXT NOT NULL REFERENCES tenants(id),
    site_id          TEXT NOT NULL REFERENCES sites(id),
    personnel_no     TEXT NOT NULL,
    last_name        TEXT NOT NULL,
    first_name       TEXT NOT NULL,
    middle_name      TEXT,
    pinfl_enc        BLOB,
    pinfl_hash       TEXT,           -- keyed hash for duplicate detection
    pinfl_last4      TEXT,
    birth_date       TEXT,
    phone            TEXT,
    department_id    TEXT NOT NULL REFERENCES departments(id),
    position_id      TEXT REFERENCES positions(id),
    team             TEXT,           -- shift brigade, e.g. "A"
    hire_date        TEXT NOT NULL,
    status           TEXT NOT NULL DEFAULT 'active',   -- active | deactivated
    deactivated_at   TEXT,
    deactivation_reason TEXT,
    language         TEXT NOT NULL DEFAULT 'uz',
    card_no          TEXT,
    pin_hash         TEXT,
    biometric_status TEXT NOT NULL DEFAULT 'none',     -- none | active | review | revoked | declined
    version          INTEGER NOT NULL DEFAULT 1,
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL,
    UNIQUE (tenant_id, site_id, personnel_no)
);
CREATE UNIQUE INDEX ux_employees_card ON employees(tenant_id, card_no) WHERE card_no IS NOT NULL;
CREATE INDEX ix_employees_dept ON employees(tenant_id, department_id, status);
CREATE INDEX ix_employees_pinfl ON employees(tenant_id, pinfl_hash);

CREATE TABLE employment_assignments (
    id            TEXT PRIMARY KEY,
    tenant_id     TEXT NOT NULL REFERENCES tenants(id),
    employee_id   TEXT NOT NULL REFERENCES employees(id),
    department_id TEXT NOT NULL REFERENCES departments(id),
    position_id   TEXT REFERENCES positions(id),
    team          TEXT,
    valid_from    TEXT NOT NULL,
    valid_to      TEXT,
    created_by    TEXT,
    created_at    TEXT NOT NULL
);
CREATE INDEX ix_assign_emp ON employment_assignments(employee_id, valid_from);

CREATE TABLE employee_access_points (
    tenant_id       TEXT NOT NULL REFERENCES tenants(id),
    employee_id     TEXT NOT NULL REFERENCES employees(id),
    access_point_id TEXT NOT NULL REFERENCES access_points(id),
    PRIMARY KEY (employee_id, access_point_id)
);

CREATE TABLE duplicate_candidates (
    id            TEXT PRIMARY KEY,
    tenant_id     TEXT NOT NULL REFERENCES tenants(id),
    employee_a    TEXT NOT NULL REFERENCES employees(id),
    employee_b    TEXT NOT NULL REFERENCES employees(id),
    reason        TEXT NOT NULL,    -- pinfl | name_birth | face
    score         REAL,
    status        TEXT NOT NULL DEFAULT 'open',   -- open | merged | distinct
    decided_by    TEXT,
    decided_at    TEXT,
    created_at    TEXT NOT NULL,
    UNIQUE (tenant_id, employee_a, employee_b, reason)
);

CREATE TABLE import_batches (
    id          TEXT PRIMARY KEY,
    tenant_id   TEXT NOT NULL REFERENCES tenants(id),
    kind        TEXT NOT NULL,
    filename    TEXT NOT NULL,
    file_hash   TEXT NOT NULL,
    status      TEXT NOT NULL,          -- preview | applied | failed
    summary     TEXT NOT NULL,          -- JSON
    rows        TEXT NOT NULL,          -- JSON preview rows
    created_by  TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    applied_at  TEXT
);

-- ---------------------------------------------------------------- biometrics
CREATE TABLE biometric_consents (
    id             TEXT PRIMARY KEY,
    tenant_id      TEXT NOT NULL REFERENCES tenants(id),
    employee_id    TEXT NOT NULL REFERENCES employees(id),
    decision       TEXT NOT NULL,     -- granted | declined | withdrawn
    policy_version TEXT NOT NULL,
    method         TEXT NOT NULL,     -- paper_scan | e_signature | portal
    document_hash  TEXT,
    recorded_by    TEXT NOT NULL,
    created_at     TEXT NOT NULL
);
CREATE INDEX ix_consents_emp ON biometric_consents(employee_id, created_at);

CREATE TABLE biometric_profiles (
    id              TEXT PRIMARY KEY,
    tenant_id       TEXT NOT NULL REFERENCES tenants(id),
    employee_id     TEXT NOT NULL REFERENCES employees(id),
    status          TEXT NOT NULL,     -- active | review | revoked
    template_enc    BLOB,              -- AES-GCM(tenant DEK); NULL after revoke (crypto-erase)
    template_nonce  BLOB,
    model_version   TEXT NOT NULL,
    quality_score   REAL NOT NULL,
    liveness_score  REAL,
    frames          INTEGER NOT NULL,
    gallery_version INTEGER NOT NULL,
    created_by      TEXT NOT NULL,
    created_at      TEXT NOT NULL,
    revoked_at      TEXT,
    revoke_reason   TEXT
);
CREATE INDEX ix_bioprof_emp ON biometric_profiles(tenant_id, employee_id, status);

CREATE TABLE biometric_reviews (
    id                 TEXT PRIMARY KEY,
    tenant_id          TEXT NOT NULL REFERENCES tenants(id),
    profile_id         TEXT NOT NULL REFERENCES biometric_profiles(id),
    matched_profile_id TEXT NOT NULL REFERENCES biometric_profiles(id),
    score              REAL NOT NULL,
    status             TEXT NOT NULL DEFAULT 'open',   -- open | same_person | different
    comment            TEXT,
    decided_by         TEXT,
    decided_at         TEXT,
    created_at         TEXT NOT NULL
);

CREATE TABLE gallery_versions (
    tenant_id  TEXT PRIMARY KEY REFERENCES tenants(id),
    version    INTEGER NOT NULL,
    updated_at TEXT NOT NULL
);

-- ---------------------------------------------------------------- devices
CREATE TABLE device_groups (
    id             TEXT PRIMARY KEY,
    tenant_id      TEXT NOT NULL REFERENCES tenants(id),
    name           TEXT NOT NULL,
    config         TEXT NOT NULL,     -- JSON profile
    config_version INTEGER NOT NULL DEFAULT 1,
    created_at     TEXT NOT NULL,
    UNIQUE (tenant_id, name)
);

CREATE TABLE devices (
    id                    TEXT PRIMARY KEY,
    tenant_id             TEXT NOT NULL REFERENCES tenants(id),
    site_id               TEXT NOT NULL REFERENCES sites(id),
    access_point_id       TEXT REFERENCES access_points(id),
    group_id              TEXT REFERENCES device_groups(id),
    name                  TEXT NOT NULL,
    type                  TEXT NOT NULL,   -- terminal | camera | controller | site_server
    direction             TEXT NOT NULL DEFAULT 'in',
    serial                TEXT,
    status                TEXT NOT NULL DEFAULT 'pending',  -- pending | online | degraded | offline | decommissioned
    public_key            BLOB,           -- Ed25519 raw public key (request signatures)
    enc_public_key        BLOB,           -- X25519 raw public key (gallery packages are sealed to it)
    activation_code_hash  TEXT,
    activation_expires_at TEXT,
    firmware              TEXT,
    config_override       TEXT NOT NULL DEFAULT '{}',
    config_version        INTEGER NOT NULL DEFAULT 0,
    applied_config_version INTEGER NOT NULL DEFAULT 0,
    gallery_version       INTEGER NOT NULL DEFAULT 0,
    last_seen_at          TEXT,
    last_acked_seq        INTEGER NOT NULL DEFAULT 0,
    outbox_size           INTEGER NOT NULL DEFAULT 0,
    clock_skew_ms         INTEGER,
    health                TEXT NOT NULL DEFAULT '{}',
    offline_notified_at   TEXT,
    created_at            TEXT NOT NULL
);
CREATE UNIQUE INDEX ux_devices_serial ON devices(tenant_id, serial) WHERE serial IS NOT NULL;

CREATE TABLE device_commands (
    id         TEXT PRIMARY KEY,
    tenant_id  TEXT NOT NULL REFERENCES tenants(id),
    device_id  TEXT NOT NULL REFERENCES devices(id),
    type       TEXT NOT NULL,   -- restart | apply_config | diagnostic | open_gate | decommission | gallery_sync
    payload    TEXT NOT NULL DEFAULT '{}',
    reason     TEXT,
    status     TEXT NOT NULL DEFAULT 'queued',  -- queued | sent | acked | failed
    result     TEXT,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    sent_at    TEXT,
    acked_at   TEXT
);
CREATE INDEX ix_devcmd ON device_commands(device_id, status);

CREATE TABLE firmware_releases (
    id         TEXT PRIMARY KEY,
    tenant_id  TEXT NOT NULL REFERENCES tenants(id),
    version    TEXT NOT NULL,
    sha256     TEXT NOT NULL,
    notes      TEXT,
    created_at TEXT NOT NULL,
    UNIQUE (tenant_id, version)
);

CREATE TABLE firmware_rollouts (
    id          TEXT PRIMARY KEY,
    tenant_id   TEXT NOT NULL REFERENCES tenants(id),
    release_id  TEXT NOT NULL REFERENCES firmware_releases(id),
    group_id    TEXT NOT NULL REFERENCES device_groups(id),
    stage_pct   INTEGER NOT NULL DEFAULT 5,
    status      TEXT NOT NULL DEFAULT 'running',  -- running | paused | completed | rolled_back
    window_from TEXT NOT NULL,
    window_to   TEXT NOT NULL,
    created_by  TEXT NOT NULL,
    created_at  TEXT NOT NULL
);

-- ---------------------------------------------------------------- attendance
-- Raw events are append-only: see triggers below.
CREATE TABLE attendance_events (
    id              TEXT PRIMARY KEY,      -- event_id generated on the device (UUIDv7)
    tenant_id       TEXT NOT NULL REFERENCES tenants(id),
    device_id       TEXT REFERENCES devices(id),
    device_seq      INTEGER,
    employee_id     TEXT REFERENCES employees(id),
    access_point_id TEXT REFERENCES access_points(id),
    site_id         TEXT NOT NULL REFERENCES sites(id),
    direction       TEXT NOT NULL,          -- in | out
    method          TEXT NOT NULL,          -- face | card_pin | qr | manual | guard_override
    result          TEXT NOT NULL,          -- accepted | denied | unknown | pad | duplicate | review
    score           REAL,
    liveness_score  REAL,
    model_version   TEXT,
    captured_at     TEXT NOT NULL,          -- UTC, device clock
    received_at     TEXT NOT NULL,          -- UTC, server clock
    clock_suspect   INTEGER NOT NULL DEFAULT 0,
    late_arrival    INTEGER NOT NULL DEFAULT 0, -- arrived from offline buffer (> 2 min after capture)
    flags           TEXT NOT NULL DEFAULT '[]',
    capture_ref     TEXT,                   -- encrypted capture for suspicious events
    signature       TEXT,
    UNIQUE (device_id, device_seq)
);
CREATE INDEX ix_events_emp_time ON attendance_events(tenant_id, employee_id, captured_at);
CREATE INDEX ix_events_time ON attendance_events(tenant_id, captured_at);

CREATE TRIGGER trg_events_no_update BEFORE UPDATE ON attendance_events
BEGIN
    SELECT RAISE(ABORT, 'attendance_events are append-only');
END;
CREATE TRIGGER trg_events_no_delete BEFORE DELETE ON attendance_events
WHEN (SELECT value FROM sys_flags WHERE key = 'retention_purge') <> '1'
BEGIN
    SELECT RAISE(ABORT, 'attendance_events are append-only');
END;

CREATE TABLE event_reviews (
    id         TEXT PRIMARY KEY,
    tenant_id  TEXT NOT NULL REFERENCES tenants(id),
    event_id   TEXT NOT NULL UNIQUE REFERENCES attendance_events(id),
    decision   TEXT NOT NULL,     -- verified | rejected
    comment    TEXT,
    decided_by TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE capture_access_log (
    id         TEXT PRIMARY KEY,
    tenant_id  TEXT NOT NULL REFERENCES tenants(id),
    event_id   TEXT NOT NULL REFERENCES attendance_events(id),
    user_id    TEXT NOT NULL,
    reason     TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE shift_templates (
    id                  TEXT PRIMARY KEY,
    tenant_id           TEXT NOT NULL REFERENCES tenants(id),
    code                TEXT NOT NULL,
    version             INTEGER NOT NULL,
    valid_from          TEXT NOT NULL,
    name                TEXT NOT NULL,
    start_time          TEXT NOT NULL,   -- HH:MM
    end_time            TEXT NOT NULL,
    crosses_midnight    INTEGER NOT NULL,
    breaks              TEXT NOT NULL DEFAULT '[]',  -- JSON [{start,end,paid}|{floating_min,paid}]
    window_before_min   INTEGER NOT NULL DEFAULT 120,
    window_after_min    INTEGER NOT NULL DEFAULT 240,
    grace_min           INTEGER NOT NULL DEFAULT 5,
    early_leave_min     INTEGER NOT NULL DEFAULT 5,
    overtime_min        INTEGER NOT NULL DEFAULT 30,
    overtime_round_min  INTEGER NOT NULL DEFAULT 15,
    overtime_requires_approval INTEGER NOT NULL DEFAULT 0,
    count_early_arrival INTEGER NOT NULL DEFAULT 0,
    color               TEXT NOT NULL DEFAULT 'blue',
    status              TEXT NOT NULL DEFAULT 'active',
    created_by          TEXT NOT NULL,
    created_at          TEXT NOT NULL,
    UNIQUE (tenant_id, code, version)
);

CREATE TABLE rotations (
    id         TEXT PRIMARY KEY,
    tenant_id  TEXT NOT NULL REFERENCES tenants(id),
    name       TEXT NOT NULL,
    pattern    TEXT NOT NULL,     -- JSON list of shift codes or "OFF"
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE shift_assignments (
    id          TEXT PRIMARY KEY,
    tenant_id   TEXT NOT NULL REFERENCES tenants(id),
    employee_id TEXT NOT NULL REFERENCES employees(id),
    work_date   TEXT NOT NULL,
    shift_code  TEXT,               -- NULL = day off
    source      TEXT NOT NULL,      -- manual | rotation | bulk | import
    batch_id    TEXT,
    created_by  TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    UNIQUE (tenant_id, employee_id, work_date)
);
CREATE INDEX ix_assign_date ON shift_assignments(tenant_id, work_date);

CREATE TABLE calendar_days (
    id         TEXT PRIMARY KEY,
    tenant_id  TEXT NOT NULL REFERENCES tenants(id),
    site_id    TEXT NOT NULL REFERENCES sites(id),
    day        TEXT NOT NULL,
    kind       TEXT NOT NULL,    -- holiday | transfer_workday | exception
    name       TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (tenant_id, site_id, day)
);

CREATE TABLE leave_requests (
    id               TEXT PRIMARY KEY,
    tenant_id        TEXT NOT NULL REFERENCES tenants(id),
    employee_id      TEXT NOT NULL REFERENCES employees(id),
    type             TEXT NOT NULL,     -- vacation | sick | business_trip | unpaid | permission
    start_date       TEXT NOT NULL,
    end_date         TEXT NOT NULL,
    start_time       TEXT,
    end_time         TEXT,
    reason           TEXT NOT NULL,
    status           TEXT NOT NULL DEFAULT 'pending',  -- pending | approved | rejected | cancelled
    requested_by     TEXT NOT NULL,
    decided_by       TEXT,
    decided_at       TEXT,
    decision_comment TEXT,
    created_at       TEXT NOT NULL
);
CREATE INDEX ix_leave_emp ON leave_requests(tenant_id, employee_id, start_date);

CREATE TABLE corrections (
    id               TEXT PRIMARY KEY,
    tenant_id        TEXT NOT NULL REFERENCES tenants(id),
    employee_id      TEXT NOT NULL REFERENCES employees(id),
    work_date        TEXT NOT NULL,
    kind             TEXT NOT NULL,   -- add_event | void_event | change_time | set_day_status
    event_id         TEXT REFERENCES attendance_events(id),
    new_time         TEXT,            -- UTC ISO
    direction        TEXT,
    day_status       TEXT,
    reason_code      TEXT NOT NULL,
    comment          TEXT NOT NULL,
    source           TEXT NOT NULL DEFAULT 'hr',  -- hr | employee_dispute | bulk
    status           TEXT NOT NULL DEFAULT 'pending',  -- pending | approved | rejected
    requested_by     TEXT NOT NULL,
    decided_by       TEXT,
    decided_at       TEXT,
    decision_comment TEXT,
    created_at       TEXT NOT NULL
);
CREATE INDEX ix_corr_emp ON corrections(tenant_id, employee_id, work_date);

CREATE TABLE daily_summaries (
    id              TEXT PRIMARY KEY,
    tenant_id       TEXT NOT NULL REFERENCES tenants(id),
    employee_id     TEXT NOT NULL REFERENCES employees(id),
    work_date       TEXT NOT NULL,
    shift_code      TEXT,
    planned_start   TEXT,
    planned_end     TEXT,
    first_in        TEXT,
    last_out        TEXT,
    worked_min      INTEGER NOT NULL DEFAULT 0,
    break_min       INTEGER NOT NULL DEFAULT 0,
    late_min        INTEGER NOT NULL DEFAULT 0,
    early_leave_min INTEGER NOT NULL DEFAULT 0,
    overtime_min    INTEGER NOT NULL DEFAULT 0,
    status          TEXT NOT NULL,
    anomalies       TEXT NOT NULL DEFAULT '[]',
    explanation     TEXT NOT NULL DEFAULT '',
    corrected       INTEGER NOT NULL DEFAULT 0,
    rule_version    INTEGER NOT NULL DEFAULT 1,
    computed_at     TEXT NOT NULL,
    UNIQUE (tenant_id, employee_id, work_date)
);
CREATE INDEX ix_summary_date ON daily_summaries(tenant_id, work_date);

CREATE TABLE anomalies (
    id          TEXT PRIMARY KEY,
    tenant_id   TEXT NOT NULL REFERENCES tenants(id),
    employee_id TEXT NOT NULL REFERENCES employees(id),
    work_date   TEXT NOT NULL,
    kind        TEXT NOT NULL,    -- missing_out | missing_in | late_event_after_close | clock_suspect | review_required
    status      TEXT NOT NULL DEFAULT 'open',   -- open | resolved
    details     TEXT NOT NULL DEFAULT '{}',
    created_at  TEXT NOT NULL,
    resolved_at TEXT,
    UNIQUE (tenant_id, employee_id, work_date, kind)
);

CREATE TABLE periods (
    id          TEXT PRIMARY KEY,
    tenant_id   TEXT NOT NULL REFERENCES tenants(id),
    site_id     TEXT NOT NULL REFERENCES sites(id),
    start_date  TEXT NOT NULL,
    end_date    TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'open',   -- open | closed | reopen_requested
    closed_by   TEXT,
    closed_at   TEXT,
    close_note  TEXT,
    reopen_requested_by TEXT,
    reopen_reason TEXT,
    created_at  TEXT NOT NULL,
    UNIQUE (tenant_id, site_id, start_date)
);

-- ---------------------------------------------------------------- identity
CREATE TABLE users (
    id              TEXT PRIMARY KEY,
    tenant_id       TEXT NOT NULL REFERENCES tenants(id),
    login           TEXT NOT NULL,     -- email or personnel number for employees
    email           TEXT,
    name            TEXT NOT NULL,
    password_hash   TEXT,
    status          TEXT NOT NULL DEFAULT 'active',   -- invited | active | blocked
    mfa_enabled     INTEGER NOT NULL DEFAULT 0,
    totp_secret_enc BLOB,
    backup_codes    TEXT NOT NULL DEFAULT '[]',
    failed_logins   INTEGER NOT NULL DEFAULT 0,
    locked_until    TEXT,
    employee_id     TEXT REFERENCES employees(id),
    language        TEXT NOT NULL DEFAULT 'uz',
    telegram_chat_id TEXT,
    invite_token_hash TEXT,
    invite_expires_at TEXT,
    created_at      TEXT NOT NULL,
    last_login_at   TEXT,
    UNIQUE (tenant_id, login)
);

CREATE TABLE roles (
    id          TEXT PRIMARY KEY,
    tenant_id   TEXT REFERENCES tenants(id),   -- NULL = system role
    code        TEXT NOT NULL,
    name        TEXT NOT NULL,
    permissions TEXT NOT NULL,                  -- JSON {permission: level}
    system      INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL
);
CREATE UNIQUE INDEX ux_roles_code ON roles(COALESCE(tenant_id, ''), code);

CREATE TABLE user_roles (
    id          TEXT PRIMARY KEY,
    tenant_id   TEXT NOT NULL REFERENCES tenants(id),
    user_id     TEXT NOT NULL REFERENCES users(id),
    role_code   TEXT NOT NULL,
    scope_type  TEXT NOT NULL,     -- global | site | department | team | self
    scope_id    TEXT,
    valid_until TEXT,
    created_by  TEXT,
    created_at  TEXT NOT NULL
);
CREATE INDEX ix_user_roles ON user_roles(user_id);

CREATE TABLE sessions (
    id           TEXT PRIMARY KEY,
    tenant_id    TEXT,                 -- NULL for platform sessions
    user_id      TEXT NOT NULL,
    realm        TEXT NOT NULL,        -- tenant | platform
    refresh_hash TEXT NOT NULL,
    mfa_passed   INTEGER NOT NULL DEFAULT 0,
    ip           TEXT,
    user_agent   TEXT,
    created_at   TEXT NOT NULL,
    expires_at   TEXT NOT NULL,
    revoked_at   TEXT
);
CREATE INDEX ix_sessions_user ON sessions(user_id);

CREATE TABLE login_history (
    id         TEXT PRIMARY KEY,
    tenant_id  TEXT,
    user_id    TEXT,
    login      TEXT NOT NULL,
    success    INTEGER NOT NULL,
    reason     TEXT,
    ip         TEXT,
    user_agent TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE api_keys (
    id           TEXT PRIMARY KEY,
    tenant_id    TEXT NOT NULL REFERENCES tenants(id),
    name         TEXT NOT NULL,
    prefix       TEXT NOT NULL UNIQUE,
    key_hash     TEXT NOT NULL,
    scopes       TEXT NOT NULL,
    ip_allowlist TEXT NOT NULL DEFAULT '[]',
    expires_at   TEXT,
    created_by   TEXT NOT NULL,
    created_at   TEXT NOT NULL,
    revoked_at   TEXT,
    last_used_at TEXT
);

-- ---------------------------------------------------------------- audit (hash chained, append-only)
CREATE TABLE audit_logs (
    seq         INTEGER PRIMARY KEY AUTOINCREMENT,
    id          TEXT NOT NULL UNIQUE,
    tenant_id   TEXT,                 -- NULL = platform scope
    actor_type  TEXT NOT NULL,        -- user | device | system | platform_user | api_key
    actor_id    TEXT,
    action      TEXT NOT NULL,
    object_type TEXT,
    object_id   TEXT,
    ip          TEXT,
    request_id  TEXT,
    before_json TEXT,
    after_json  TEXT,
    result      TEXT NOT NULL DEFAULT 'success',
    created_at  TEXT NOT NULL,
    prev_hash   TEXT NOT NULL,
    hash        TEXT NOT NULL
);
CREATE INDEX ix_audit_tenant ON audit_logs(tenant_id, seq);
CREATE INDEX ix_audit_object ON audit_logs(tenant_id, object_type, object_id);

CREATE TRIGGER trg_audit_no_update BEFORE UPDATE ON audit_logs
BEGIN
    SELECT RAISE(ABORT, 'audit_logs are append-only');
END;
CREATE TRIGGER trg_audit_no_delete BEFORE DELETE ON audit_logs
BEGIN
    SELECT RAISE(ABORT, 'audit_logs are append-only');
END;

CREATE TABLE security_alerts (
    id          TEXT PRIMARY KEY,
    tenant_id   TEXT NOT NULL REFERENCES tenants(id),
    kind        TEXT NOT NULL,     -- pad_attempt | unknown_repeat | duplicate_face | after_hours | login_failures | device_tamper | audit_chain_broken | gate_opened
    severity    TEXT NOT NULL,     -- low | medium | high | critical
    status      TEXT NOT NULL DEFAULT 'new',   -- new | in_review | closed
    device_id   TEXT,
    event_id    TEXT,
    details     TEXT NOT NULL DEFAULT '{}',
    assignee    TEXT,
    resolution  TEXT,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
CREATE INDEX ix_alerts_tenant ON security_alerts(tenant_id, status, created_at);

-- ---------------------------------------------------------------- notifications & settings
CREATE TABLE notifications (
    id         TEXT PRIMARY KEY,
    tenant_id  TEXT NOT NULL REFERENCES tenants(id),
    user_id    TEXT NOT NULL REFERENCES users(id),
    kind       TEXT NOT NULL,
    title      TEXT NOT NULL,
    body       TEXT NOT NULL,
    link       TEXT,
    read_at    TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX ix_notif_user ON notifications(user_id, read_at);

CREATE TABLE notification_outbox (
    id              TEXT PRIMARY KEY,
    tenant_id       TEXT,
    channel         TEXT NOT NULL,   -- email | telegram | webhook
    recipient       TEXT NOT NULL,
    payload         TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'pending',  -- pending | sent | failed | dead
    attempts        INTEGER NOT NULL DEFAULT 0,
    next_attempt_at TEXT NOT NULL,
    last_error      TEXT,
    created_at      TEXT NOT NULL
);

CREATE TABLE settings (
    id         TEXT PRIMARY KEY,
    tenant_id  TEXT NOT NULL REFERENCES tenants(id),
    key        TEXT NOT NULL,      -- attendance_rules | biometric_policy | retention | notifications | locale
    version    INTEGER NOT NULL,
    value      TEXT NOT NULL,
    valid_from TEXT,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (tenant_id, key, version)
);

CREATE TABLE webhooks (
    id         TEXT PRIMARY KEY,
    tenant_id  TEXT NOT NULL REFERENCES tenants(id),
    url        TEXT NOT NULL,
    events     TEXT NOT NULL,
    secret_enc BLOB NOT NULL,
    secret_nonce BLOB NOT NULL,
    status     TEXT NOT NULL DEFAULT 'active',
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE exports (
    id           TEXT PRIMARY KEY,
    tenant_id    TEXT NOT NULL REFERENCES tenants(id),
    kind         TEXT NOT NULL,
    params       TEXT NOT NULL,
    format       TEXT NOT NULL,
    status       TEXT NOT NULL,   -- running | ready | failed | expired
    file_path    TEXT,
    rows         INTEGER,
    error        TEXT,
    requested_by TEXT NOT NULL,
    created_at   TEXT NOT NULL,
    finished_at  TEXT,
    expires_at   TEXT
);

CREATE TABLE idempotency_keys (
    scope         TEXT NOT NULL,   -- tenant id or 'platform'
    key           TEXT NOT NULL,
    method        TEXT NOT NULL,
    path          TEXT NOT NULL,
    request_hash  TEXT NOT NULL,
    status_code   INTEGER NOT NULL,
    response      TEXT NOT NULL,
    created_at    TEXT NOT NULL,
    PRIMARY KEY (scope, key)
);

CREATE TABLE feedback (
    id         TEXT PRIMARY KEY,
    tenant_id  TEXT NOT NULL REFERENCES tenants(id),
    user_id    TEXT NOT NULL,
    score      INTEGER,
    comment    TEXT,
    context    TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE roi_baselines (
    tenant_id  TEXT PRIMARY KEY REFERENCES tenants(id),
    inputs     TEXT NOT NULL,
    updated_by TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE leads (
    id         TEXT PRIMARY KEY,
    email      TEXT NOT NULL,
    company    TEXT,
    inputs     TEXT NOT NULL,
    result     TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE backups (
    id         TEXT PRIMARY KEY,
    path       TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    sha256     TEXT NOT NULL,
    kind       TEXT NOT NULL,      -- backup | restore_test
    status     TEXT NOT NULL,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL
);
