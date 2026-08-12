"""Quarantine readiness metrics + classification API tests."""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app
from app.models.common import SubEvaluation
from app.models.report import QuarantineCategory
from app.utils.quarantine_mapper import (
    build_quarantine_manifest,
    compute_readiness_stats,
    enrich_execution_diagnostics,
    suggest_category,
)

client = TestClient(app)


def test_readiness_percentage_math():
    """1,000 rows with 20 Gate 3 ragged failures → 98% / 2%."""
    failed_indices = list(range(20))
    gate_reports = {
        "gate_3": {
            "evaluations": [
                {
                    "rule_name": "G3_RAGGED_ROW",
                    "passed": False,
                    "message": "Ragged row width mismatch on 20 rows.",
                    "details": {
                        "row_indices": failed_indices,
                        "affected_rows": 20,
                    },
                }
            ]
        }
    }
    stats, manifest = enrich_execution_diagnostics(
        total_rows=1000,
        gate_reports=gate_reports,
    )
    assert stats.total_rows == 1000
    assert stats.quarantined_rows == 20
    assert stats.verified_rows == 980
    assert stats.readiness_pct == 98.0
    assert stats.quarantine_pct == 2.0
    assert manifest[0].rule_id == "G3_RAGGED_ROW"
    assert suggest_category("G3_RAGGED_ROW") == QuarantineCategory.DATA_QUALITY_BUG

    # Direct math helper also agrees
    direct = compute_readiness_stats(1000, 20)
    assert direct.readiness_pct == 98.0
    assert direct.quarantine_pct == 2.0


def test_rule_id_category_mapping():
    failed = [3, 7, 11]
    gate_reports = {
        "gate_3": {
            "evaluations": [
                SubEvaluation(
                    rule_name="G3_TYPE_CAST_FAIL",
                    passed=False,
                    message="Non-numeric poison in amount column.",
                    details={
                        "row_indices": failed,
                        "affected_rows": 3,
                        "failures": [
                            {"row_index": 3, "poison_value": "ERR"},
                            {"row_index": 7, "poison_value": "N/A"},
                            {"row_index": 11, "poison_value": "x"},
                        ],
                    },
                )
            ]
        }
    }
    manifest = build_quarantine_manifest(gate_reports=gate_reports)
    assert len(manifest) == 1
    item = manifest[0]
    assert item.rule_id == "G3_TYPE_CAST_FAIL"
    assert item.suggested_category == QuarantineCategory.DATA_QUALITY_BUG
    assert item.row_indices == failed


def test_persist_operator_reclassification():
    run_id = "cccccccc-dddd-eeee-ffff-000000000001"
    seed_manifest = [
        {
            "rule_id": "G3_TYPE_CAST_FAIL",
            "affected_rows": 3,
            "row_indices": [3, 7, 11],
            "suggested_category": "DATA_QUALITY_BUG",
            "user_category": None,
            "message": "cast fail",
            "sample_records": [],
        }
    ]
    seed = {
        "run_id": run_id,
        "property_id": "ESMA.MALAG",
        "report_type": "sales_data",
        "business_date": "2026-08-11",
        "overall_outcome": "QUARANTINE_FILE",
        "quarantine_manifest": seed_manifest,
        "checksum_sha256": "abc",
    }

    captured: dict[str, Any] = {}

    def _classify(
        rid: str, *, quarantine_manifest: list, operator_id: str
    ) -> dict[str, Any]:
        assert rid == run_id
        assert operator_id == "op_402"
        captured["manifest"] = quarantine_manifest
        return {**seed, "quarantine_manifest": quarantine_manifest}

    with patch("app.main.is_supabase_configured", return_value=True), patch(
        "app.main.fetch_run_report_by_id", return_value=seed
    ), patch("app.main.classify_run_report", side_effect=_classify):
        res = client.post(
            f"/api/v1/airlock/runs/{run_id}/classify",
            json={
                "operator_id": "op_402",
                "classifications": [
                    {
                        "rule_id": "G3_TYPE_CAST_FAIL",
                        "user_category": "FALSE_POSITIVE",
                        "user_notes": "Known vendor glitch; safe to release",
                    }
                ],
            },
        )

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["success"] is True
    assert captured["manifest"][0]["user_category"] == "FALSE_POSITIVE"
    assert body["quarantine_manifest"][0]["user_category"] == "FALSE_POSITIVE"


def test_readiness_math_physical_decode_failure():
    """Decode / physical integrity failure → 0% ready, file-level manifest."""
    decode_msg = (
        "Physical integrity failed: decode error at byte 40 "
        "(utf-8 codec can't decode byte 0xfc)."
    )
    gate_reports = {
        "gate_1": {
            "evaluations": [
                {
                    "rule_name": "physical_integrity",
                    "passed": False,
                    "message": decode_msg,
                    "details": {
                        "bytes_read": 128,
                        "error_start": 40,
                        "offending_byte": "fc",
                    },
                }
            ]
        }
    }
    stats, manifest = enrich_execution_diagnostics(
        total_rows=0,
        gate_reports=gate_reports,
        outcome="REJECT_FILE",
    )
    assert stats.readiness_pct == 0.0
    assert stats.quarantine_pct == 100.0
    assert stats.verified_rows == 0
    assert stats.quarantined_rows == 1
    assert len(manifest) == 1
    item = manifest[0]
    assert item.rule_id == "G1_PHYSICAL_INTEGRITY"
    assert item.affected_rows == 0
    assert item.is_file_level is True
    assert item.suggested_category == QuarantineCategory.DATA_QUALITY_BUG
    assert item.message == decode_msg
    assert "physical integrity failure" in item.decision_guidance.lower()

    direct = compute_readiness_stats(0, 0, outcome="REJECT_FILE")
    assert direct.readiness_pct == 0.0
    assert direct.quarantine_pct == 100.0


def test_gate4_financial_imbalance_populates_manifest():
    """$150 sales vs $142.50 tender → UNBALANCED_REVENUE manifest item."""
    msg = (
        "Financial imbalance detected: Net sales $150.00 "
        "vs Tender payments $142.50. Variance: 7.50."
    )
    gate_reports = {
        "gate_4": {
            "overall_outcome": "REJECT_FILE",
            "evaluations": [
                {
                    "rule_name": "sales_vs_tender_balance",
                    "passed": False,
                    "message": msg,
                    "details": {
                        "net_sales": 150.0,
                        "tender_payments": 142.5,
                        "variance": 7.5,
                        "max_variance": 0.02,
                    },
                }
            ],
            "net_sales": 150.0,
            "tender_payments": 142.5,
        }
    }
    stats, manifest = enrich_execution_diagnostics(
        total_rows=12,
        gate_reports=gate_reports,
        outcome="REJECT_FILE",
        outcome_reason=msg,
    )
    assert stats.readiness_pct == 0.0
    assert len(manifest) >= 1
    item = next(
        m for m in manifest if m.rule_id == "G4_FINANCIAL_IMBALANCE"
    )
    assert item.suggested_category == QuarantineCategory.UNBALANCED_REVENUE
    assert "7.5" in item.message or "7.50" in item.message
    assert item.affected_rows == 0
    assert item.is_file_level is True
    assert "sales and payments" in item.decision_guidance.lower()
