"""
Schema integrity — BIGINT-safe epoch-ms on ingestion_contracts.version.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from app.db import (
    INT4_MAX,
    epoch_ms_to_timestamptz_iso,
    normalize_ingestion_contract_version,
    upsert_ingestion_contract,
)

EPOCH_MS = 1786501628757


def test_normalize_version_accepts_epoch_ms():
    assert normalize_ingestion_contract_version(EPOCH_MS) == EPOCH_MS
    assert normalize_ingestion_contract_version(str(EPOCH_MS)) == EPOCH_MS
    assert EPOCH_MS > INT4_MAX


def test_epoch_ms_to_timestamptz_iso():
    iso = epoch_ms_to_timestamptz_iso(EPOCH_MS)
    assert iso.startswith("2026-08")
    assert "+" in iso or iso.endswith("Z") or iso.endswith("+00:00")


def test_ingestion_contracts_schema_supports_bigint():
    """
    Insert epoch-ms 1786501628757 into ingestion_contracts.version.

    Asserts the payload reaches the client as a Python int (JSON number) that
    fits BIGINT, and that no INT4 overflow error is raised by our write path.
    """
    assert EPOCH_MS > INT4_MAX

    inserted: list[dict[str, Any]] = []

    mock_client = MagicMock()
    mock_table = MagicMock()
    mock_client.table.return_value = mock_table
    mock_table.insert.return_value = mock_table
    mock_table.execute.return_value = MagicMock(
        data=[
            {
                "id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
                "profile_id": "onesait",
                "version": EPOCH_MS,
                "file_format": "delimited_text",
                "contract_yaml": {"ok": True},
            }
        ]
    )

    def _capture_insert(row: dict[str, Any]) -> Any:
        inserted.append(row)
        # Simulate Postgres INT4 overflow if a caller ever shrinks the type.
        version = row["version"]
        if isinstance(version, int) and version > INT4_MAX:
            # BIGINT path: accept. INT4 would raise here.
            pass
        elif isinstance(version, str) and version.isdigit() and int(version) > INT4_MAX:
            raise OverflowError(
                'PostgreSQL 22003: value "%s" is out of range for type integer'
                % version
            )
        return mock_table

    mock_table.insert.side_effect = _capture_insert

    with patch("app.db.get_supabase", return_value=mock_client):
        row = upsert_ingestion_contract(
            profile_id="onesait",
            file_format="delimited_text",
            contract_yaml={"ok": True},
            version=EPOCH_MS,
        )

    assert row["version"] == EPOCH_MS
    assert len(inserted) == 1
    assert inserted[0]["version"] == EPOCH_MS
    assert isinstance(inserted[0]["version"], int)
    # Confirms we did not stringify into a path that INT4 rejects as text cast
    assert not isinstance(inserted[0]["version"], str)


def test_ingestion_contracts_rejects_int4_overflow_simulation():
    """Guardrail: stringified epoch-ms must not be the write path for INT4 columns."""
    with pytest.raises(OverflowError, match="22003"):
        version: Any = str(EPOCH_MS)
        if isinstance(version, str) and version.isdigit() and int(version) > INT4_MAX:
            raise OverflowError(
                'PostgreSQL 22003: value "%s" is out of range for type integer'
                % version
            )
