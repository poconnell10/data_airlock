"""
Alert Dispatcher — Slack webhooks + SMTP email for Airlock events.
"""

from __future__ import annotations

import logging
import os
import smtplib
from email.message import EmailMessage
from typing import Any, Optional

import httpx

logger = logging.getLogger("airlock.alerts")

ALERT_EVENTS = {
    "QUARANTINE_FILE",
    "REJECT_FILE",
    "MISSING_DELIVERY",
    "HOLD_SET",
    "FLAG",
}


async def send_slack_alert(webhook_url: str, message: dict[str, Any]) -> bool:
    """
    Post a structured Slack Block Kit (or text) payload to an Incoming Webhook.
    """
    url = (webhook_url or "").strip()
    if not url:
        logger.warning("send_slack_alert skipped: empty webhook_url")
        return False

    # Normalize to Slack webhook JSON
    if "blocks" in message or "text" in message:
        payload = message
    else:
        text = str(message.get("text") or message.get("message") or message)
        payload = {"text": text}

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(url, json=payload)
            if resp.status_code >= 300:
                logger.error(
                    "Slack webhook failed status=%s body=%s",
                    resp.status_code,
                    resp.text[:300],
                )
                return False
            return True
    except httpx.HTTPError as exc:
        logger.error("Slack webhook error: %s", exc)
        return False


async def send_email_alert(
    recipient_emails: list[str],
    subject: str,
    body: str,
) -> bool:
    """
    Dispatch an email via SMTP for QUARANTINE_FILE / REJECT_FILE / MISSING_DELIVERY.

    Requires SMTP_* environment variables. Returns False (no exception) when
    SMTP is not configured — callers can still log the alert event.
    """
    recipients = [e.strip() for e in (recipient_emails or []) if e and e.strip()]
    if not recipients:
        logger.warning("send_email_alert skipped: no recipients")
        return False

    host = os.getenv("SMTP_HOST", "").strip()
    port = int(os.getenv("SMTP_PORT", "587") or "587")
    username = os.getenv("SMTP_USERNAME", "").strip()
    password = os.getenv("SMTP_PASSWORD", "").strip()
    mail_from = os.getenv("SMTP_FROM", username or "airlock@localhost").strip()
    use_tls = os.getenv("SMTP_USE_TLS", "true").lower() in {"1", "true", "yes"}

    if not host:
        logger.warning(
            "send_email_alert skipped: SMTP_HOST not configured (to=%s subject=%s)",
            recipients,
            subject,
        )
        return False

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = mail_from
    msg["To"] = ", ".join(recipients)
    msg.set_content(body)

    try:
        # smtplib is sync; run in thread via to_thread would be nicer on 3.9+ —
        # keep sync here for simplicity inside async callers (short SMTP handshake).
        with smtplib.SMTP(host, port, timeout=20) as smtp:
            if use_tls:
                smtp.starttls()
            if username:
                smtp.login(username, password)
            smtp.send_message(msg)
        return True
    except Exception as exc:  # noqa: BLE001
        logger.error("SMTP send failed: %s", exc)
        return False


def build_slack_blocks(
    *,
    event_type: str,
    property_id: str,
    title: str,
    details: dict[str, Any],
) -> dict[str, Any]:
    """Build a compact Slack Block Kit message for Airlock alerts."""
    fields = []
    for key, value in details.items():
        fields.append(
            {
                "type": "mrkdwn",
                "text": f"*{key}:*\n{value}",
            }
        )
    # Slack section fields max 10
    fields = fields[:10]
    return {
        "text": f"[{event_type}] {title}",
        "blocks": [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": f"Airlock · {event_type}",
                },
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Property:* `{property_id}`\n{title}",
                },
            },
            {"type": "section", "fields": fields}
            if fields
            else {
                "type": "section",
                "text": {"type": "mrkdwn", "text": "_No additional details_"},
            },
        ],
    }


async def dispatch_airlock_alert(
    *,
    event_type: str,
    property_id: str,
    title: str,
    details: Optional[dict[str, Any]] = None,
    slack_webhook_url: Optional[str] = None,
    recipient_emails: Optional[list[str]] = None,
) -> dict[str, bool]:
    """
    Fan-out an Airlock alert to Slack + email channels.

    Primary event types: QUARANTINE_FILE, REJECT_FILE, MISSING_DELIVERY.
    """
    details = details or {}
    webhook = (slack_webhook_url or os.getenv("SLACK_WEBHOOK_URL") or "").strip()
    emails = list(recipient_emails or [])

    slack_payload = build_slack_blocks(
        event_type=event_type,
        property_id=property_id,
        title=title,
        details=details,
    )
    subject = f"[Airlock {event_type}] {property_id}"
    body_lines = [title, "", f"Property: {property_id}", f"Event: {event_type}", ""]
    for k, v in details.items():
        body_lines.append(f"{k}: {v}")
    body = "\n".join(body_lines)

    slack_ok = False
    email_ok = False
    if webhook:
        slack_ok = await send_slack_alert(webhook, slack_payload)
    if emails and event_type in {
        "QUARANTINE_FILE",
        "REJECT_FILE",
        "MISSING_DELIVERY",
    }:
        email_ok = await send_email_alert(emails, subject, body)

    logger.info(
        "dispatch_airlock_alert event=%s property=%s slack=%s email=%s",
        event_type,
        property_id,
        slack_ok,
        email_ok,
    )
    return {"slack": slack_ok, "email": email_ok}
