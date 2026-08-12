"""Pydantic v2 schemas for the Operational Adjudication Dashboard."""

from __future__ import annotations

from typing import Any, Dict, Literal, Optional

from pydantic import BaseModel, Field


class OverrideRequest(BaseModel):
    run_id: str = Field(..., min_length=1)
    property_id: str = Field(..., min_length=1)
    override_type: Literal["DECLARE_SHORT", "REDRIVE_VALIDATION"]
    reason: str = Field(..., min_length=10, max_length=500)
    operator_id: str = Field(..., min_length=1)


class AdjudicationItem(BaseModel):
    run_id: str
    property_id: str
    property_name: str = ""
    report_type: str = ""
    business_date: str = ""
    overall_outcome: str
    created_at: str = ""
    gate_evaluations: Dict[str, Any] = Field(default_factory=dict)
    s3_path: Optional[str] = None
    timezone: Optional[str] = None
    outcome_reason: Optional[str] = None
    feed_category: Optional[str] = None
    released_by: Optional[str] = None
    released_at: Optional[str] = None
    readiness_stats: Optional[Dict[str, Any]] = None
    quarantine_manifest: list[Dict[str, Any]] = Field(default_factory=list)


class OverrideResponse(BaseModel):
    success: bool
    new_run_id: Optional[str] = None
    status: Optional[str] = None
    override_type: str
    message: str = ""
    gate_report: Optional[Dict[str, Any]] = None


class AdjudicationMetrics(BaseModel):
    active_quarantines: int = 0
    held_sets: int = 0
    sla_breaches: int = 0
    overrides_executed_today: int = 0
    rejects: int = 0
