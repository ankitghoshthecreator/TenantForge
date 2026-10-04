"""
Email service — stub for dev, swap with SES/SendGrid in prod.

In ENVIRONMENT=development, emails are printed to stdout instead of sent.
This keeps the provisioning flow end-to-end testable without SMTP credentials.
"""

import logging
from dataclasses import dataclass

from src.core.config import settings

logger = logging.getLogger(__name__)


@dataclass
class EmailMessage:
    to: str
    subject: str
    body: str


async def send_email(msg: EmailMessage) -> None:
    """
    Send an email.  In dev mode, log it instead of sending.
    In production, replace this body with an SES/SendGrid call.
    """
    if settings.ENVIRONMENT == "development":
        logger.info(
            "\n"
            "╔══════════════════════════════════════════════════╗\n"
            "║  [EMAIL STUB — NOT ACTUALLY SENT]               ║\n"
            f"║  To:      {msg.to:<40}║\n"
            f"║  Subject: {msg.subject:<40}║\n"
            "╠══════════════════════════════════════════════════╣\n"
            f"{msg.body}\n"
            "╚══════════════════════════════════════════════════╝"
        )
        return

    # TODO: plug in real email provider here
    # e.g. boto3 SES client or httpx call to SendGrid
    raise NotImplementedError("Configure a real email provider for production")
