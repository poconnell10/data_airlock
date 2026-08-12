"""
Gate 1 — Extraction Contract (legacy API facade).

Delegates to the production engine in `gate1_extraction.py` and maps the
typed report into the historical Gate1Report shape used by dry-run / ingest.
"""

from __future__ import annotations

from typing import Any, Optional

from app.gates.gate1_extraction import evaluate_gate1_from_yaml
from app.models.gate1 import (
    FilenameTokens,
    Gate1Outcome,
    Gate1Report,
    Gate1SubEvaluation,
)
from app.models.gate1_contract import Gate1Report as TypedGate1Report


def evaluate_gate_1(
    raw_bytes: bytes,
    filename: str,
    path: str,
    contract_yaml: dict[str, Any],
    present_batch_filenames: Optional[list[str]] = None,
) -> Gate1Report:
    """
    Execute Gate 1 checks in fail-closed order.

    Outcome precedence: REJECT_FILE > QUARANTINE_FILE > HOLD_SET > PASS
    """
    typed = evaluate_gate1_from_yaml(
        contract_yaml if isinstance(contract_yaml, dict) else {},
        filename=filename,
        path=path or "",
        raw_bytes=raw_bytes if raw_bytes is not None else b"",
        present_batch_filenames=present_batch_filenames,
        present_batch_keys=present_batch_filenames,
        property_code=str(
            (contract_yaml or {}).get("property_code")
            or (contract_yaml or {}).get("property_id")
            or ""
        ),
    )
    return _to_legacy_report(typed)


def _to_legacy_report(report: TypedGate1Report) -> Gate1Report:
    status_map = {
        "PASS": Gate1Outcome.PASS,
        "REJECT": Gate1Outcome.REJECT_FILE,
        "QUARANTINE": Gate1Outcome.QUARANTINE_FILE,
        "HOLD": Gate1Outcome.HOLD_SET,
    }
    tokens = FilenameTokens(
        report_type=report.captured_tokens.get("report_type"),
        property=report.captured_tokens.get("property"),
        date=report.captured_tokens.get("date"),
        hash=report.captured_tokens.get("hash"),
    )
    evaluations = [
        Gate1SubEvaluation(
            rule_name=f.check_name,
            passed=f.passed,
            message=f.message,
            details=dict(f.details or {}),
        )
        for f in report.findings
    ]
    # Attach missing atomic members onto the atomic_set evaluation for callers
    if report.missing_atomic_members:
        for ev in evaluations:
            if ev.rule_name == "atomic_set":
                ev.details.setdefault(
                    "missing_endpoints", list(report.missing_atomic_members)
                )
                ev.details.setdefault("hold", report.status == "HOLD")

    return Gate1Report(
        overall_outcome=status_map.get(report.status, Gate1Outcome.QUARANTINE_FILE),
        filename_tokens=tokens,
        evaluations=evaluations,
        total_rows=int(report.total_rows or 0),
        bytes_read=int(report.bytes_read or 0),
        outcome_reason=report.outcome_reason
        or (report.findings[-1].message if report.findings else ""),
    )
