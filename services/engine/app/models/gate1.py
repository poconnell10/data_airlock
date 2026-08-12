"""Pydantic v2 models for Gate 1 (Extraction Contract) reports."""

from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class Gate1Outcome(str, Enum):
    PASS = "PASS"
    HOLD_SET = "HOLD_SET"
    QUARANTINE_FILE = "QUARANTINE_FILE"
    REJECT_FILE = "REJECT_FILE"


class FilenameTokens(BaseModel):
    report_type: Optional[str] = None
    property: Optional[str] = None
    date: Optional[str] = None
    hash: Optional[str] = None

    def as_dict(self) -> dict[str, str]:
        return {
            k: v
            for k, v in self.model_dump().items()
            if v is not None
        }


class Gate1SubEvaluation(BaseModel):
    rule_name: str
    passed: bool
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class Gate1Report(BaseModel):
    overall_outcome: Gate1Outcome
    filename_tokens: FilenameTokens = Field(default_factory=FilenameTokens)
    evaluations: list[Gate1SubEvaluation] = Field(default_factory=list)
    total_rows: int = 0
    bytes_read: int = 0
    outcome_reason: str = ""
