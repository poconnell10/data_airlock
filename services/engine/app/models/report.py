"""Execution run report models — readiness metrics + quarantine diagnostics."""

from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class QuarantineCategory(str, Enum):
    DATA_QUALITY_BUG = "DATA_QUALITY_BUG"
    OVERLAP_DRIFT = "OVERLAP_DRIFT"
    DUPLICATE_PAYLOAD = "DUPLICATE_PAYLOAD"
    VENDOR_CONFIG_CHANGE = "VENDOR_CONFIG_CHANGE"
    UNMAPPED_ENTITY = "UNMAPPED_ENTITY"
    UNBALANCED_REVENUE = "UNBALANCED_REVENUE"
    BUSINESS_EDGE_CASE = "BUSINESS_EDGE_CASE"
    FALSE_POSITIVE = "FALSE_POSITIVE"
    FROZEN_PERIOD_ATTEMPT = "FROZEN_PERIOD_ATTEMPT"


class ReadinessStats(BaseModel):
    total_rows: int = 0
    verified_rows: int = 0
    quarantined_rows: int = 0
    readiness_pct: float = Field(default=100.0, ge=0.0, le=100.0)
    quarantine_pct: float = Field(default=0.0, ge=0.0, le=100.0)


class QuarantineManifestItem(BaseModel):
    rule_id: str
    affected_rows: int
    row_indices: list[int] = Field(default_factory=list)
    suggested_category: QuarantineCategory
    user_category: Optional[QuarantineCategory] = None
    user_notes: Optional[str] = None
    message: str = ""
    sample_records: list[dict[str, Any]] = Field(default_factory=list)
    is_file_level: bool = False
    decision_guidance: str = ""


class ExecutionRunReport(BaseModel):
    """Persisted / API-facing execution report with readiness diagnostics."""

    run_id: str
    property_id: str
    business_date: str
    outcome: str  # RELEASED | FLAGGED | QUARANTINE | HOLD_SET | …
    report_type: str = ""
    feed_category: Optional[str] = None
    readiness_stats: ReadinessStats = Field(default_factory=ReadinessStats)
    quarantine_manifest: list[QuarantineManifestItem] = Field(default_factory=list)
    findings: list[dict[str, Any]] = Field(default_factory=list)
    gate_evaluations: dict[str, Any] = Field(default_factory=dict)
    s3_path: Optional[str] = None
    outcome_reason: Optional[str] = None


class ClassifyManifestPatch(BaseModel):
    rule_id: str = Field(..., min_length=1)
    user_category: QuarantineCategory
    user_notes: Optional[str] = Field(default=None, max_length=1000)


class ClassifyRequest(BaseModel):
    operator_id: str = Field(..., min_length=1)
    classifications: list[ClassifyManifestPatch] = Field(default_factory=list)


class ClassifyResponse(BaseModel):
    success: bool
    run_id: str
    quarantine_manifest: list[QuarantineManifestItem] = Field(default_factory=list)
    message: str = ""
