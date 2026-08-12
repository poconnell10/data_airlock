"""Gate 2 Anomaly Engine — four core invariant tests."""

from __future__ import annotations

from datetime import date

from app.gates.gate_2_anomaly import evaluate_gate_2
from app.models.common import GateOutcome

PROPERTY = "ESMA.MALAG"
REPORT = "pos_check_detail"


def _z_eval(report):
    return next(e for e in report.evaluations if e.rule_name == "G2_ZSCORE_ANOMALY")


def _eval(report, rule_id: str):
    return next(e for e in report.evaluations if e.rule_name == rule_id)


def test_gate2_deduplication_catches_duplicate_sha256() -> None:
    payload_hash = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    history = [
        {
            "run_id": "run-released-1",
            "property_id": PROPERTY,
            "report_type": REPORT,
            "business_date": "2026-08-10",
            "overall_outcome": "RELEASED_TO_ETL",
            "checksum_sha256": payload_hash,
            "accepted_rows": 100,
        }
    ]

    report = evaluate_gate_2(
        run_reports_history=history,
        current_row_count=100,
        business_date="2026-08-11",
        property_id=PROPERTY,
        report_type=REPORT,
        current_checksum=payload_hash,
        as_of=date(2026, 8, 12),
        min_historical_samples=7,
    )

    dup = _eval(report, "G2_DUPLICATE_PAYLOAD")
    assert dup.passed is False
    assert dup.details.get("suggested_category") == "DUPLICATE_PAYLOAD"
    assert "FILE_ALREADY_INGESTED" in dup.message
    assert report.overall_outcome == GateOutcome.QUARANTINE_FILE


def test_gate2_overlap_drift_detects_modified_payload_for_same_date() -> None:
    history = [
        {
            "run_id": "run-certified",
            "property_id": PROPERTY,
            "report_type": REPORT,
            "business_date": "2026-08-11",
            "overall_outcome": "PASS",
            "checksum_sha256": "a91f" + ("0" * 60),
            "accepted_rows": 100,
        }
    ]

    report = evaluate_gate_2(
        run_reports_history=history,
        current_row_count=100,
        business_date="2026-08-11",
        property_id=PROPERTY,
        report_type=REPORT,
        current_checksum="b82e" + ("0" * 60),
        as_of=date(2026, 8, 12),
        min_historical_samples=7,
    )

    drift = _eval(report, "G2_OVERLAP_DRIFT")
    assert drift.passed is False
    assert drift.details.get("suggested_category") == "OVERLAP_DRIFT"
    assert "OVERLAP_DRIFT_DETECTED" in drift.message
    assert report.overall_outcome == GateOutcome.FLAG


def test_gate2_frozen_window_quarantines_old_date() -> None:
    report = evaluate_gate_2(
        run_reports_history=[],
        current_row_count=50,
        business_date="2026-06-01",
        property_id=PROPERTY,
        report_type=REPORT,
        current_checksum="cccc" + ("0" * 60),
        frozen_date_threshold_days=30,
        as_of=date(2026, 8, 12),
        min_historical_samples=7,
    )

    frozen = _eval(report, "G2_FROZEN_WINDOW")
    assert frozen.passed is False
    assert frozen.rule_name == "G2_FROZEN_WINDOW"
    assert frozen.details.get("suggested_category") == "FROZEN_PERIOD_ATTEMPT"
    assert "FROZEN_WINDOW_VIOLATION" in frozen.message
    assert report.overall_outcome == GateOutcome.QUARANTINE_FILE


def test_gate2_zscore_flags_volume_spike() -> None:
    # 10 historical runs averaging ~1000 rows with σ≈50 → Z≈40 for 3000 rows
    history = []
    for i, rows in enumerate(
        [950, 1000, 1050, 980, 1020, 990, 1010, 970, 1030, 1000]
    ):
        day = 1 + i  # 2026-07-01 .. 2026-07-10
        history.append(
            {
                "run_id": f"hist-{i}",
                "property_id": PROPERTY,
                "report_type": REPORT,
                "business_date": f"2026-07-{day:02d}",
                "overall_outcome": "PASS",
                "accepted_rows": rows,
                "checksum_sha256": f"{i:064x}",
            }
        )

    report = evaluate_gate_2(
        run_reports_history=history,
        current_row_count=3000,
        business_date="2026-08-11",
        max_z_score=2.5,
        property_id=PROPERTY,
        report_type=REPORT,
        current_checksum="dddd" + ("0" * 60),
        as_of=date(2026, 8, 12),
        rolling_window_days=45,
        min_historical_samples=7,
    )

    z = _z_eval(report)
    assert z.passed is False
    assert z.details.get("suggested_category") == "FALSE_POSITIVE"
    assert "Z=" in z.message or "z" in z.message.lower()
    assert abs(float(z.details["z_score"])) > 2.5
    assert report.overall_outcome == GateOutcome.FLAG
