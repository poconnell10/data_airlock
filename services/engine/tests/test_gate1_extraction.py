"""
Comprehensive Gate 1 Extraction Engine suite.

Covers multipart (POC test bench) and S3-key (production) inputs across
POS, PMS, Reservations, Data Lake, and Data Warehouse feed categories.
"""

from __future__ import annotations

import json

import pytest

from app.gates.gate1_extraction import evaluate_gate1, evaluate_gate1_from_yaml
from app.gates.gate_1_extraction import evaluate_gate_1
from app.models.gate1 import Gate1Outcome
from app.models.gate1_contract import (
    Gate1Contract,
    LineConservationConfig,
    ObjectLandingConfig,
    gate1_contract_from_yaml,
    to_python_named_groups,
)


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


ONESAIT_RX = (
    r"^(?P<report_type>[a-z_]+)_(?P<property>[A-Z]{4}\.[A-Z]{5})_"
    r"(?P<date>\d{4}-\d{2}-\d{2})__(?P<hash>[a-f0-9]+)\.csv$"
)
# JS-style (as stored by the Property Setup UI)
ONESAIT_RX_JS = (
    r"^(?<report_type>[a-z_]+)_(?<property>[A-Z]{4}\.[A-Z]{5})_"
    r"(?<date>\d{4}-\d{2}-\d{2})__(?<hash>[a-f0-9]+)\.csv$"
)


def _pos_contract(**overrides) -> Gate1Contract:
    base = Gate1Contract(
        property_code="ESMA.MALAG",
        feed_category="pos",
        preset_id="onesait",
        encoding="UTF-8",
        delimiter="|",
        line_ending="\r\n",
        filename_regex=ONESAIT_RX,
        path_agreement=False,
        atomic_set=["headers_data", "sales_data", "payments_data"],
        line_conservation=LineConservationConfig(
            header_patterns=[r"^check_id\|"],
            footer_patterns=[r"^EOF", r"^TRL\|COUNT\|"],
            declared_count_regex=r"^TRL\|COUNT\|(?P<declared_row_count>\d+)",
        ),
    )
    return base.model_copy(update=overrides)


def _batch_ok(report_type: str = "sales_data") -> list[str]:
    date = "2026-08-09"
    prop = "ESMA.MALAG"
    h = "a91f"
    return [
        f"headers_data_{prop}_{date}__{h}.csv",
        f"sales_data_{prop}_{date}__{h}.csv",
        f"payments_data_{prop}_{date}__{h}.csv",
    ]


def _pos_body(rows: int = 3) -> bytes:
    lines = ["check_id|amount|guest"]
    for i in range(rows):
        lines.append(f"CHK{i:03d}|10.00|Guest{i}")
    lines.append(f"TRL|COUNT|{rows}")
    lines.append("EOF")
    return ("\r\n".join(lines) + "\r\n").encode("utf-8")


# ---------------------------------------------------------------------------
# Model / adapter
# ---------------------------------------------------------------------------


def test_to_python_named_groups_converts_js_syntax():
    assert "(?P<report_type>" in to_python_named_groups(ONESAIT_RX_JS)
    # idempotent on already-Python patterns
    assert to_python_named_groups(ONESAIT_RX) == ONESAIT_RX


def test_yaml_adapter_file_and_object():
    file_doc = {
        "profile_id": "onesait",
        "feed_category": "pos",
        "property_code": "ESMA.MALAG",
        "filename": {"pattern": ONESAIT_RX_JS, "path_agree": False},
        "file_format": {"encoding": "utf-8", "delimiter": "|"},
        "atomic_set": {
            "is_multi_file": True,
            "required_endpoints": ["headers_data", "sales_data", "payments_data"],
        },
        "row_classification": {
            "header_patterns": [r"^check_id\|"],
            "footer_patterns": [r"^EOF"],
        },
    }
    c = gate1_contract_from_yaml(file_doc)
    assert c.feed_category == "pos"
    assert c.atomic_set == ["headers_data", "sales_data", "payments_data"]
    assert c.object_config is None

    lake_doc = {
        "feed_category": "lake",
        "profile_id": "s3parquet",
        "property_code": "ESMA.MALAG",
        "object_landing": {
            "format": "parquet",
            "partition_path": "raw/{property}/pos/dt={date}/",
            "require_commit_marker": True,
        },
    }
    o = gate1_contract_from_yaml(lake_doc)
    assert o.is_object_feed()
    assert o.object_config is not None
    assert o.object_config.format == "Parquet"


