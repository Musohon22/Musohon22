"""Outgoing email. Uses SMTP when REJA_SMTP_HOST is set; otherwise messages are only logged
(and kept in `sent` so tests and local development can see them)."""

import logging
import os
import smtplib
import ssl
from email.message import EmailMessage

log = logging.getLogger("reja.mail")
sent: list[dict] = []
MAX_KEPT = 200


def configured() -> bool:
    return bool(os.environ.get("REJA_SMTP_HOST"))


def send(to: str, subject: str, text: str) -> bool:
    sent.append({"to": to, "subject": subject, "text": text})
    del sent[:-MAX_KEPT]
    host = os.environ.get("REJA_SMTP_HOST")
    if not host:
        log.info("email (not sent, no SMTP configured) to=%s subject=%s", to, subject)
        return False
    msg = EmailMessage()
    msg["From"] = os.environ.get("REJA_SMTP_FROM", "Reja <no-reply@localhost>")
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(text)
    port = int(os.environ.get("REJA_SMTP_PORT", "587"))
    user = os.environ.get("REJA_SMTP_USER")
    password = os.environ.get("REJA_SMTP_PASSWORD")
    try:
        if port == 465:
            server = smtplib.SMTP_SSL(host, port, timeout=15, context=ssl.create_default_context())
        else:
            server = smtplib.SMTP(host, port, timeout=15)
            server.starttls(context=ssl.create_default_context())
        with server:
            if user:
                server.login(user, password or "")
            server.send_message(msg)
        return True
    except (OSError, smtplib.SMTPException):
        log.exception("email to %s failed", to)
        return False
