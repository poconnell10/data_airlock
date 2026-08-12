"""
Airlock contract API — upsert + preset fallback.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

_FEED_ID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
_PROPERTY_ID = "ESMA.MALAG"

_VALID_PAYLOAD: dict[str, Any] = {
    "property_id": _PROPERTY_ID,
    "feed_id": _FEED_ID,
    "feed_category": "pos",
    "system_preset": "onesait",
    "file_format": "delimited_text",
    "contract_yaml": {
        "version": "2.0",
        "metadata": {
            "property_id": _PROPERTY_ID,
            "feed_category": "POS",
            "system_preset": "onesait",
            "updated_at": "2026-08-11T22:00:00Z",
        },
        "gates": {
            "gate1_extraction": {
                "filename_pattern": (
                    r"^(?P<report_type>[a-z_]+)_(?P<property>[A-Z]{4}\.[A-Z]{5})_"
                    r"(?P<date>\d{4}-\d{2}-\d{2})__(?P<hash>[a-f0-9]+)\.csv$"
                ),
                "delimiter": "|",
                "encoding": "utf-8",
                "atomic_set_members": [
                    "sales_data",
                    "headers_data",
                    "payments_data",
                ],
                "hold_set_enabled": True,
            },
            "gate2_anomaly": {
                "zscore_threshold": 2.5,
                "rolling_window_days": 30,
            },
            "gate3_quality": {
                "required_columns": [
                    "check_id",
                    "business_date",
                    "total_amount",
                ],
            },
            "gate4_revenue": {"tolerance_eur": 0.05},
        },
    },
    "engine_contract": {
        "profile_id": "onesait",
        "filename": {
            "pattern": (
                r"^(?P<report_type>[a-z_]+)_(?P<property>[A-Z]{4}\.[A-Z]{5})_"
                r"(?P<date>\d{4}-\d{2}-\d{2})__(?P<hash>[a-f0-9]+)\.csv$"
            )
        },
        "atomic_set": {
            "is_multi_file": True,
            "required_endpoints": [
                "sales_data",
                "headers_data",
                "payments_data",
            ],
        },
    },
    "timezone": "Europe/Madrid",
    "sla_cutoff_time": "07:00",
    "grace_period_minutes": 60,
}


def test_upsert_airlock_contract():
    stored: list[dict[str, Any]] = []
    updated_at = datetime.now(timezone.utc).isoformat()

    def _upsert_airlock(row: dict[str, Any]) -> dict[str, Any]:
        stored.append(row)
        return {
            "id": "11111111-2222-3333-4444-555555555555",
            **row,
            "updated_at": updated_at,
        }

    with patch(
        "app.routers.contracts.is_supabase_configured", return_value=True
    ), patch(
        "app.routers.contracts.fetch_property_feed",
        return_value={
            "id": _FEED_ID,
            "property_id": _PROPERTY_ID,
            "feed_category": "pos",
            "preset_id": "onesait",
            "active_contract_id": None,
        },
    ), patch(
        "app.routers.contracts.upsert_ingestion_contract",
        return_value={"id": "99999999-aaaa-bbbb-cccc-dddddddddddd"},
    ), patch(
        "app.routers.contracts.update_feed_preset",
        return_value={},
    ), patch(
        "app.routers.contracts.link_feed_active_contract",
        return_value={},
    ), patch(
        "app.routers.contracts.update_property_sla_fields",
        return_value=None,
    ), patch(
        "app.routers.contracts.upsert_airlock_contract",
        side_effect=_upsert_airlock,
    ):
        res = client.post("/api/v1/airlock/contracts", json=_VALID_PAYLOAD)

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["property_id"] == _PROPERTY_ID
    assert body["feed_id"] == _FEED_ID
    assert body["status"] == "published"
    assert body["updated_at"]
    assert len(stored) == 1
    gates = stored[0]["contract_yaml"]["gates"]["gate1_extraction"]
    assert "filename_pattern" in gates
    assert gates["atomic_set_members"] == [
        "sales_data",
        "headers_data",
        "payments_data",
    ]


def test_get_contract_falls_back_to_preset():
    with patch(
        "app.routers.contracts.is_supabase_configured", return_value=True
    ), patch(
        "app.routers.contracts.fetch_airlock_contract", return_value=None
    ), patch(
        "app.routers.contracts.fetch_property_feed",
        return_value={
            "id": _FEED_ID,
            "property_id": _PROPERTY_ID,
            "feed_category": "pos",
            "preset_id": "onesait",
            "active_contract_id": None,
        },
    ):
        res = client.get(
            f"/api/v1/airlock/contracts/{_PROPERTY_ID}/{_FEED_ID}"
        )

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["source"] == "preset_fallback"
    assert body["status"] == "draft"
    assert body["system_preset"] == "onesait"
    gates = body["contract_yaml"]["gates"]["gate1_extraction"]
    assert gates["delimiter"] == "|"
    assert "sales_data" in gates["atomic_set_members"]


def test_upsert_contract_with_epoch_ms_timestamp():
    """JS epoch-ms (1786501628757) must not 502 with Postgres 22003 / INT4 overflow."""
    epoch_ms = 1786501628757
    assert epoch_ms > 2_147_483_647  # would overflow INT4

    captured_versions: list[Any] = []
    updated_at = datetime.now(timezone.utc).isoformat()

    def _capture_ingestion(**kwargs: Any) -> dict[str, Any]:
        captured_versions.append(kwargs.get("version"))
        return {
            "id": "99999999-aaaa-bbbb-cccc-dddddddddddd",
            "version": kwargs.get("version"),
        }

    payload = {
        **_VALID_PAYLOAD,
        "version": epoch_ms,
        "updated_at_ms": epoch_ms,
        "contract_yaml": {
            **_VALID_PAYLOAD["contract_yaml"],
            "metadata": {
                **_VALID_PAYLOAD["contract_yaml"]["metadata"],
                "updated_at_ms": epoch_ms,
            },
        },
    }

    with patch(
        "app.routers.contracts.is_supabase_configured", return_value=True
    ), patch(
        "app.routers.contracts.fetch_property_feed",
        return_value={
            "id": _FEED_ID,
            "property_id": _PROPERTY_ID,
            "feed_category": "pos",
            "preset_id": "onesait",
            "active_contract_id": None,
        },
    ), patch(
        "app.routers.contracts.upsert_ingestion_contract",
        side_effect=_capture_ingestion,
    ), patch(
        "app.routers.contracts.update_feed_preset",
        return_value={},
    ), patch(
        "app.routers.contracts.link_feed_active_contract",
        return_value={},
    ), patch(
        "app.routers.contracts.update_property_sla_fields",
        return_value=None,
    ), patch(
        "app.routers.contracts.upsert_airlock_contract",
        return_value={
            "id": "11111111-2222-3333-4444-555555555555",
            "property_id": _PROPERTY_ID,
            "feed_id": _FEED_ID,
            "feed_category": "pos",
            "system_preset": "onesait",
            "status": "published",
            "version": "2.0",
            "updated_at": updated_at,
            "ingestion_contract_id": "99999999-aaaa-bbbb-cccc-dddddddddddd",
            "contract_yaml": payload["contract_yaml"],
            "engine_contract": payload["engine_contract"],
        },
    ):
        res = client.post("/api/v1/airlock/contracts", json=payload)

    assert res.status_code == 200, res.text
    assert "22003" not in res.text
    assert "out of range" not in res.text.lower()
    assert captured_versions == [epoch_ms]
    assert isinstance(captured_versions[0], int)


def test_switching_pos_preset_updates_existing_feed() -> None:
    """Simphony → One Sait must update preset in-place (no uq_property_feed)."""
    updated_at = datetime.now(timezone.utc).isoformat()
    preset_calls: list[dict[str, Any]] = []

    def _update_preset(**kwargs: Any) -> dict[str, Any]:
        preset_calls.append(kwargs)
        return {
            "id": _FEED_ID,
            "property_id": _PROPERTY_ID,
            "feed_category": "pos",
            "preset_id": kwargs["preset_id"],
        }

    payload = {
        **_VALID_PAYLOAD,
        "system_preset": "onesait",
        "contract_yaml": {
            **_VALID_PAYLOAD["contract_yaml"],
            "metadata": {
                **_VALID_PAYLOAD["contract_yaml"]["metadata"],
                "system_preset": "onesait",
            },
        },
    }

    with patch(
        "app.routers.contracts.is_supabase_configured", return_value=True
    ), patch(
        "app.routers.contracts.fetch_property_feed",
        return_value={
            "id": _FEED_ID,
            "property_id": _PROPERTY_ID,
            "feed_category": "pos",
            "preset_id": "simphony",
            "active_contract_id": None,
        },
    ), patch(
        "app.routers.contracts.upsert_ingestion_contract",
        return_value={"id": "99999999-aaaa-bbbb-cccc-dddddddddddd"},
    ), patch(
        "app.routers.contracts.update_feed_preset",
        side_effect=_update_preset,
    ), patch(
        "app.routers.contracts.link_feed_active_contract",
        return_value={
            "id": _FEED_ID,
            "preset_id": "onesait",
            "feed_category": "pos",
        },
    ) as link_feed, patch(
        "app.routers.contracts.update_property_sla_fields",
        return_value=None,
    ), patch(
        "app.routers.contracts.upsert_airlock_contract",
        return_value={
            "id": "11111111-2222-3333-4444-555555555555",
            "property_id": _PROPERTY_ID,
            "feed_id": _FEED_ID,
            "feed_category": "pos",
            "system_preset": "onesait",
            "status": "published",
            "version": "2.0",
            "updated_at": updated_at,
            "ingestion_contract_id": "99999999-aaaa-bbbb-cccc-dddddddddddd",
            "contract_yaml": payload["contract_yaml"],
            "engine_contract": payload["engine_contract"],
        },
    ):
        res = client.post("/api/v1/airlock/contracts", json=payload)

    assert res.status_code == 200, res.text
    assert "uq_property_feed" not in res.text
    body = res.json()
    assert body["system_preset"] == "onesait"
    assert len(preset_calls) == 1
    assert preset_calls[0]["feed_id"] == _FEED_ID
    assert preset_calls[0]["feed_category"] == "pos"
    assert preset_calls[0]["preset_id"] == "onesait"
    link_feed.assert_called_once()
    assert link_feed.call_args.kwargs["preset_id"] == "onesait"