# ---------------------------------------------------------------------------
# POS (multipart POC)
# ---------------------------------------------------------------------------


def test_pos_multipart_pass():
    report = evaluate_gate1(
        _pos_contract(),
        filename="sales_data_ESMA.MALAG_2026-08-09__a91f.csv",
        path="",
        raw_bytes=_pos_body(),
        present_batch_filenames=_batch_ok(),
    )
    assert report.status == "PASS"
    assert report.captured_tokens["property"] == "ESMA.MALAG"
    assert report.captured_tokens["report_type"] == "sales_data"
    assert report.missing_atomic_members == []
    line = next(f for f in report.findings if f.check_name == "line_conservation")
    assert line.details["data_lines"] == 3
    assert line.details["declared_count"] == 3


def test_pos_js_named_groups_in_regex():
    report = evaluate_gate1(
        _pos_contract(filename_regex=ONESAIT_RX_JS),
        filename="sales_data_ESMA.MALAG_2026-08-09__a91f.csv",
        raw_bytes=_pos_body(),
        present_batch_filenames=_batch_ok(),
    )
    assert report.status == "PASS"


def test_pos_filename_mismatch_quarantines():
    report = evaluate_gate1(
        _pos_contract(),
        filename="broken.csv",
        raw_bytes=_pos_body(),
        present_batch_filenames=_batch_ok(),
    )
    assert report.status == "QUARANTINE"
    assert report.findings[0].check_name == "filename_regex"
    assert report.findings[0].passed is False


def test_pos_incomplete_atomic_set_holds():
    report = evaluate_gate1(
        _pos_contract(),
        filename="sales_data_ESMA.MALAG_2026-08-09__a91f.csv",
        raw_bytes=_pos_body(),
        present_batch_filenames=["sales_data_ESMA.MALAG_2026-08-09__a91f.csv"],
    )
    assert report.status == "HOLD"
    assert set(report.missing_atomic_members) == {"headers_data", "payments_data"}


def test_pos_encoding_reject_with_offending_byte():
    # latin-1 ü (0xFC) under strict utf-8
    body = "check_id|guest\r\n1|Jürgen\r\nEOF\r\n".encode("latin-1")
    report = evaluate_gate1(
        _pos_contract(
            line_conservation=LineConservationConfig(
                header_patterns=[r"^check_id\|"],
                footer_patterns=[r"^EOF"],
            ),
            atomic_set=[],
        ),
        filename="sales_data_ESMA.MALAG_2026-08-09__a91f.csv",
        raw_bytes=body,
    )
    assert report.status == "REJECT"
    phys = next(f for f in report.findings if f.check_name == "physical_integrity")
    assert phys.passed is False
    assert phys.details.get("offending_byte") == "fc"


def test_pos_noise_filter_drops_macos_sidecar():
    report = evaluate_gate1(
        _pos_contract(),
        filename="._sales_data_ESMA.MALAG_2026-08-09__a91f.csv",
        path="landing/__MACOSX/._sales_data_ESMA.MALAG_2026-08-09__a91f.csv",
        raw_bytes=_pos_body(),
        present_batch_filenames=_batch_ok(),
    )
    assert report.status == "QUARANTINE"
    assert report.findings[0].check_name == "noise_filter"


def test_pos_path_agreement_s3_key():
    contract = _pos_contract(
        path_agreement=True,
        path_regex=r"raw/(?P<property>[A-Z.]+)/pos/(?P<date>\d{4}-\d{2}-\d{2})/",
    )
    report = evaluate_gate1(
        contract,
        filename="sales_data_ESMA.MALAG_2026-08-09__a91f.csv",
        path="s3://ing-airlock/raw/ESMA.MALAG/pos/2026-08-09/sales_data_ESMA.MALAG_2026-08-09__a91f.csv",
        raw_bytes=_pos_body(),
        present_batch_filenames=_batch_ok(),
    )
    assert report.status == "PASS"
    path_f = next(f for f in report.findings if f.check_name == "path_agreement")
    assert path_f.passed is True


def test_pos_path_disagreement_quarantines():
    contract = _pos_contract(
        path_agreement=True,
        path_regex=r"raw/(?P<property>[A-Z.]+)/pos/(?P<date>\d{4}-\d{2}-\d{2})/",
    )
    report = evaluate_gate1(
        contract,
        filename="sales_data_ESMA.MALAG_2026-08-09__a91f.csv",
        path="s3://ing-airlock/raw/OTHER.PROP/pos/2026-08-09/sales_data_ESMA.MALAG_2026-08-09__a91f.csv",
        raw_bytes=_pos_body(),
        present_batch_filenames=_batch_ok(),
    )
    assert report.status == "QUARANTINE"
    assert any(f.check_name == "path_agreement" and not f.passed for f in report.findings)


