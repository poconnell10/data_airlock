"""
Operational Adjudication API.

Fail-closed: Supabase required for queue/override; original run_reports
rows are never mutated — DECLARE_SHORT always appends PASS_OVERRIDDEN.
"""

from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException

from app.db import (
    count_run_reports_by_outcomes,
    fetch_adjudication_queue_rows,
    fetch_properties_by_ids,
    fetch_property_contract,
    fetch_run_report_by_id,
    insert_run_report,
    is_supabase_configured,
)
from app.models.adjudication import (
    AdjudicationItem,
    AdjudicationMetrics,
    OverrideRequest,
    OverrideResponse,
)

router = APIRouter(prefix="/api/v1/adjudication", tags=["adjudication"])

_BLOCKED = ("QUARANTINE_FILE", "HOLD_SET", "REJECT_FILE", "FLAG")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc_now_iso() -> str:
    return _utc_now().isoformat()


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, list):
        return {"evaluations": value}
    if value is None:
        return {}
    return {"value": value}


def _extract_s3_path(row: dict[str, Any]) -> Optional[str]:
    if row.get("s3_path"):
        return str(row["s3_path"])
    gates = _as_dict(row.get("gate_evaluations"))
    for key in ("s3_path", "path", "object_key", "uri"):
        if gates.get(key):
            return str(gates[key])
    file_identity = gates.get("file_identity")
    if isinstance(file_identity, dict):
        for key in ("s3_path", "path", "uri"):
            if file_identity.get(key):
                return str(file_identity[key])
    return None


def _normalize_gate_evaluations(value: Any) -> dict[str, Any]:
    return _as_dict(value)


def _row_to_item(
    row: dict[str, Any],
    prop: Optional[dict[str, Any]],
) -> AdjudicationItem:
    prop = prop or {}
    property_id = str(row.get("property_id") or "")
    name = (
        prop.get("property_name")
        or prop.get("name")
        or property_id
    )
    tz = prop.get("timezone") or prop.get("local_timezone")
    biz = row.get("business_date")
    created = row.get("created_at") or ""
    gates = _normalize_gate_evaluations(row.get("gate_evaluations"))
    feed = row.get("feed_category") or gates.get("feed_category")
    readiness = row.get("readiness_stats") or gates.get("readiness_stats")
    manifest = row.get("quarantine_manifest") or gates.get("quarantine_manifest") or []
    if not isinstance(manifest, list):
        manifest = []
    return AdjudicationItem(
        run_id=str(row.get("run_id") or ""),
        property_id=property_id,
        property_name=str(name),
        report_type=str(row.get("report_type") or ""),
        business_date=str(biz) if biz is not None else "",
        overall_outcome=str(row.get("overall_outcome") or ""),
        created_at=str(created),
        gate_evaluations=gates,
        s3_path=_extract_s3_path(row),
        timezone=str(tz) if tz else None,
        outcome_reason=(
            str(row["outcome_reason"]) if row.get("outcome_reason") else None
        ),
        feed_category=str(feed).lower() if feed else None,
        released_by=str(row["released_by"]) if row.get("released_by") else None,
        released_at=str(row["released_at"]) if row.get("released_at") else None,
        readiness_stats=readiness if isinstance(readiness, dict) else None,
        quarantine_manifest=[m for m in manifest if isinstance(m, dict)],
    )


@router.get("/queue", response_model=list[AdjudicationItem])
def get_adjudication_queue(limit: int = 100) -> list[AdjudicationItem]:
    if not is_supabase_configured():
        raise HTTPException(
            status_code=503,
            detail="Supabase is not configured on the engine.",
        )
    try:
        rows = fetch_adjudication_queue_rows(limit=max(1, min(limit, 500)))
        props = fetch_properties_by_ids(
            [str(r.get("property_id") or "") for r in rows]
        )
        return [_row_to_item(r, props.get(str(r.get("property_id") or ""))) for r in rows]
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=502,
            detail=f"Failed to load adjudication queue: {exc}",
        ) from exc


@router.get("/metrics", response_model=AdjudicationMetrics)
def get_adjudication_metrics() -> AdjudicationMetrics:
    if not is_supabase_configured():
        raise HTTPException(
            status_code=503,
            detail="Supabase is not configured on the engine.",
        )
    since = (_utc_now() - timedelta(hours=24)).isoformat()
    try:
        return AdjudicationMetrics(
            active_quarantines=count_run_reports_by_outcomes(["QUARANTINE_FILE"]),
            held_sets=count_run_reports_by_outcomes(["HOLD_SET"]),
            rejects=count_run_reports_by_outcomes(["REJECT_FILE"]),
            sla_breaches=count_run_reports_by_outcomes(["MISSING_DELIVERY"]),
            overrides_executed_today=count_run_reports_by_outcomes(
                ["PASS_OVERRIDDEN"], since_iso=since
            ),
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=502,
            detail=f"Failed to load adjudication metrics: {exc}",
        ) from exc


