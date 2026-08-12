"""Supabase client for the FastAPI engine (service-role)."""

from __future__ import annotations

import json
import os
import re
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from typing import Any, Optional

from supabase import Client, create_client

_PGRST204_COLUMN = re.compile(
    r"Could not find the '([^']+)' column",
    re.IGNORECASE,
)

_RUN_REPORT_JSONB_LIST_COLS = frozenset({"quarantine_manifest", "findings"})
_RUN_REPORT_JSONB_OBJECT_COLS = frozenset({"gate_evaluations", "readiness_stats"})


def is_supabase_configured() -> bool:
    return bool(os.getenv("SUPABASE_URL") and os.getenv("SUPABASE_SERVICE_ROLE_KEY"))


@lru_cache(maxsize=1)
def get_supabase() -> Client:
    """
    Service-role Supabase client singleton.

    Never expose this client (or the service role key) to the browser.
    """
    url = os.getenv("SUPABASE_URL", "").strip()
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    if not url or not key:
        raise RuntimeError(
            "Missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY in engine environment."
        )
    return create_client(url, key)


def fetch_property_contract(
    property_id: str,
) -> tuple[Optional[dict[str, Any]], Optional[dict[str, Any]]]:
    """Load a property row and its active ingestion contract (if any)."""
    client = get_supabase()
    prop_resp = (
        client.table("properties")
        .select("*")
        .eq("property_id", property_id)
        .maybe_single()
        .execute()
    )
    property_row = prop_resp.data if prop_resp else None
    if not property_row:
        return None, None

    contract_id = property_row.get("active_contract_id")
    if not contract_id:
        return property_row, None

    contract_resp = (
        client.table("ingestion_contracts")
        .select("*")
        .eq("id", contract_id)
        .maybe_single()
        .execute()
    )
    contract_row = contract_resp.data if contract_resp else None
    return property_row, contract_row


def fetch_run_reports_history(
    property_id: str,
    *,
    report_type: Optional[str] = None,
    lookback_days: int = 45,
    limit: int = 500,
) -> list[dict[str, Any]]:
    """
    Fetch recent run_reports for Gate 2 baselines / hash drift checks.

    Tolerates schema drift between local migrations and remote tables by
    selecting * and normalizing in the gate evaluator.
    """
    client = get_supabase()
    since = (date.today() - timedelta(days=lookback_days)).isoformat()
    query = (
        client.table("run_reports")
        .select("*")
        .eq("property_id", property_id)
        .gte("business_date", since)
        .order("business_date", desc=True)
        .limit(limit)
    )
    if report_type:
        query = query.eq("report_type", report_type)
    try:
        resp = query.execute()
    except Exception:
        # Table may not exist yet in some environments
        return []
    rows = resp.data or []
    return [r for r in rows if isinstance(r, dict)]


def fetch_active_properties() -> list[dict[str, Any]]:
    """Return active property rows (tolerates missing `active` column)."""
    client = get_supabase()
    try:
        resp = (
            client.table("properties")
            .select("*")
            .eq("active", True)
            .execute()
        )
        rows = resp.data or []
        if rows:
            return [r for r in rows if isinstance(r, dict)]
    except Exception:
        pass

    # Fallback: no active flag / column — return all properties
    try:
        resp = client.table("properties").select("*").execute()
        rows = resp.data or []
        return [r for r in rows if isinstance(r, dict)]
    except Exception:
        return []


def fetch_contract_by_id(contract_id: str) -> Optional[dict[str, Any]]:
    client = get_supabase()
    try:
        resp = (
            client.table("ingestion_contracts")
            .select("*")
            .eq("id", contract_id)
            .maybe_single()
            .execute()
        )
        data = resp.data if resp else None
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def fetch_run_reports_for_business_date(
    property_id: str,
    *,
    business_date: str,
    limit: int = 200,
) -> list[dict[str, Any]]:
    """Fetch run_reports for a property on a specific business_date."""
    client = get_supabase()
    try:
        resp = (
            client.table("run_reports")
            .select("*")
            .eq("property_id", property_id)
            .eq("business_date", business_date)
            .limit(limit)
            .execute()
        )
        rows = resp.data or []
        return [r for r in rows if isinstance(r, dict)]
    except Exception:
        return []


