"""run_reports insert — JSONB payload + stale PostgREST schema cache (PGRST204)."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

from app.db import insert_run_report


class _FakePGRST204(Exception):
    def __init__(self, column: str) -> None:
        self.code = "PGRST204"
        self.message = (
            f"Could not find the '{column}' column of 'run_reports' in the schema cache"
        )
        super().__init__(self.message)


def test_insert_run_report_retries_without_stale_schema_column():
    calls: list[dict[str, Any]] = []

    mock_client = MagicMock()
    mock_table = MagicMock()
    mock_client.table.return_value = mock_table
    mock_table.insert.return_value = mock_table

    def _execute() -> MagicMock:
        payload = dict(mock_table.insert.call_args[0][0])
        calls.append(payload)
        if "quarantine_manifest" in payload:
            raise _FakePGRST204("quarantine_manifest")
        return MagicMock(data=[{"run_id": payload["run_id"]}])

    mock_table.execute.side_effect = _execute

    with patch("app.db.get_supabase", return_value=mock_client):
        row = insert_run_report(
            {
                "run_id": "r1",
                "property_id": "ESMA.MALAG",
                "quarantine_manifest": [{"rule_id": "G1"}],
                "readiness_stats": {"total_rows": 1},
            }
        )

    assert len(calls) == 2
    assert "quarantine_manifest" in calls[0]
    assert isinstance(calls[0]["quarantine_manifest"], list)
    assert "quarantine_manifest" not in calls[1]
    assert calls[1]["readiness_stats"] == {"total_rows": 1}
    assert row["run_id"] == "r1"


def test_insert_run_report_coerces_json_string_manifest():
    captured: list[dict[str, Any]] = []

    mock_client = MagicMock()
    mock_table = MagicMock()
    mock_client.table.return_value = mock_table
    mock_table.insert.return_value = mock_table

    def _capture(row: dict[str, Any]) -> MagicMock:
        captured.append(row)
        return mock_table

    mock_table.insert.side_effect = _capture
    mock_table.execute.return_value = MagicMock(data=[{"run_id": "r2"}])

    with patch("app.db.get_supabase", return_value=mock_client):
        insert_run_report(
            {
                "run_id": "r2",
                "quarantine_manifest": "[]",
                "findings": "[]",
            }
        )

    assert captured[0]["quarantine_manifest"] == []
    assert captured[0]["findings"] == []