# ---------------------------------------------------------------------------
# PMS
# ---------------------------------------------------------------------------


def test_pms_opera_style_pass():
    contract = Gate1Contract(
        property_code="ESMA.MALAG",
        feed_category="pms",
        preset_id="opera",
        encoding="ISO-8859-1",
        filename_regex=(
            r"^(?P<property>[A-Z]{4}\.[A-Z]{5})_(?P<report_type>[A-Z_]+)_"
            r"(?P<date>\d{8})\.txt$"
        ),
        path_agreement=False,
        line_conservation=LineConservationConfig(
            header_patterns=[r"^RESV_NAME_ID,"],
            footer_patterns=[r"^\*\*\* END OF REPORT \*\*\*", r"^TOTAL:"],
        ),
    )
    body = (
        "RESV_NAME_ID,GUEST,AMOUNT\n"
        "1,Ada,10.00\n"
        "2,Grace,20.00\n"
        "TOTAL: 30.00\n"
        "*** END OF REPORT ***\n"
    ).encode("latin-1")
    report = evaluate_gate1(
        contract,
        filename="ESMA.MALAG_STAT_DAILY_20260809.txt",
        path="s3://ing-airlock/raw/ESMA.MALAG/pms/ESMA.MALAG_STAT_DAILY_20260809.txt",
        raw_bytes=body,
    )
    assert report.status == "PASS"
    assert report.captured_tokens["report_type"] == "STAT_DAILY"
    line = next(f for f in report.findings if f.check_name == "line_conservation")
    assert line.details["data_lines"] == 2
    assert line.details["footer_lines"] >= 2


# ---------------------------------------------------------------------------
# Reservations
# ---------------------------------------------------------------------------


def test_reservations_feed_pass():
    contract = Gate1Contract(
        property_code="ESMA.MALAG",
        feed_category="res",
        preset_id="booking",
        filename_regex=(
            r"^(?P<report_type>[a-z]+)_(?P<property>[A-Z]{4}\.[A-Z]{5})_"
            r"(?P<date>\d{4}-\d{2}-\d{2})\.csv$"
        ),
        path_agreement=False,
        atomic_set=["bookings"],
        line_conservation=LineConservationConfig(
            header_patterns=[r"^booking_id,"],
        ),
    )
    body = b"booking_id,guest\nB1,Ada\nB2,Grace\n"
    report = evaluate_gate1(
        contract,
        filename="bookings_ESMA.MALAG_2026-08-09.csv",
        raw_bytes=body,
        present_batch_filenames=["bookings_ESMA.MALAG_2026-08-09.csv"],
    )
    assert report.status == "PASS"
    assert report.captured_tokens["report_type"] == "bookings"


# ---------------------------------------------------------------------------
# Data Lake
# ---------------------------------------------------------------------------


def test_lake_parquet_pass_with_success_marker():
    contract = Gate1Contract(
        property_code="ESMA.MALAG",
        feed_category="lake",
        preset_id="s3parquet",
        object_config=ObjectLandingConfig(
            format="Parquet",
            partition_path_template="raw/{property}/pos/dt={date}/",
            require_commit_marker=True,
            commit_marker="_SUCCESS",
        ),
    )
    keys = [
        "ing-airlock/raw/ESMA.MALAG/pos/dt=2026-08-09/part-000.parquet",
        "ing-airlock/raw/ESMA.MALAG/pos/dt=2026-08-09/_SUCCESS",
    ]
    report = evaluate_gate1(
        contract,
        filename="part-000.parquet",
        path="s3://ing-airlock/raw/ESMA.MALAG/pos/dt=2026-08-09/part-000.parquet",
        raw_bytes=b"PAR1",  # opaque; not decoded
        present_batch_keys=keys,
    )
    assert report.status == "PASS"
    assert report.captured_tokens["property"] == "ESMA.MALAG"
    assert report.captured_tokens["date"] == "2026-08-09"
    assert any(f.check_name == "commit_marker" and f.passed for f in report.findings)


