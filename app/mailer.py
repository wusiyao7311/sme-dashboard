"""Send email via SMTP when SMTP_HOST is set; otherwise write .eml-style files to outbox/ (safe for the public demo)."""
from __future__ import annotations

import os
import smtplib
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path

OUTBOX = Path("outbox")


def send_email(to: str, subject: str, body: str) -> str:
    """Send one email. Returns 'sent' (SMTP) or the outbox file path (demo mode)."""
    msg = EmailMessage()
    msg["From"] = os.getenv("MAIL_FROM", "dashboard@example.com")
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)

    host = os.getenv("SMTP_HOST")
    if not host:
        OUTBOX.mkdir(exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        path = OUTBOX / f"{stamp}-{to.replace('@', '_at_')}.eml"
        path.write_bytes(bytes(msg))
        return str(path)

    with smtplib.SMTP(host, int(os.getenv("SMTP_PORT", "587")), timeout=30) as smtp:
        smtp.starttls()
        if os.getenv("SMTP_USER"):
            smtp.login(os.environ["SMTP_USER"], os.getenv("SMTP_PASSWORD", ""))
        smtp.send_message(msg)
    return "sent"
