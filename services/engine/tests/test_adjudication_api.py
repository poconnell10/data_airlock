"""
Adjudication API — evaluate persist + release state transition.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.gates.gate_2_anomaly import Gate2Report
from app.gates.gate_3_quality import Gate3Report
from app.gates.gate_4_revenue import Gate4Report
from app.main import DryRunResponse, app
from app.models.common import GateOutcome
from app.models.gate1 import FilenameTokens, Gate1Outcome, Gate1Report

client = TestClient(app)


def _minimal_dry_response() -> DryRunResponse:
    tokens = FilenameTokens(
        property="ESMA.MALAG",
        date="2026-08-11",
        report_type="sales_data",
        hash="a91f",
    )
    g1 = Gate1Report(
        overall_outcome=Gate1Outcome.HOLD_SET,
        outcome_reason="Atomic set incomplete",
        filename_tokens=tokens,
        evaluations=[],
        total_rows=3,
        bytes_read=128,
    )
    return DryRunResponse(
        run_id="11111111-2222-3333-4444-555555555555",
        timestamp=datetime.now(timezone.utc).isoformat(),
        property_id="ESMA.MALAG",
        filename="sales_data_ESMA.MALAG_2026-08-11__a91f.csv",
        path="raw/ESMA.MALAG/pos/sales_data_ESMA.MALAG_2026-08-11__a91f.csv",
        overall_outcome=GateOutcome.HOLD_SET,
        outcome_reason="Atomic set incomplete",
        gate1_report=g1,
        gate2_report=Gate2Report(
            overall_outcome=GateOutcome.PASS, outcome_reason="ok"
        ),
        gate3_report=Gate3Report(
            overall_outcome=GateOutcome.PASS, outcome_reason="ok"
        ),
        gate4_report=Gate4Report(
            overall_outcome=GateOutcome.PASS, outcome_reason="ok"
        ),
    )


def test_evaluate_endpoint_persists_to_supabase():
    dry = _minimal_dry_response()
    inserted_rows: list[dict[str, Any]] = []

    async def _fake_dry(_req: Any) -> DryRunResponse:
        return dry

    def _capture_insert(row: dict[str, Any]) -> dict[str, Any]:
        inserted_rows.append(row)
        return row

    with patch("app.main.airlock_dry_run", side_effect=_fake_dry), patch(
        "app.main.is_supabase_configured", return_value=True
    ), patch(
        "app.main._hydrate_contract",
        return_value=({"feed_category": "pos"}, None, None),
    ), patch(
        "app.main.insert_run_report", side_effect=_capture_insert
    ):
        res = client.post(
            "/api/v1/airlock/evaluate",
            json={
                "property_id": "ESMA.MALAG",
                "filename": "sales_data_ESMA.MALAG_2026-08-11__a91f.csv",
                "path": "raw/ESMA.MALAG/pos/sales_data_ESMA.MALAG_2026-08-11__a91f.csv",
                "payload_text": "check_id|amount\n1|10\n",
                "contract_json": {"feed_category": "pos"},
                "feed_category": "POS",
                "persist_run": True,
            },
        )

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["run_id"] == dry.run_id
    assert body["persisted"] is True
    assert len(inserted_rows) == 1
    row = inserted_rows[0]
    assert row["property_id"] == "ESMA.MALAG"
    assert row["report_type"] == "sales_data"
    assert row["overall_outcome"] == "HOLD_SET"
    assert row["feed_category"] == "pos"


def test_evaluate_persist_failure_message():
    dry = _minimal_dry_response()

    async def _fake_dry(_req: Any) -> DryRunResponse:
        return dry

    with patch("app.main.airlock_dry_run", side_effect=_fake_dry), patch(
        "app.main.is_supabase_configured", return_value=True
    ), patch(
        "app.main._hydrate_contract",
        return_value=({"feed_category": "pos"}, None, None),
    ), patch(
        "app.main.insert_run_report",
        side_effect=RuntimeError(
            "PGRST204: Could not find the 'quarantine_manifest' column"
        ),
    ):
        res = client.post(
            "/api/v1/airlock/evaluate",
            json={
                "property_id": "ESMA.MALAG",
                "filename": "sales_data_ESMA.MALAG_2026-08-11__a91f.csv",
                "payload_text": "check_id|amount\n1|10\n",
                "contract_json": {"feed_category": "pos"},
                "persist_run": True,
            },
        )

    assert res.status_code == 502
    detail = res.json()["detail"]
    assert detail.startswith("Failed to persist run report to adjudication queue:")
    assert "Gate evaluation succeeded but run_report persist failed" not in detail


def test_release_run_state_transition():
    run_id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    seed = {
        "run_id": run_id,
        "property_id": "ESMA.MALAG",
        "report_type": "sales_data",
        "business_date": "2026-08-11",
        "overall_outcome": "HOLD_SET",
        "feed_category": "pos",
        "released_by": None,
        "released_at": None,
    }
    released_at = datetime.now(timezone.utc).isoformat()

    def _release(rid: str, *, operator_id: str, reason: str = "") -> dict[str, Any]:
        assert rid == run_id
        assert operator_id == "op_402"
        return {
            **seed,
            "overall_outcome": "RELEASED_TO_ETL",
            "released_by": operator_id,
            "released_at": released_at,
            "outcome_reason": reason,
        }

    with patch(
        "app.main.is_supabase_configured", return_value=True
    ), patch("app.main.fetch_run_report_by_id", return_value=seed), patch(
        "app.main.release_run_report", side_effect=_release
    ):
        res = client.post(
            f"/api/v1/airlock/runs/{run_id}/release",
            json={
                "operator_id": "op_402",
                "reason": "Verified manual drop",
            },
        )

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["success"] is True
    assert body["status"] == "RELEASED_TO_ETL"
    assert body["released_by"] == "op_402"
    assert body["released_at"]
    assert body["event"] == "airlock.run.released"