def test_lake_missing_commit_marker_holds():
    contract = Gate1Contract(
        property_code="ESMA.MALAG",
        feed_category="lake",
        preset_id="s3parquet",
        object_config=ObjectLandingConfig(
            format="Parquet",
            partition_path_template="raw/{property}/pos/dt={date}/",
            require_commit_marker=True,
        ),
    )
    report = evaluate_gate1(
        contract,
        filename="part-000.parquet",
        path="s3://ing-airlock/raw/ESMA.MALAG/pos/dt=2026-08-09/part-000.parquet",
        raw_bytes=b"PAR1",
        present_batch_keys=[
            "ing-airlock/raw/ESMA.MALAG/pos/dt=2026-08-09/part-000.parquet",
        ],
    )
    assert report.status == "HOLD"
    marker = next(f for f in report.findings if f.check_name == "commit_marker")
    assert marker.passed is False
    assert marker.details.get("hold") is True


# ---------------------------------------------------------------------------
# Data Warehouse
# ---------------------------------------------------------------------------


def test_dwh_jsonl_watermark_pass():
    contract = Gate1Contract(
        property_code="ESMA.MALAG",
        feed_category="dwh",
        preset_id="snowflake_export",
        object_config=ObjectLandingConfig(
            format="JSONL",
            partition_path_template="raw/{property}/dwh/dt={date}/",
            watermark_column="_ingested_at",
            require_commit_marker=True,
        ),
    )
    payload = (
        json.dumps(
            {
                "booking_id": "B1",
                "_ingested_at": "2026-08-09T07:00:00Z",
            }
        )
        + "\n"
    ).encode("utf-8")
    keys = [
        "bucket/raw/ESMA.MALAG/dwh/dt=2026-08-09/export.jsonl",
        "bucket/raw/ESMA.MALAG/dwh/dt=2026-08-09/_SUCCESS",
    ]
    report = evaluate_gate1(
        contract,
        filename="export.jsonl",
        path="s3://bucket/raw/ESMA.MALAG/dwh/dt=2026-08-09/export.jsonl",
        raw_bytes=payload,
        present_batch_keys=keys,
    )
    assert report.status == "PASS"
    wm = next(f for f in report.findings if f.check_name == "watermark")
    assert wm.passed is True


def test_dwh_jsonl_missing_watermark_quarantines():
    contract = Gate1Contract(
        property_code="ESMA.MALAG",
        feed_category="dwh",
        preset_id="snowflake_export",
        object_config=ObjectLandingConfig(
            format="JSONL",
            partition_path_template="raw/{property}/dwh/dt={date}/",
            watermark_column="_ingested_at",
            require_commit_marker=False,
        ),
    )
    payload = (json.dumps({"booking_id": "B1"}) + "\n").encode("utf-8")
    report = evaluate_gate1(
        contract,
        filename="export.jsonl",
        path="s3://bucket/raw/ESMA.MALAG/dwh/dt=2026-08-09/export.jsonl",
        raw_bytes=payload,
    )
    assert report.status == "QUARANTINE"
    wm = next(f for f in report.findings if f.check_name == "watermark")
    assert wm.passed is False


def test_dwh_delta_accepts_delta_log_as_commit():
    contract = Gate1Contract(
        property_code="ESMA.MALAG",
        feed_category="dwh",
        preset_id="delta_lake",
        object_config=ObjectLandingConfig(
            format="Delta",
            partition_path_template="raw/{property}/dwh/dt={date}/",
            require_commit_marker=True,
            commit_marker="_SUCCESS",
        ),
    )
    keys = [
        "b/raw/ESMA.MALAG/dwh/dt=2026-08-09/part-000.snappy.parquet",
        "b/raw/ESMA.MALAG/dwh/dt=2026-08-09/_delta_log/00001.json",
    ]
    report = evaluate_gate1(
        contract,
        filename="part-000.snappy.parquet",
        path="s3://b/raw/ESMA.MALAG/dwh/dt=2026-08-09/part-000.snappy.parquet",
        raw_bytes=b"PAR1",
        present_batch_keys=keys,
    )
    assert report.status == "PASS"


# ---------------------------------------------------------------------------
# YAML entry + legacy facade
# ---------------------------------------------------------------------------


