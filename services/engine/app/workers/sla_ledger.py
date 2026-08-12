"""
SLA Delivery Ledger Worker.

Evaluates whether each active property has delivered required report types
before local SLA cutoff + grace, and emits MISSING_DELIVERY alerts.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.alerts.dispatcher import dispatch_airlock_alert
from app.db import (
    fetch_active_properties,
    fetch_contract_by_id,
    fetch_run_reports_for_business_date,
    is_supabase_configured,
)

logger = logging.getLogger("airlock.sla_ledger")

_VALID_DELIVERY_OUTCOMES = {"PASS", "HOLD_SET"}


def _property_timezone(prop: dict[str, Any]) -> ZoneInfo:
    name = (
        prop.get("timezone")
        or prop.get("local_timezone")
        or "UTC"
    )
    try:
        return ZoneInfo(str(name))
    except ZoneInfoNotFoundError:
        logger.warning(
            "Unknown timezone %r for %s; falling back to UTC",
            name,
            prop.get("property_id"),
        )
        return ZoneInfo("UTC")


def _parse_cutoff(value: Any) -> time:
    if isinstance(value, time):
        return value
    text = str(value or "06:00:00").strip()
    for fmt in ("%H:%M:%S", "%H:%M"):
        try:
            return datetime.strptime(text, fmt).time()
        except ValueError:
            continue
    return time(6, 0, 0)


def _grace_minutes(prop: dict[str, Any]) -> int:
    raw = prop.get("sla_grace_period_mins")
    if raw is None:
        raw = prop.get("grace_period_minutes", 30)
    try:
        return max(0, int(raw))
    except (TypeError, ValueError):
        return 30


def _deadline_local(prop: dict[str, Any], local_now: datetime) -> datetime:
    cutoff = _parse_cutoff(
        prop.get("sla_cutoff_time") or prop.get("sla_delivery_cutoff")
    )
    grace = _grace_minutes(prop)
    base = datetime.combine(local_now.date(), cutoff, tzinfo=local_now.tzinfo)
    return base + timedelta(minutes=grace)


def _alert_emails(prop: dict[str, Any]) -> list[str]:
    if isinstance(prop.get("alert_emails"), list):
        return [str(e) for e in prop["alert_emails"] if e]
    rules = prop.get("alert_rules") if isinstance(prop.get("alert_rules"), dict) else {}
    emails = rules.get("email_recipients") or []
    return [str(e) for e in emails if e]


def _slack_webhook(prop: dict[str, Any]) -> Optional[str]:
    rules = prop.get("alert_rules") if isinstance(prop.get("alert_rules"), dict) else {}
    for key in ("slack_webhook_url", "slack_webhook", "webhook_url"):
        if rules.get(key):
            return str(rules[key])
        if prop.get(key):
            return str(prop[key])
    return None


def _required_report_types(contract: Optional[dict[str, Any]]) -> list[str]:
    if not contract:
        return []
    yaml_doc = contract.get("contract_yaml")
    if not isinstance(yaml_doc, dict):
        yaml_doc = {}

    atomic = yaml_doc.get("atomic_set")
    if isinstance(atomic, dict):
        endpoints = atomic.get("required_endpoints") or atomic.get("members") or []
        if endpoints:
            return [str(e) for e in endpoints]

    sets = yaml_doc.get("atomic_sets")
    if isinstance(sets, list) and sets and isinstance(sets[0], dict):
        members = sets[0].get("members") or []
        if members:
            return [str(e) for e in members]

    gate1 = yaml_doc.get("gate_1") if isinstance(yaml_doc.get("gate_1"), dict) else {}
    endpoints = gate1.get("required_set_endpoints") or []
    return [str(e) for e in endpoints]


def _delivered_report_types(
    reports: list[dict[str, Any]],
) -> set[str]:
    delivered: set[str] = set()
    for rec in reports:
        outcome = str(rec.get("overall_outcome") or "")
        if outcome not in _VALID_DELIVERY_OUTCOMES:
            continue
        rtype = rec.get("report_type")
        if rtype:
            delivered.add(str(rtype))
    return delivered


async def check_property_sla_deliveries(
    *,
    dispatch_alerts: bool = True,
    as_of_utc: Optional[datetime] = None,
) -> dict[str, Any]:
    """
    Scan active properties and emit MISSING_DELIVERY when past local SLA deadline
    without PASS/HOLD_SET coverage for required report types.
    """
    if not is_supabase_configured():
        return {
            "status": "skipped",
            "reason": "supabase_not_configured",
            "checked": 0,
            "alerts": [],
        }

    now_utc = as_of_utc or datetime.now(timezone.utc)
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=timezone.utc)

    properties = fetch_active_properties()
    alerts: list[dict[str, Any]] = []
    checked = 0
    past_deadline = 0
    ok_count = 0

    for prop in properties:
        property_id = str(prop.get("property_id") or "").strip()
        if not property_id:
            continue
        checked += 1

        tz = _property_timezone(prop)
        local_now = now_utc.astimezone(tz)
        business_date: date = local_now.date()
        deadline = _deadline_local(prop, local_now)

        if local_now < deadline:
            # Still inside the delivery window
            continue

        past_deadline += 1

        contract = None
        contract_id = prop.get("active_contract_id")
        if contract_id:
            contract = fetch_contract_by_id(str(contract_id))

        required = _required_report_types(contract)
        if not required:
            # Without a declared atomic set, treat any PASS/HOLD_SET as sufficient.
            required = []

        reports = fetch_run_reports_for_business_date(
            property_id,
            business_date=business_date.isoformat(),
        )
        delivered = _delivered_report_types(reports)

        if required:
            missing = [r for r in required if r not in delivered]
            satisfied = len(missing) == 0
        else:
            missing = []
            satisfied = len(delivered) > 0

        if satisfied:
            ok_count += 1
            continue

        event = {
            "event_type": "MISSING_DELIVERY",
            "property_id": property_id,
            "business_date": business_date.isoformat(),
            "local_time": local_now.isoformat(),
            "deadline_local": deadline.isoformat(),
            "timezone": str(tz),
            "required_report_types": required,
            "delivered_report_types": sorted(delivered),
            "missing_report_types": missing
            if required
            else ["<any PASS/HOLD_SET delivery>"],
            "sla_cutoff": str(
                prop.get("sla_cutoff_time") or prop.get("sla_delivery_cutoff")
            ),
            "grace_minutes": _grace_minutes(prop),
        }
        alerts.append(event)

        if dispatch_alerts:
            title = (
                f"Missing delivery for {business_date.isoformat()} — "
                f"past SLA deadline {deadline.strftime('%H:%M %Z')}"
            )
            await dispatch_airlock_alert(
                event_type="MISSING_DELIVERY",
                property_id=property_id,
                title=title,
                details={
                    "business_date": event["business_date"],
                    "deadline_local": event["deadline_local"],
                    "missing": ", ".join(event["missing_report_types"]),
                    "delivered": ", ".join(event["delivered_report_types"]) or "none",
                    "timezone": event["timezone"],
                },
                slack_webhook_url=_slack_webhook(prop),
                recipient_emails=_alert_emails(prop),
            )

        logger.warning(
            "MISSING_DELIVERY property=%s date=%s missing=%s",
            property_id,
            business_date.isoformat(),
            event["missing_report_types"],
        )

    return {
        "status": "ok",
        "checked_at_utc": now_utc.isoformat(),
        "checked": checked,
        "past_deadline": past_deadline,
        "satisfied": ok_count,
        "missing_delivery_count": len(alerts),
        "alerts": alerts,
    }
