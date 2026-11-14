"""SMTP notification module."""

import logging
import smtplib
from email.message import EmailMessage

from src.checker import CheckResult, STATUS_AVAILABLE
from src.config import Config

logger = logging.getLogger(__name__)


def format_email_body(config: Config, result: CheckResult) -> str:
    """Format a human-readable plain-text result email."""
    return f"""Oracle A1.Flex Availability Checker

Status: {result.status}
Region: {config.region}
Target shape: {config.shape} ({config.ocpus} OCPU, {config.memory_gb} GB RAM)
Timestamp (UTC): {result.timestamp}

Quota:
- OCPU available: {result.quota_available}
- OCPU used: {result.quota_used}
- OCPU limit: {result.quota_limit}
- Memory available (GB): {result.memory_quota_available}
- Memory used (GB): {result.memory_quota_used}
- Memory limit (GB): {result.memory_quota_limit}

Shape availability confirmed: {result.shape_available}
Availability Domain: {result.ad_name or 'Not confirmed'}
Details: {result.details}

Important limitation:
{result.limitations}

This checker is read-only and never provisions or creates a VM.
"""


def send_notification(config: Config, result: CheckResult) -> bool:
    """Send an availability notification through SMTP.

    Notifications are intentionally suppressed unless status is AVAILABLE.
    Returns True when sent, False when suppressed or delivery fails.
    """
    if result.status != STATUS_AVAILABLE:
        logger.info("Notification suppressed for status %s", result.status)
        return False

    message = EmailMessage()
    message["Subject"] = (
        f"OCI A1.Flex capacity indicated in {config.region}"
    )
    message["From"] = config.email_from
    message["To"] = config.email_to
    message.set_content(format_email_body(config, result))

    try:
        with smtplib.SMTP(config.smtp_host, config.smtp_port, timeout=30) as smtp:
            smtp.ehlo()
            smtp.starttls()
            smtp.ehlo()
            smtp.login(config.smtp_user, config.smtp_password)
            smtp.send_message(message)
        logger.info("Availability notification sent to %s", config.email_to)
        return True
    except (OSError, smtplib.SMTPException) as exc:
        logger.error("SMTP notification failed: %s", exc)
        return False