def fetch_run_report_by_id(run_id: str) -> Optional[dict[str, Any]]:
    client = get_supabase()
    try:
        resp = (
            client.table("run_reports")
            .select("*")
            .eq("run_id", run_id)
            .maybe_single()
            .execute()
        )
        data = resp.data if resp else None
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def fetch_adjudication_queue_rows(limit: int = 100) -> list[dict[str, Any]]:
    """Blocked / flagged outcomes for the adjudication action queue."""
    client = get_supabase()
    blocked = ["QUARANTINE_FILE", "HOLD_SET", "REJECT_FILE", "FLAG"]
    try:
        resp = (
            client.table("run_reports")
            .select("*")
            .in_("overall_outcome", blocked)
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
        rows = resp.data or []
        return [r for r in rows if isinstance(r, dict)]
    except Exception:
        return []


def count_run_reports_by_outcomes(
    outcomes: list[str],
    *,
    since_iso: Optional[str] = None,
) -> int:
    client = get_supabase()
    try:
        query = (
            client.table("run_reports")
            .select("run_id", count="exact")
            .in_("overall_outcome", outcomes)
        )
        if since_iso:
            query = query.gte("created_at", since_iso)
        resp = query.execute()
        if resp.count is not None:
            return int(resp.count)
        return len(resp.data or [])
    except Exception:
        return 0


def _jsonb_compatible(value: Any) -> Any:
    """Coerce Pydantic models / JSON strings into list/dict for JSONB columns."""
    if value is None:
        return None
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, (list, dict)):
        return json.loads(json.dumps(value, default=str))
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return value
        return parsed
    return value


def _normalize_run_report_row(row: dict[str, Any]) -> dict[str, Any]:
    payload = dict(row)
    for key in _RUN_REPORT_JSONB_LIST_COLS:
        if key not in payload:
            continue
        payload[key] = _jsonb_compatible(payload[key])
        if not isinstance(payload[key], list):
            payload[key] = []
    for key in _RUN_REPORT_JSONB_OBJECT_COLS:
        if key not in payload:
            continue
        payload[key] = _jsonb_compatible(payload[key])
        if not isinstance(payload[key], dict):
            payload[key] = {}
    return payload


def _pgrst204_missing_column(exc: BaseException) -> Optional[str]:
    code = getattr(exc, "code", None)
    message = str(getattr(exc, "message", "") or exc)
    blob = f"{code} {message}"
    if "PGRST204" not in blob and "schema cache" not in blob.lower():
        return None
    match = _PGRST204_COLUMN.search(blob)
    return match.group(1) if match else None


def insert_run_report(row: dict[str, Any]) -> dict[str, Any]:
    """
    Append-only insert into run_reports.

    Never updates existing rows (audit immutability), except via release_run_report.
    JSONB fields are sent as native list/dict. If PostgREST schema cache is stale
    (PGRST204), retry without the unknown column so persist still succeeds.
    """
    client = get_supabase()
    payload = _normalize_run_report_row(row)
    last_exc: Optional[BaseException] = None
    for _ in range(6):
        try:
            resp = client.table("run_reports").insert(payload).execute()
            data = resp.data
            if isinstance(data, list) and data:
                return data[0] if isinstance(data[0], dict) else payload
            if isinstance(data, dict):
                return data
            return payload
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            missing = _pgrst204_missing_column(exc)
            if missing and missing in payload:
                payload.pop(missing, None)
                continue
            raise
    if last_exc:
        raise last_exc
    return payload


