"""Property Journal API — property-level operational timeline."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from app.db import (
    fetch_property_journal_entries,
    fetch_run_report_by_id,
    insert_property_journal_entry,
    insert_run_audit_note,
    is_supabase_configured,
)
from app.models.journal import (
    AuditNoteResponse,
    CreateAuditNoteRequest,
    CreateJournalEntryRequest,
    JournalEntry,
)

router = APIRouter(tags=["journal"])


def _row_to_entry(row: dict) -> JournalEntry:
    return JournalEntry(
        journal_id=str(row.get("journal_id") or ""),
        property_id=str(row.get("property_id") or ""),
        run_id=str(row["run_id"]) if row.get("run_id") else None,
        gate_number=row.get("gate_number"),
        rule_id=str(row["rule_id"]) if row.get("rule_id") else None,
        operator_id=str(row.get("operator_id") or ""),
        note_type=str(row.get("note_type") or "NOTE_ADDED"),
        customer_impact=str(row.get("customer_impact") or "NONE"),
        lifecycle_event=str(row.get("lifecycle_event") or "NOTE_ADDED"),
        content=str(row.get("content") or ""),
        report_type=str(row["report_type"]) if row.get("report_type") else None,
        created_at=str(row.get("created_at") or ""),
    )


@router.get(
    "/api/v1/properties/{property_id}/journal",
    response_model=list[JournalEntry],
)
def get_property_journal(
    property_id: str,
    note_type: Optional[str] = Query(default=None),
    customer_impact: Optional[str] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[JournalEntry]:
    if not is_supabase_configured():
        raise HTTPException(status_code=503, detail="Supabase is not configured")
    try:
        rows = fetch_property_journal_entries(
            property_id,
            note_type=note_type,
            customer_impact=customer_impact,
            limit=limit,
            offset=offset,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return [_row_to_entry(row) for row in rows]


@router.post(
    "/api/v1/properties/{property_id}/journal",
    response_model=JournalEntry,
)
def create_property_journal_entry(
    property_id: str,
    body: CreateJournalEntryRequest,
) -> JournalEntry:
    if not is_supabase_configured():
        raise HTTPException(status_code=503, detail="Supabase is not configured")
    try:
        row = insert_property_journal_entry(
            property_id=property_id,
            operator_id=body.operator_id,
            content=body.content.strip(),
            note_type=body.note_type,
            customer_impact=body.customer_impact,
            lifecycle_event=body.lifecycle_event,
            run_id=body.run_id,
            gate_number=body.gate_number,
            rule_id=body.rule_id,
            report_type=body.report_type,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return _row_to_entry(row)


@router.post(
    "/api/v1/airlock/runs/{run_id}/audit-notes",
    response_model=AuditNoteResponse,
)
def create_run_audit_note(
    run_id: str,
    body: CreateAuditNoteRequest,
) -> AuditNoteResponse:
    """
    Persist an operator note on a run.
    DB trigger mirrors the note into property_journal_entries.
    """
    if not is_supabase_configured():
        raise HTTPException(status_code=503, detail="Supabase is not configured")

    run = fetch_run_report_by_id(run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")

    try:
        row = insert_run_audit_note(
            run_id=run_id,
            operator_id=body.operator_id,
            content=body.content.strip(),
            note_type=body.note_type,
            gate_number=body.gate_number,
            rule_id=body.rule_id,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    note_id = str(row.get("note_id") or "")
    return AuditNoteResponse(
        success=True,
        note_id=note_id,
        run_id=run_id,
        journal_projected=True,
        message="Audit note saved; projected to property journal",
    )
