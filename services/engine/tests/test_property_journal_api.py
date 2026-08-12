"""Property Journal API — audit note projection + journal CRUD."""

from __future__ import annotations

from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

PROPERTY_ID = "ESMA.MALAG"
RUN_ID = "7e3512df-aaaa-bbbb-cccc-ddddeeeeffff"


def test_audit_note_creates_property_journal_entry() -> None:
    """Post an audit note for a run; journal GET returns matching entry."""
    run_row = {
        "run_id": RUN_ID,
        "property_id": PROPERTY_ID,
        "report_type": "pos_check_detail",
        "overall_outcome": "FLAG",
    }
    note_row = {
        "note_id": "note-001",
        "run_id": RUN_ID,
        "operator_id": "op_402",
        "note_type": "DECISION_REASON",
        "content": "Approved $12.50 revenue variance — GM confirmed late posting.",
        "created_at": "2026-08-12T15:15:00+00:00",
    }
    journal_row = {
        "journal_id": "jnl-001",
        "property_id": PROPERTY_ID,
        "run_id": RUN_ID,
        "operator_id": "op_402",
        "note_type": "DECISION_REASON",
        "customer_impact": "LOW",
        "lifecycle_event": "NOTE_ADDED",
        "content": note_row["content"],
        "report_type": "pos_check_detail",
        "created_at": note_row["created_at"],
    }

    with (
        patch("app.routers.journal.is_supabase_configured", return_value=True),
        patch(
            "app.routers.journal.fetch_run_report_by_id",
            return_value=run_row,
        ),
        patch(
            "app.routers.journal.insert_run_audit_note",
            return_value=note_row,
        ) as insert_note,
        patch(
            "app.routers.journal.fetch_property_journal_entries",
            return_value=[journal_row],
        ),
    ):
        post = client.post(
            f"/api/v1/airlock/runs/{RUN_ID}/audit-notes",
            json={
                "operator_id": "op_402",
                "content": note_row["content"],
                "note_type": "DECISION_REASON",
            },
        )
        assert post.status_code == 200, post.text
        body = post.json()
        assert body["success"] is True
        assert body["note_id"] == "note-001"
        assert body["journal_projected"] is True
        insert_note.assert_called_once()

        get = client.get(f"/api/v1/properties/{PROPERTY_ID}/journal")
        assert get.status_code == 200, get.text
        entries = get.json()
        assert len(entries) == 1
        entry = entries[0]
        assert entry["content"] == note_row["content"]
        assert entry["operator_id"] == "op_402"
        assert entry["run_id"] == RUN_ID
        assert entry["note_type"] == "DECISION_REASON"


def test_create_manual_property_journal_entry() -> None:
    journal_row = {
        "journal_id": "jnl-manual",
        "property_id": PROPERTY_ID,
        "run_id": None,
        "operator_id": "op_108",
        "note_type": "NOTE_ADDED",
        "customer_impact": "NONE",
        "lifecycle_event": "NOTE_ADDED",
        "content": "Phone call with Hotel Controller regarding POS upgrade.",
        "report_type": None,
        "created_at": "2026-08-12T16:00:00+00:00",
    }
    with (
        patch("app.routers.journal.is_supabase_configured", return_value=True),
        patch(
            "app.routers.journal.insert_property_journal_entry",
            return_value=journal_row,
        ),
    ):
        res = client.post(
            f"/api/v1/properties/{PROPERTY_ID}/journal",
            json={
                "operator_id": "op_108",
                "content": journal_row["content"],
                "note_type": "NOTE_ADDED",
            },
        )
        assert res.status_code == 200, res.text
        data = res.json()
        assert data["journal_id"] == "jnl-manual"
        assert "POS upgrade" in data["content"]
        assert data["run_id"] is None