def release_run_report(
    run_id: str,
    *,
    operator_id: str,
    reason: str = "",
) -> dict[str, Any]:
    """
    Transition a blocked/flagged run to RELEASED_TO_ETL.

    Allowed by the DB trigger only when overall_outcome moves to RELEASED_TO_ETL.
    """
    client = get_supabase()
    patch: dict[str, Any] = {
        "overall_outcome": "RELEASED_TO_ETL",
        "released_by": operator_id,
        "released_at": datetime.now(timezone.utc).isoformat(),
        "outcome_reason": reason or f"Released to ETL by {operator_id}",
    }
    resp = (
        client.table("run_reports")
        .update(patch)
        .eq("run_id", run_id)
        .execute()
    )
    data = resp.data
    if isinstance(data, list) and data and isinstance(data[0], dict):
        return data[0]
    if isinstance(data, dict):
        return data
    # Fallback read
    row = fetch_run_report_by_id(run_id)
    if not row:
        raise RuntimeError(f"Release update returned empty for run_id={run_id}")
    return row


def classify_run_report(
    run_id: str,
    *,
    quarantine_manifest: list[dict[str, Any]],
    operator_id: str,
) -> dict[str, Any]:
    """
    Persist operator re-classification tags onto quarantine_manifest.

    Does not change overall_outcome (audit identity preserved).
    """
    client = get_supabase()
    patch: dict[str, Any] = {
        "quarantine_manifest": quarantine_manifest,
        "outcome_reason": f"Classification updated by {operator_id}",
    }
    resp = (
        client.table("run_reports")
        .update(patch)
        .eq("run_id", run_id)
        .execute()
    )
    data = resp.data
    if isinstance(data, list) and data and isinstance(data[0], dict):
        return data[0]
    if isinstance(data, dict):
        return data
    row = fetch_run_report_by_id(run_id)
    if not row:
        raise RuntimeError(f"Classify update returned empty for run_id={run_id}")
    return row


def fetch_properties_by_ids(property_ids: list[str]) -> dict[str, dict[str, Any]]:
    """Map property_id → property row for join enrichment."""
    ids = sorted({p for p in property_ids if p})
    if not ids:
        return {}
    client = get_supabase()
    try:
        resp = (
            client.table("properties")
            .select("*")
            .in_("property_id", ids)
            .execute()
        )
        rows = resp.data or []
        out: dict[str, dict[str, Any]] = {}
        for row in rows:
            if isinstance(row, dict) and row.get("property_id"):
                out[str(row["property_id"])] = row
        return out
    except Exception:
        return {}


def fetch_property_feed(feed_id: str) -> Optional[dict[str, Any]]:
    client = get_supabase()
    try:
        resp = (
            client.table("property_feeds")
            .select("*")
            .eq("id", feed_id)
            .maybe_single()
            .execute()
        )
        data = resp.data if resp else None
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def fetch_airlock_contract(
    property_id: str,
    feed_id: str,
) -> Optional[dict[str, Any]]:
    client = get_supabase()
    try:
        resp = (
            client.table("airlock_contracts")
            .select("*")
            .eq("property_id", property_id)
            .eq("feed_id", feed_id)
            .maybe_single()
            .execute()
        )
        data = resp.data if resp else None
        return data if isinstance(data, dict) else None
    except Exception:
        return None


# INT4 max; JS epoch-ms (e.g. 1786501628757) overflows this — needs BIGINT.
INT4_MAX = 2_147_483_647


def epoch_ms_to_timestamptz_iso(epoch_ms: int | float | str) -> str:
    """Convert JS epoch milliseconds → ISO-8601 UTC for TIMESTAMPTZ columns."""
    ms = int(epoch_ms)
    return datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc).isoformat()


def normalize_ingestion_contract_version(
    version: Optional[Any] = None,
) -> int:
    """
    Normalize ingestion_contracts.version to a BIGINT-safe integer.

    Prefer explicit epoch-ms tokens. Non-numeric labels (e.g. schema \"2.0\")
    mint a fresh epoch-ms value so INT/BIGINT columns never receive decimals.
    """
    if version is None or version == "":
        return int(datetime.now(timezone.utc).timestamp() * 1000)
    if isinstance(version, bool):
        raise ValueError("version must not be a boolean")
    if isinstance(version, int):
        return version
    if isinstance(version, float):
        return int(version)
    text = str(version).strip()
    if text.isdigit() or (text.startswith("-") and text[1:].isdigit()):
        return int(text)
    return int(datetime.now(timezone.utc).timestamp() * 1000)


