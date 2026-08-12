"""
Production landmines — high-signal Gate 1–4 edge-case suite.

These cases encode real hospitality extract failure modes that float past
naive parsers: split-tender cents, Opera trailers, cold-start z-scores,
cross-midnight atomic holds, latin-1 encoding drift, and numeric poison.
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from app.gates.gate_1_extraction import evaluate_gate_1
from app.gates.gate_2_anomaly import evaluate_gate_2
from app.gates.gate_3_quality import evaluate_gate_3
from app.gates.gate_4_revenue import evaluate_gate_4
from app.models.common import GateOutcome
from app.models.gate1 import Gate1Outcome


# ---------------------------------------------------------------------------
# Shared contract helpers
# ---------------------------------------------------------------------------


def _onesait_style_contract(**overrides):
    contract = {
        "filename": {
            "pattern": (
                r"^(?P<property>[A-Z0-9.]+)_(?P<date>\d{8})_"
                r"(?P<report_type>headers_data|sales_data|payments_data)\.csv$"
            ),
        },
        "file_format": {
            "encoding": "utf-8",
            "delimiter": ",",
        },
        "row_classification": {
            "header_patterns": [r"^check_id,"],
            "footer_patterns": [
                r"^\*\*\* END OF REPORT \*\*\*",
                r"^TOTAL:",
            ],
            "ignore_patterns": [r"^\s*$"],
        },
        "atomic_set": {
            "is_multi_file": True,
            "required_endpoints": [
                "headers_data",
                "sales_data",
                "payments_data",
            ],
        },
    }
    contract.update(overrides)
    return contract


# ---------------------------------------------------------------------------
# a) Split-Tender Precision (Gate 4)
# ---------------------------------------------------------------------------


def test_split_tender_precision_gate4_passes_within_cent():
    """$33.33 + $33.33 + $33.34 must balance a $100.00 check at $0.01 tol."""
    df = pl.DataFrame(
        {
            "check_total": [100.00, None, None],
            "tender_payment": [33.33, 33.33, 33.34],
            "net_sales": [100.00, None, None],
        }
    )
    report = evaluate_gate_4(
        df,
        {
            "max_variance": 0.01,
            "header_vs_line_balance": False,
            "sales_vs_tender_balance": True,
            "net_sales_columns": ["net_sales"],
            "tender_columns": ["tender_payment"],
        },
    )
    assert report.overall_outcome == GateOutcome.PASS
    assert report.tender_payments == pytest.approx(100.00)
    assert report.net_sales == pytest.approx(100.00)
    tender_eval = next(
        e for e in report.evaluations if e.rule_name == "sales_vs_tender_balance"
    )
    assert tender_eval.passed is True
    assert tender_eval.details["variance"] <= 0.01


# ---------------------------------------------------------------------------
# b) Trailing Summary Footers (Gate 1)
# ---------------------------------------------------------------------------


def test_trailing_summary_footers_excluded_from_data_row_counts():
    """Opera-style END OF REPORT / TOTAL: trailers must not count as data."""
    body = (
        "check_id,amount,guest\n"
        "1,10.00,Ada\n"
        "2,20.00,Grace\n"
        "3,30.00,Alan\n"
        "TOTAL: 60.00\n"
        "*** END OF REPORT ***\n"
        "TRL|COUNT|3\n"
    )
    contract = _onesait_style_contract()
    contract["row_classification"]["footer_patterns"] = [
        r"^\*\*\* END OF REPORT \*\*\*",
        r"^TOTAL:",
        r"^TRL\|COUNT\|",
    ]
    contract["row_classification"]["row_count_declaration"] = {
        "pattern": r"^TRL\|COUNT\|(?P<declared_row_count>\d+)",
    }

    report = evaluate_gate_1(
        raw_bytes=body.encode("utf-8"),
        filename="ESMA.MALAG_20260810_headers_data.csv",
        path="landing/ESMA.MALAG/20260810/ESMA.MALAG_20260810_headers_data.csv",
        contract_yaml=contract,
        present_batch_filenames=[
            "ESMA.MALAG_20260810_headers_data.csv",
            "ESMA.MALAG_20260810_sales_data.csv",
            "ESMA.MALAG_20260810_payments_data.csv",
        ],
    )

    line_eval = next(e for e in report.evaluations if e.rule_name == "line_conservation")
    assert line_eval.passed is True
    assert line_eval.details["data_lines"] == 3
    assert line_eval.details["footer_lines"] >= 2
    assert "TOTAL:" not in str(line_eval.details.get("data_lines"))
    # Footers excluded: data_lines matches declared 3
    assert line_eval.details["declared_count"] == 3


# ---------------------------------------------------------------------------
# c) Cold-Start Zero Std-Dev (Gate 2)
# ---------------------------------------------------------------------------


def test_cold_start_zero_stddev_does_not_raise():
    """< min_historical_samples peers must skip z-score without ZeroDivisionError."""
    history = [
        {
            "business_date": "2026-08-03",  # same Monday as 2026-08-10
            "overall_outcome": "PASS",
            "accepted_rows": 100,
            "property_id": "NEW.PROP",
            "report_type": "headers_data",
        },
        {
            "business_date": "2026-07-27",
            "overall_outcome": "PASS",
            "accepted_rows": 100,  # identical → std would be 0
            "property_id": "NEW.PROP",
            "report_type": "headers_data",
        },
    ]

    report = evaluate_gate_2(
        run_reports_history=history,
        current_row_count=250,  # would explode if std=0 division applied
        business_date="2026-08-10",
        max_z_score=3.0,
        property_id="NEW.PROP",
        report_type="headers_data",
        as_of=date(2026, 8, 11),
        min_historical_samples=7,
    )

    assert report.baseline_n < 7
    z_eval = next(e for e in report.evaluations if e.rule_name == "G2_ZSCORE_ANOMALY")
    assert z_eval.passed is True
    assert z_eval.details.get("cold_start") is True
    assert report.overall_outcome in {GateOutcome.PASS, GateOutcome.FLAG}


# ---------------------------------------------------------------------------
# d) Cross-Midnight Atomic Set Hold (Gate 1)
# ---------------------------------------------------------------------------


def test_cross_midnight_atomic_set_hold_uses_business_date_not_calendar():
    """2/3 files for biz date 2026-08-10 → HOLD_SET even if run on 2026-08-11."""
    body = "check_id,amount\n1,10.00\n2,20.00\n"
    contract = _onesait_style_contract()
    # Processed on calendar 2026-08-11; filename carries business date 20260810
    report = evaluate_gate_1(
        raw_bytes=body.encode("utf-8"),
        filename="ESMA.MALAG_20260810_headers_data.csv",
        path="landing/ESMA.MALAG/20260810/ESMA.MALAG_20260810_headers_data.csv",
        contract_yaml=contract,
        present_batch_filenames=[
            "ESMA.MALAG_20260810_headers_data.csv",
            "ESMA.MALAG_20260810_sales_data.csv",
            # payments_data intentionally missing
        ],
    )

    assert report.overall_outcome == Gate1Outcome.HOLD_SET
    assert report.filename_tokens.date == "20260810"
    atomic = next(e for e in report.evaluations if e.rule_name == "atomic_set")
    assert atomic.details.get("hold") is True
    assert "payments_data" in atomic.details.get("missing_endpoints", [])


# ---------------------------------------------------------------------------
# e) Non-UTF8 Encoding Shifts (Gate 1)
# ---------------------------------------------------------------------------


def test_non_utf8_encoding_shift_rejects_with_byte_position():
    """ISO-8859-1 0xFC ('ü' in Müller) under utf-8 contract → REJECT_FILE."""
    # "Müller" with latin-1 ü (0xFC) — invalid UTF-8 continuation
    raw = b"check_id,guest\n1,M\xfcller\n"
    assert b"\xfc" in raw

    contract = _onesait_style_contract()
    report = evaluate_gate_1(
        raw_bytes=raw,
        filename="ESMA.MALAG_20260810_headers_data.csv",
        path="landing/ESMA.MALAG/20260810/ESMA.MALAG_20260810_headers_data.csv",
        contract_yaml=contract,
        present_batch_filenames=[
            "ESMA.MALAG_20260810_headers_data.csv",
            "ESMA.MALAG_20260810_sales_data.csv",
            "ESMA.MALAG_20260810_payments_data.csv",
        ],
    )

    assert report.overall_outcome == Gate1Outcome.REJECT_FILE
    phys = next(e for e in report.evaluations if e.rule_name == "physical_integrity")
    assert phys.passed is False
    assert phys.details.get("error_start") is not None
    assert phys.details.get("offending_byte") == "fc"
    assert "byte" in phys.message.lower() or "decode" in phys.message.lower()


# ---------------------------------------------------------------------------
# f) Mid-Stream String Poisoning in Numeric Column (Gate 3)
# ---------------------------------------------------------------------------


def test_midstream_string_poison_in_numeric_column_quarantines():
    """Buried 'ERR' in an amount column must yield QUARANTINE_FILE."""
    df = pl.DataFrame(
        {
            "check_id": ["A1", "A2", "A3", "A4"],
            "amount": ["10.00", "20.50", "ERR", "5.00"],
        }
    )
    report = evaluate_gate_3(
        df,
        {
            "required_columns": ["check_id", "amount"],
            "numeric_columns": ["amount"],
            "numeric_ranges": [
                {"column": "amount", "min_value": 0, "max_value": 100000}
            ],
        },
    )

    assert report.overall_outcome == GateOutcome.QUARANTINE_FILE
    poison = next(
        e for e in report.evaluations if e.rule_name == "numeric_column_integrity"
    )
    assert poison.passed is False
    failures = poison.details.get("failures") or []
    assert any(
        f.get("poison_value") == "ERR" and f.get("column") == "amount"
        for f in failures
    )