def test_evaluate_from_yaml_and_legacy_facade_align():
    doc = {
        "property_code": "ESMA.MALAG",
        "feed_category": "pos",
        "profile_id": "onesait",
        "filename": {"pattern": ONESAIT_RX},
        "file_format": {"encoding": "utf-8", "delimiter": "|"},
        "atomic_set": {
            "is_multi_file": True,
            "required_endpoints": ["headers_data", "sales_data", "payments_data"],
        },
        "row_classification": {
            "header_patterns": [r"^check_id\|"],
            "footer_patterns": [r"^EOF", r"^TRL\|COUNT\|"],
            "row_count_declaration": {
                "pattern": r"^TRL\|COUNT\|(?P<declared_row_count>\d+)"
            },
        },
    }
    typed = evaluate_gate1_from_yaml(
        doc,
        filename="sales_data_ESMA.MALAG_2026-08-09__a91f.csv",
        path="landing/sales_data_ESMA.MALAG_2026-08-09__a91f.csv",
        raw_bytes=_pos_body(),
        present_batch_filenames=_batch_ok(),
        property_code="ESMA.MALAG",
    )
    legacy = evaluate_gate_1(
        raw_bytes=_pos_body(),
        filename="sales_data_ESMA.MALAG_2026-08-09__a91f.csv",
        path="landing/sales_data_ESMA.MALAG_2026-08-09__a91f.csv",
        contract_yaml=doc,
        present_batch_filenames=_batch_ok(),
    )
    assert typed.status == "PASS"
    assert legacy.overall_outcome == Gate1Outcome.PASS
    assert legacy.filename_tokens.property == "ESMA.MALAG"
    assert legacy.filename_tokens.report_type == "sales_data"


@pytest.mark.parametrize(
    "category,preset",
    [
        ("pos", "onesait"),
        ("pms", "opera"),
        ("res", "booking"),
        ("lake", "s3parquet"),
        ("dwh", "snowflake_export"),
    ],
)
def test_all_feed_categories_constructible(category, preset):
    if category in {"lake", "dwh"}:
        c = Gate1Contract(
            property_code="ESMA.MALAG",
            feed_category=category,
            preset_id=preset,
            object_config=ObjectLandingConfig(),
        )
        assert c.is_object_feed()
    else:
        c = Gate1Contract(
            property_code="ESMA.MALAG",
            feed_category=category,
            preset_id=preset,
            filename_regex=ONESAIT_RX,
        )
        assert c.is_file_feed()


# ---------------------------------------------------------------------------
# Explicit non_empty_payload + endpoint_registered checks
# ---------------------------------------------------------------------------


def test_gate1_quarantines_zero_byte_file():
    report = evaluate_gate1(
        _pos_contract(),
        filename="sales_data_ESMA.MALAG_2026-08-11__a91f.csv",
        path="raw/ESMA.MALAG/pos/sales_data_ESMA.MALAG_2026-08-11__a91f.csv",
        raw_bytes=b"",
        present_batch_filenames=_batch_ok(),
    )
    assert report.status == "QUARANTINE"
    finding = next(f for f in report.findings if f.check_name == "non_empty_payload")
    assert finding.passed is False
    assert "PHYSICAL_INTEGRITY_FAIL" in finding.message


def test_gate1_quarantines_header_only_zero_data_rows():
    body = (
        "check_id|business_date|amount\r\n"
        "EOF|0\r\n"
    ).encode("utf-8")
    report = evaluate_gate1(
        _pos_contract(),
        filename="sales_data_ESMA.MALAG_2026-08-11__a91f.csv",
        path="raw/ESMA.MALAG/pos/sales_data_ESMA.MALAG_2026-08-11__a91f.csv",
        raw_bytes=body,
        present_batch_filenames=[
            "headers_data_ESMA.MALAG_2026-08-11__a91f.csv",
            "sales_data_ESMA.MALAG_2026-08-11__a91f.csv",
            "payments_data_ESMA.MALAG_2026-08-11__a91f.csv",
        ],
    )
    assert report.status == "QUARANTINE"
    finding = next(f for f in report.findings if f.check_name == "non_empty_payload")
    assert finding.passed is False
    assert "EMPTY_PAYLOAD" in finding.message


def test_gate1_quarantines_unregistered_endpoint():
    report = evaluate_gate1(
        _pos_contract(),
        filename="unknown_report_ESMA.MALAG_2026-08-11__a91f.csv",
        path="raw/ESMA.MALAG/pos/unknown_report_ESMA.MALAG_2026-08-11__a91f.csv",
        raw_bytes=_pos_body(),
        present_batch_filenames=[
            "unknown_report_ESMA.MALAG_2026-08-11__a91f.csv",
        ],
    )
    assert report.status == "QUARANTINE"
    finding = next(f for f in report.findings if f.check_name == "endpoint_registered")
    assert finding.passed is False
    assert "UNREGISTERED_ENDPOINT" in finding.message
    assert "unknown_report" in finding.message
    assert "ESMA.MALAG" in finding.message
