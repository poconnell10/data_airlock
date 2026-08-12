"""Property journal & run audit note models."""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

NoteType = Literal[
    "DECISION_REASON",
    "MEETING_REQUIRED",
    "VENDOR_ESCALATION",
    "THRESHOLD_ADJUSTMENT",
    "NOTE_ADDED",
]

CustomerImpact = Literal[
    "NONE",
    "LOW",
    "MEDIUM",
    "HIGH",
    "CUSTOMER_NOTIFIED",
]

LifecycleEvent = Literal[
    "OVERRIDE_RELEASE",
    "FILE_REJECTED",
    "THRESHOLD_TUNED",
    "VENDOR_TICKET_OPENED",
    "NOTE_ADDED",
    "RELEASE_OVERRIDE",
    "HARD_REJECT",
    "CONTRACT_THRESHOLD_TUNED",
]


class JournalEntry(BaseModel):
    journal_id: str
    property_id: str
    run_id: Optional[str] = None
    gate_number: Optional[int] = None
    rule_id: Optional[str] = None
    operator_id: str
    note_type: str
    customer_impact: str = "NONE"
    lifecycle_event: str
    content: str
    report_type: Optional[str] = None
    created_at: str = ""


class CreateJournalEntryRequest(BaseModel):
    operator_id: str = Field(..., min_length=1)
    content: str = Field(..., min_length=3, max_length=4000)
    note_type: NoteType = "NOTE_ADDED"
    customer_impact: CustomerImpact = "NONE"
    lifecycle_event: LifecycleEvent = "NOTE_ADDED"
    run_id: Optional[str] = None
    gate_number: Optional[int] = None
    rule_id: Optional[str] = None
    report_type: Optional[str] = None


class CreateAuditNoteRequest(BaseModel):
    operator_id: str = Field(..., min_length=1)
    content: str = Field(..., min_length=3, max_length=4000)
    note_type: NoteType = "DECISION_REASON"
    gate_number: Optional[int] = None
    rule_id: Optional[str] = None


class AuditNoteResponse(BaseModel):
    success: bool
    note_id: str
    run_id: str
    journal_projected: bool = True
    message: str = ""