def upsert_ingestion_contract(
    *,
    profile_id: str,
    file_format: str,
    contract_yaml: dict[str, Any],
    existing_id: Optional[str] = None,
    version: Optional[Any] = None,
) -> dict[str, Any]:
    """Insert or update an ingestion_contracts row used by Gate evaluation."""
    client = get_supabase()
    now_iso = datetime.now(timezone.utc).isoformat()
    if existing_id:
        resp = (
            client.table("ingestion_contracts")
            .update(
                {
                    "profile_id": profile_id,
                    "file_format": file_format,
                    "contract_yaml": contract_yaml,
                    "updated_at": now_iso,
                }
            )
            .eq("id", existing_id)
            .execute()
        )
        data = resp.data
        if isinstance(data, list) and data and isinstance(data[0], dict):
            return data[0]
        if isinstance(data, dict):
            return data

    # BIGINT-safe epoch-ms integer (INT4 max is 2147483647; ms epochs exceed it)
    ver = normalize_ingestion_contract_version(version)
    resp = (
        client.table("ingestion_contracts")
        .insert(
            {
                "profile_id": profile_id,
                "version": ver,
                "file_format": file_format,
                "contract_yaml": contract_yaml,
            }
        )
        .execute()
    )
    data = resp.data
    if isinstance(data, list) and data and isinstance(data[0], dict):
        return data[0]
    if isinstance(data, dict):
        return data
    raise RuntimeError("ingestion_contracts insert returned empty")


