from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage
from pathlib import Path

from ..config import settings

logger = logging.getLogger(__name__)


def _smtp_ready() -> bool:
    return bool(settings.SMTP_HOST and settings.SMTP_FROM_EMAIL)


def send_receipt_email(
    *,
    recipient: str,
    student_name: str,
    subject: str,
    body: str,
    receipt_path: str | None = None,
) -> str:
    if not _smtp_ready():
        logger.info("SMTP not configured. Receipt email simulated for %s.", recipient)
        return "simulated"

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = settings.SMTP_FROM_EMAIL
    message["To"] = recipient
    message.set_content(f"Dear {student_name or 'Student'},\n\n{body}\n")

    if receipt_path:
        file_path = Path(receipt_path)
        if file_path.exists():
            message.add_attachment(
                file_path.read_bytes(),
                maintype="application",
                subtype="pdf",
                filename=file_path.name,
            )

    try:
        with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=20) as smtp:
            if settings.SMTP_USE_TLS:
                smtp.starttls()
            if settings.SMTP_USERNAME and settings.SMTP_PASSWORD:
                smtp.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD)
            smtp.send_message(message)
    except Exception:
        logger.exception("Failed to send receipt email to %s", recipient)
        return "failed"

    return "sent"
