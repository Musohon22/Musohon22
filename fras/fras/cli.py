"""Command line: python -m fras <command>."""

from __future__ import annotations

import argparse
import getpass
import sys

from .config import load_settings
from .db import Database
from .security import crypto, passwords, totp
from .services import tenancy
from .util import new_id, now_iso


def _db():
    s = load_settings()
    d = Database(s.db_path)
    d.migrate()
    with d.tx() as conn:
        tenancy.seed_plans(conn)
    return s, d


def cmd_migrate(args):
    s = load_settings()
    applied = Database(s.db_path).migrate()
    print("applied:", applied or "nothing to do")


def cmd_platform_user(args):
    s, d = _db()
    pw = args.password or getpass.getpass("Password: ")
    problems = passwords.password_problems(pw)
    if problems:
        sys.exit(f"weak password: {problems}")
    secret = totp.new_secret() if args.mfa else None
    with d.tx() as conn:
        conn.execute("INSERT INTO platform_users (id, email, name, password_hash, role, totp_secret, mfa_enabled, status, "
                     "created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                     (new_id(), args.email.lower(), args.name, passwords.hash_secret(pw), args.role,
                      crypto.seal(s.master_key, secret.encode(), b"platform-totp").hex() if secret else None,
                      1 if secret else 0, "active", now_iso()))
    print("platform user created", args.email)
    if secret:
        print("TOTP secret (add to an authenticator app):", secret)


def cmd_tenant(args):
    s, d = _db()
    with d.tx() as conn:
        res = tenancy.create_tenant(conn, s.master_key, slug=args.slug, name=args.name, plan_code=args.plan,
                                    admin_email=args.admin_email, admin_name=args.admin_name,
                                    admin_password=args.admin_password, trial_days=args.trial_days)
    print("tenant:", res["tenant_id"])
    if res["invite_token"]:
        print(f"invite: {s.public_base_url}/app/invite?org={args.slug}&token={res['invite_token']}")


def cmd_seed(args):
    from .seed import seed_demo
    s, d = _db()
    info = seed_demo(s, d, employees=args.employees, days=args.days)
    for line in info:
        print(line)


def cmd_serve(args):
    import uvicorn
    from .app import create_app
    uvicorn.run(create_app(), host=args.host, port=args.port, proxy_headers=True, log_level="info")


def main(argv=None):
    p = argparse.ArgumentParser(prog="fras")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("migrate").set_defaults(fn=cmd_migrate)
    pu = sub.add_parser("create-platform-user")
    pu.add_argument("--email", required=True)
    pu.add_argument("--name", required=True)
    pu.add_argument("--role", default="owner", choices=["owner", "billing", "success", "support", "security"])
    pu.add_argument("--password")
    pu.add_argument("--mfa", action="store_true")
    pu.set_defaults(fn=cmd_platform_user)
    pt = sub.add_parser("create-tenant")
    pt.add_argument("--slug", required=True)
    pt.add_argument("--name", required=True)
    pt.add_argument("--plan", default="business")
    pt.add_argument("--admin-email", required=True)
    pt.add_argument("--admin-name", required=True)
    pt.add_argument("--admin-password")
    pt.add_argument("--trial-days", type=int, default=0)
    pt.set_defaults(fn=cmd_tenant)
    ps = sub.add_parser("seed-demo")
    ps.add_argument("--employees", type=int, default=60)
    ps.add_argument("--days", type=int, default=14)
    ps.set_defaults(fn=cmd_seed)
    sv = sub.add_parser("serve")
    sv.add_argument("--host", default="127.0.0.1")
    sv.add_argument("--port", type=int, default=8000)
    sv.set_defaults(fn=cmd_serve)
    args = p.parse_args(argv)
    args.fn(args)