def upsert_airlock_contract(row: dict[str, Any]) -> dict[str, Any]:
    """Upsert airlock_contracts on unique (property_id, feed_id)."""
    client = get_supabase()
    payload = {
        **row,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    resp = (
        client.table("airlock_contracts")
        .upsert(payload, on_conflict="property_id,feed_id")
        .execute()
    )
    data = resp.data
    if isinstance(data, list) and data and isinstance(data[0], dict):
        return data[0]
    if isinstance(data, dict):
        return data
    raise RuntimeError("airlock_contracts upsert returned empty")


def link_feed_active_contract(
    *,
    feed_id: str,
    property_id: str,
    contract_id: str,
    sla_cutoff_time: Optional[str] = None,
    preset_id: Optional[str] = None,
) -> dict[str, Any]:
    client = get_supabase()
    patch: dict[str, Any] = {"active_contract_id": contract_id}
    if sla_cutoff_time:
        patch["sla_cutoff_time"] = sla_cutoff_time
    if preset_id:
        patch["preset_id"] = preset_id
    resp = (
        client.table("property_feeds")
        .update(patch)
        .eq("id", feed_id)
        .execute()
    )
    # Keep property-level pointer in sync for engine property lookups
    client.table("properties").update({"active_contract_id": contract_id}).eq(
        "property_id", property_id
    ).execute()
    data = resp.data
    if isinstance(data, list) and data and isinstance(data[0], dict):
        return data[0]
    if isinstance(data, dict):
        return data
    return patch


def upsert_property_feed(
    *,
    property_id: str,
    feed_category: str,
    preset_id: str,
    schedule: Optional[str] = None,
    sla_cutoff_time: Optional[str] = None,
    s3_prefix: Optional[str] = None,
    feed_id: Optional[str] = None,
) -> dict[str, Any]:
    """
    Upsert a property feed on unique (property_id, feed_category).

    Preset switches update the existing POS/PMS/… row in place — never insert
    a second category row that would trip uq_property_feed.
    """
    client = get_supabase()
    payload: dict[str, Any] = {
        "property_id": property_id,
        "feed_category": feed_category,
        "preset_id": preset_id,
    }
    if feed_id:
        payload["id"] = feed_id
    if schedule is not None:
        payload["schedule"] = schedule
    if sla_cutoff_time is not None:
        payload["sla_cutoff_time"] = sla_cutoff_time
    if s3_prefix is not None:
        payload["s3_prefix"] = s3_prefix

    resp = (
        client.table("property_feeds")
        .upsert(payload, on_conflict="property_id,feed_category")
        .execute()
    )
    data = resp.data
    if isinstance(data, list) and data and isinstance(data[0], dict):
        return data[0]
    if isinstance(data, dict):
        return data
    return payload


def update_feed_preset(
    *,
    feed_id: str,
    property_id: str,
    feed_category: str,
    preset_id: str,
) -> dict[str, Any]:
    """Update system preset for an existing feed (category-scoped upsert)."""
    return upsert_property_feed(
        property_id=property_id,
        feed_category=feed_category,
        preset_id=preset_id,
        feed_id=feed_id,
    )


def update_property_sla_fields(
    property_id: str,
    *,
    timezone: Optional[str] = None,
    sla_cutoff_time: Optional[str] = None,
    grace_period_minutes: Optional[int] = None,
    alert_emails: Optional[list[str]] = None,
    slack_channel: Optional[str] = None,
) -> None:
    patch: dict[str, Any] = {}
    if timezone is not None:
        patch["timezone"] = timezone
    if sla_cutoff_time is not None:
        patch["sla_cutoff_time"] = sla_cutoff_time
    if grace_period_minutes is not None:
        patch["sla_grace_period_mins"] = grace_period_minutes
    if alert_emails is not None:
        patch["alert_emails"] = alert_emails
    if slack_channel is not None:
        patch["slack_channel"] = slack_channel
    if not patch:
        return
    client = get_supabase()
    client.table("properties").update(patch).eq("property_id", property_id).execute()


def insert_run_audit_note(
    *,
    run_id: str,
    operator_id: str,
    content: str,
    note_type: str,
    gate_number: Optional[int] = None,
    rule_id: Optional[str] = None,
) -> dict[str, Any]:
    """Insert a run audit note; DB trigger projects into property_journal_entries."""
    client = get_supabase()
    payload: dict[str, Any] = {
        "run_id": run_id,
        "operator_id": operator_id,
        "content": content,
        "note_type": note_type,
    }
    if gate_number is not None:
        payload["gate_number"] = gate_number
    if rule_id:
        payload["rule_id"] = rule_id
    resp = client.table("run_audit_notes").insert(payload).execute()
    data = resp.data
    if isinstance(data, list) and data and isinstance(data[0], dict):
        return data[0]
    if isinstance(data, dict):
        return data
    return payload


def insert_property_journal_entry(
    *,
    property_id: str,
    operator_id: str,
    content: str,
    note_type: str,
    customer_impact: str = "NONE",
    lifecycle_event: str = "NOTE_ADDED",
    run_id: Optional[str] = None,
    gate_number: Optional[int] = None,
    rule_id: Optional[str] = None,
    report_type: Optional[str] = None,
) -> dict[str, Any]:
    client = get_supabase()
    payload: dict[str, Any] = {
        "property_id": property_id,
        "operator_id": operator_id,
        "content": content,
        "note_type": note_type,
        "customer_impact": customer_impact,
        "lifecycle_event": lifecycle_event,
    }
    if run_id:
        payload["run_id"] = run_id
    if gate_number is not None:
        payload["gate_number"] = gate_number
    if rule_id:
        payload["rule_id"] = rule_id
    if report_type:
        payload["report_type"] = report_type
    resp = client.table("property_journal_entries").insert(payload).execute()
    data = resp.data
    if isinstance(data, list) and data and isinstance(data[0], dict):
        return data[0]
    if isinstance(data, dict):
        return data
    return payload


def fetch_property_journal_entries(
    property_id: str,
    *,
    note_type: Optional[str] = None,
    customer_impact: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    client = get_supabase()
    query = (
        client.table("property_journal_entries")
        .select("*")
        .eq("property_id", property_id)
        .order("created_at", desc=True)
        .range(offset, offset + max(limit, 1) - 1)
    )
    if note_type:
        query = query.eq("note_type", note_type)
    if customer_impact:
        query = query.eq("customer_impact", customer_impact)
    resp = query.execute()
    data = resp.data
    if isinstance(data, list):
        return [row for row in data if isinstance(row, dict)]
    return []
