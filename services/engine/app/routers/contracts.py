"""
Airlock contract persistence API.

POST /api/v1/airlock/contracts — upsert published contract for (property_id, feed_id)
GET  /api/v1/airlock/contracts/{property_id}/{feed_id} — fetch or preset fallback
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, HTTPException

from app.db import (
    fetch_airlock_contract,
    fetch_property_feed,
    is_supabase_configured,
    link_feed_active_contract,
    normalize_ingestion_contract_version,
    update_feed_preset,
    update_property_sla_fields,
    upsert_airlock_contract,
    upsert_ingestion_contract,
)
from app.models.contracts import AirlockContractPayload, AirlockContractResponse

router = APIRouter(prefix="/api/v1/airlock/contracts", tags=["contracts"])

# Minimal vendor templates when no published row exists yet.
_PRESET_DEFAULTS: dict[str, dict[str, Any]] = {
    "onesait": {
        "filename_pattern": (
            r"^(?P<report_type>[a-z_]+)_(?P<property>[A-Z]{4}\.[A-Z]{5})_"
            r"(?P<date>\d{4}-\d{2}-\d{2})__(?P<hash>[a-f0-9]+)\.csv$"
        ),
        "delimiter": "|",
        "encoding": "utf-8",
        "atomic_set_members": ["headers_data", "sales_data", "payments_data"],
        "hold_set_enabled": True,
        "zscore_threshold": 3.0,
        "rolling_window_days": 30,
        "required_columns": ["check_id", "business_date", "total_amount"],
        "tolerance_eur": 0.01,
    },
    "opera": {
        "filename_pattern": (
            r"^(?P<property>[A-Z]{4}\.[A-Z]{5})_(?P<report_type>[A-Z_]+)_"
            r"(?P<date>\d{8})\.txt$"
        ),
        "delimiter": ",",
        "encoding": "iso-8859-1",
        "atomic_set_members": ["stat_daily"],
        "hold_set_enabled": True,
        "zscore_threshold": 2.5,
        "rolling_window_days": 30,
        "required_columns": ["RESV_NAME_ID", "business_date", "total_amount"],
        "tolerance_eur": 0.05,
    },
}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_time(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    text = str(raw).strip()
    if len(text) == 5:
        return f"{text}:00"
    return text


def _preset_contract(
    *,
    property_id: str,
    feed_id: str,
    feed_category: Optional[str],
    system_preset: str,
) -> AirlockContractResponse:
    defaults = _PRESET_DEFAULTS.get(system_preset) or _PRESET_DEFAULTS["onesait"]
    contract_yaml = {
        "version": "2.0",
        "metadata": {
            "property_id": property_id,
            "feed_category": (feed_category or "pos").upper(),
            "system_preset": system_preset,
            "updated_at": _utc_now_iso(),
        },
        "gates": {
            "gate1_extraction": {
                "filename_pattern": defaults["filename_pattern"],
                "delimiter": defaults["delimiter"],
                "encoding": defaults["encoding"],
                "atomic_set_members": defaults["atomic_set_members"],
                "hold_set_enabled": defaults["hold_set_enabled"],
            },
            "gate2_anomaly": {
                "zscore_threshold": defaults["zscore_threshold"],
                "rolling_window_days": defaults["rolling_window_days"],
            },
            "gate3_quality": {
                "required_columns": defaults["required_columns"],
            },
            "gate4_revenue": {
                "tolerance_eur": defaults["tolerance_eur"],
            },
        },
    }
    return AirlockContractResponse(
        id="preset",
        property_id=property_id,
        feed_id=feed_id,
        feed_category=feed_category,
        system_preset=system_preset,
        status="draft",
        version="2.0",
        updated_at=contract_yaml["metadata"]["updated_at"],
        ingestion_contract_id=None,
        contract_yaml=contract_yaml,
        engine_contract={},
        source="preset_fallback",
    )


def _row_to_response(row: dict[str, Any], *, source: str = "database") -> AirlockContractResponse:
    updated = row.get("updated_at") or _utc_now_iso()
    if hasattr(updated, "isoformat"):
        updated = updated.isoformat()
    return AirlockContractResponse(
        id=str(row.get("id") or ""),
        property_id=str(row.get("property_id") or ""),
        feed_id=str(row.get("feed_id") or ""),
        feed_category=row.get("feed_category"),
        system_preset=str(row.get("system_preset") or ""),
        status=str(row.get("status") or "published"),
        version=str(row.get("version") or "2.0"),
        updated_at=str(updated),
        ingestion_contract_id=row.get("ingestion_contract_id"),
        contract_yaml=row.get("contract_yaml")
        if isinstance(row.get("contract_yaml"), dict)
        else {},
        engine_contract=row.get("engine_contract")
        if isinstance(row.get("engine_contract"), dict)
        else {},
        source=source,
    )


@router.post("", response_model=AirlockContractResponse)
def upsert_contract(payload: AirlockContractPayload) -> AirlockContractResponse:
    """
    Upsert the published Airlock contract for (property_id, feed_id).

    Also syncs engine-compatible JSON into ingestion_contracts and points
    property_feeds.active_contract_id at the active row.
    """
    if not is_supabase_configured():
        raise HTTPException(
            status_code=503,
            detail="Supabase is not configured on the engine.",
        )

    feed = fetch_property_feed(payload.feed_id)
    if not feed:
        raise HTTPException(
            status_code=404,
            detail=f"Feed '{payload.feed_id}' not found",
        )
    if str(feed.get("property_id")) != payload.property_id:
        raise HTTPException(
            status_code=400,
            detail="feed_id does not belong to property_id",
        )

    feed_category = payload.feed_category or feed.get("feed_category")
    system_preset = payload.system_preset or feed.get("preset_id") or "custom"
    sla = _normalize_time(payload.sla_cutoff_time)

    engine_doc = (
        payload.engine_contract
        if isinstance(payload.engine_contract, dict) and payload.engine_contract
        else payload.contract_yaml
    )

    existing_ing = payload.existing_ingestion_contract_id or feed.get(
        "active_contract_id"
    )
    # Prefer explicit epoch-ms revision tokens; never send INT4-overflowing
    # values as untyped strings. TIMESTAMPTZ fields stay ISO-8601.
    version_token = normalize_ingestion_contract_version(
        payload.version
        if payload.version is not None
        else payload.contract_version
        if payload.contract_version is not None
        else payload.updated_at_ms
        if payload.updated_at_ms is not None
        else payload.created_at_ms
    )

    try:
        ingestion = upsert_ingestion_contract(
            profile_id=system_preset,
            file_format=payload.file_format or "delimited_text",
            contract_yaml=engine_doc,
            existing_id=str(existing_ing) if existing_ing else None,
            version=version_token,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=502,
            detail=f"ingestion_contracts upsert failed: {exc}",
        ) from exc

    ingestion_id = str(ingestion.get("id") or "")
    if not ingestion_id:
        raise HTTPException(
            status_code=502,
            detail="ingestion_contracts upsert returned no id",
        )

    try:
        # Preset switches must update the existing category feed in-place
        # (uq_property_feed is unique on property_id, feed_category).
        update_feed_preset(
            feed_id=payload.feed_id,
            property_id=payload.property_id,
            feed_category=str(feed_category or feed.get("feed_category") or "pos"),
            preset_id=system_preset,
        )
        link_feed_active_contract(
            feed_id=payload.feed_id,
            property_id=payload.property_id,
            contract_id=ingestion_id,
            sla_cutoff_time=sla,
            preset_id=system_preset,
        )
        update_property_sla_fields(
            payload.property_id,
            timezone=payload.timezone,
            sla_cutoff_time=sla,
            grace_period_minutes=payload.grace_period_minutes,
            alert_emails=payload.alert_emails,
            slack_channel=payload.slack_channel,
        )
    except Exception as exc:  # noqa: BLE001
        detail = str(exc)
        if "uq_property_feed" in detail:
            detail = (
                "Feed preset update collided with uq_property_feed. "
                "Ensure only one feed exists per (property_id, feed_category) "
                f"and retry. Underlying error: {exc}"
            )
        raise HTTPException(
            status_code=502,
            detail=f"Failed to link feed contract: {detail}",
        ) from exc

    try:
        row = upsert_airlock_contract(
            {
                "property_id": payload.property_id,
                "feed_id": payload.feed_id,
                "feed_category": feed_category,
                "system_preset": system_preset,
                "status": "published",
                "version": str(
                    (payload.contract_yaml or {}).get("version") or "2.0"
                ),
                "contract_yaml": payload.contract_yaml or {},
                "engine_contract": engine_doc,
                "ingestion_contract_id": ingestion_id,
            }
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=502,
            detail=f"airlock_contracts upsert failed: {exc}",
        ) from exc

    return _row_to_response(row, source="database")


@router.get("/{property_id}/{feed_id}", response_model=AirlockContractResponse)
def get_contract(property_id: str, feed_id: str) -> AirlockContractResponse:
    """Fetch active contract; fall back to system preset defaults when missing."""
    if not is_supabase_configured():
        raise HTTPException(
            status_code=503,
            detail="Supabase is not configured on the engine.",
        )

    row = fetch_airlock_contract(property_id, feed_id)
    if row:
        return _row_to_response(row, source="database")

    feed = fetch_property_feed(feed_id)
    preset = "onesait"
    category: Optional[str] = None
    if feed and str(feed.get("property_id")) == property_id:
        preset = str(feed.get("preset_id") or "onesait")
        category = feed.get("feed_category")
    elif feed and str(feed.get("property_id")) != property_id:
        raise HTTPException(
            status_code=400,
            detail="feed_id does not belong to property_id",
        )

    return _preset_contract(
        property_id=property_id,
        feed_id=feed_id,
        feed_category=category,
        system_preset=preset,
    )
