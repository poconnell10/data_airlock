"""Evaluation report enrichment — readiness stats + quarantine manifest.

Gate execution lives in `app.main` (`/dry-run`, `/evaluate`). Gate 2 runs
immediately after Gate 1 and is skipped when Gate 1 is REJECT_FILE or
QUARANTINE_FILE; findings + readiness are combined here into ExecutionRunReport.
"""

from __future__ import annotations

from typing import Any, Optional

from app.models.report import (
    ExecutionRunReport,
    QuarantineManifestItem,
    ReadinessStats,
)
from app.utils.quarantine_mapper import enrich_execution_diagnostics


def build_execution_enrichment(
    *,
    run_id: str,
    property_id: str,
    business_date: str,
    outcome: str,
    total_rows: int,
    gate_reports: dict[str, Any],
    payload_text: str = "",
    delimiter: str = ",",
    report_type: str = "",
    feed_category: Optional[str] = None,
    findings: Optional[list[dict[str, Any]]] = None,
    gate_evaluations: Optional[dict[str, Any]] = None,
    s3_path: Optional[str] = None,
    outcome_reason: Optional[str] = None,
) -> ExecutionRunReport:
    """
    Aggregate payload row counts, compute readiness percentages, and attach
    QuarantineManifestItem diagnostics to an ExecutionRunReport.
    """
    stats, manifest = enrich_execution_diagnostics(
        total_rows=total_rows,
        gate_reports=gate_reports,
        payload_text=payload_text,
        delimiter=delimiter,
        outcome=outcome,
        outcome_reason=outcome_reason or "",
    )
    return ExecutionRunReport(
        run_id=run_id,
        property_id=property_id,
        business_date=business_date,
        outcome=outcome,
        report_type=report_type,
        feed_category=feed_category,
        readiness_stats=stats,
        quarantine_manifest=manifest,
        findings=list(findings or []),
        gate_evaluations=dict(gate_evaluations or gate_reports or {}),
        s3_path=s3_path,
        outcome_reason=outcome_reason,
    )


def readiness_and_manifest_payloads(
    stats: ReadinessStats,
    manifest: list[QuarantineManifestItem],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    return (
        stats.model_dump(mode="json"),
        [m.model_dump(mode="json") for m in manifest],
    )
