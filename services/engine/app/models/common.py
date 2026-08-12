"""Shared evaluation primitives across gates."""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class GateOutcome(str, Enum):
    PASS = "PASS"
    FLAG = "FLAG"
    HOLD_SET = "HOLD_SET"
    QUARANTINE_FILE = "QUARANTINE_FILE"
    REJECT_FILE = "REJECT_FILE"


class SubEvaluation(BaseModel):
    rule_name: str
    passed: bool
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


_OUTCOME_RANK = {
    GateOutcome.PASS: 0,
    GateOutcome.FLAG: 1,
    GateOutcome.HOLD_SET: 2,
    GateOutcome.QUARANTINE_FILE: 3,
    GateOutcome.REJECT_FILE: 4,
}


def escalate(current: GateOutcome, candidate: GateOutcome) -> GateOutcome:
    return candidate if _OUTCOME_RANK[candidate] > _OUTCOME_RANK[current] else current