@router.post("/override", response_model=OverrideResponse)
async def post_adjudication_override(payload: OverrideRequest) -> OverrideResponse:
    if not is_supabase_configured():
        raise HTTPException(
            status_code=503,
            detail="Supabase is not configured on the engine.",
        )

    original = fetch_run_report_by_id(payload.run_id)
    if not original:
        raise HTTPException(
            status_code=404,
            detail=f"run_report '{payload.run_id}' not found",
        )
    if str(original.get("property_id") or "") != payload.property_id:
        raise HTTPException(
            status_code=400,
            detail="property_id does not match the original run_report.",
        )

    if payload.override_type == "DECLARE_SHORT":
        if str(original.get("overall_outcome") or "") not in _BLOCKED:
            raise HTTPException(
                status_code=400,
                detail=(
                    "DECLARE_SHORT only applies to QUARANTINE_FILE, "
                    "HOLD_SET, or REJECT_FILE runs."
                ),
            )
        return _declare_short(payload, original)

    if payload.override_type == "REDRIVE_VALIDATION":
        return await _redrive_validation(payload, original)

    raise HTTPException(status_code=400, detail="Unsupported override_type.")


def _declare_short(
    payload: OverrideRequest,
    original: dict[str, Any],
) -> OverrideResponse:
    ts = _utc_now()
    ts_compact = ts.strftime("%Y%m%dT%H%M%SZ")
    new_run_id = f"override_{payload.run_id}_{ts_compact}"

    gates = _normalize_gate_evaluations(original.get("gate_evaluations"))
    gates = copy.deepcopy(gates)
    gates["override_audit"] = {
        "operator": payload.operator_id,
        "type": "DECLARE_SHORT",
        "reason": payload.reason,
        "timestamp": ts.isoformat(),
        "original_run_id": payload.run_id,
        "original_outcome": original.get("overall_outcome"),
    }

    insert_row: dict[str, Any] = {
        "run_id": new_run_id,
        "property_id": payload.property_id,
        "report_type": original.get("report_type") or "unknown",
        "business_date": original.get("business_date"),
        "day_of_week": original.get("day_of_week")
        or str(ts.weekday()),
        "overall_outcome": "PASS_OVERRIDDEN",
        "gate_evaluations": gates,
    }
    # Optional columns — present on remote / newer migrations
    if original.get("total_read_rows") is not None:
        insert_row["total_read_rows"] = original.get("total_read_rows")
    if original.get("file_size_bytes") is not None:
        insert_row["file_size_bytes"] = original.get("file_size_bytes")
    if original.get("checksum_sha256"):
        insert_row["checksum_sha256"] = original.get("checksum_sha256")
    s3_path = _extract_s3_path(original)
    if s3_path:
        insert_row["s3_path"] = s3_path
    insert_row["outcome_reason"] = (
        f"DECLARE_SHORT by {payload.operator_id}: {payload.reason}"
    )

    try:
        insert_run_report(insert_row)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=502,
            detail=f"Failed to append PASS_OVERRIDDEN audit row: {exc}",
        ) from exc

    return OverrideResponse(
        success=True,
        new_run_id=new_run_id,
        status="PASS_OVERRIDDEN",
        override_type="DECLARE_SHORT",
        message="Override recorded as append-only PASS_OVERRIDDEN run_report.",
    )


async def _redrive_validation(
    payload: OverrideRequest,
    original: dict[str, Any],
) -> OverrideResponse:
    # Late import avoids circular dependency with main helpers.
    from app.main import (  # noqa: WPS433
        DryRunRequest,
        airlock_dry_run,
    )

    s3_path = _extract_s3_path(original)
    if not s3_path:
        raise HTTPException(
            status_code=400,
            detail=(
                "REDRIVE_VALIDATION requires a stored s3_path / file URI on "
                "the original run_report."
            ),
        )

    property_row, contract_row = fetch_property_contract(payload.property_id)
    if not property_row:
        raise HTTPException(
            status_code=404,
            detail=f"Property '{payload.property_id}' not found",
        )
    if not contract_row or not isinstance(contract_row.get("contract_yaml"), dict):
        raise HTTPException(
            status_code=400,
            detail="Active contract YAML is required for redrive validation.",
        )

    filename = urlparse(s3_path).path.rsplit("/", 1)[-1] or (
        f"{payload.property_id}_{original.get('report_type') or 'report'}.csv"
    )

    gates = _normalize_gate_evaluations(original.get("gate_evaluations"))
    batch = gates.get("present_batch_filenames") or gates.get("batch_filenames") or []
    if not isinstance(batch, list):
        batch = []

    try:
        report = await airlock_dry_run(
            DryRunRequest(
                property_id=payload.property_id,
                filename=filename,
                path=s3_path,
                s3_uri=s3_path if "://" in s3_path else None,
                fetch_uri=True,
                present_batch_filenames=[str(x) for x in batch],
                contract_json=contract_row["contract_yaml"],
            )
        )
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=502,
            detail=f"Redrive validation failed: {exc}",
        ) from exc

    return OverrideResponse(
        success=True,
        new_run_id=report.run_id,
        status=str(report.overall_outcome.value
                   if hasattr(report.overall_outcome, "value")
                   else report.overall_outcome),
        override_type="REDRIVE_VALIDATION",
        message=(
            f"REDRIVE_VALIDATION by {payload.operator_id}: {payload.reason}"
        ),
        gate_report=report.model_dump(mode="json"),
    )
