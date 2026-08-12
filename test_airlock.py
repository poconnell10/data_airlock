"""Pytest suite for the Extraction Layer Airlock shell."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
import yaml

from airlock_shell import (
    ExtractionRunReport,
    FileIdentity,
    InvalidProfileConfigException,
    OverallOutcome,
    RuleStatus,
    _rule_date_bounds,
    load_profile,
    load_registry,
    process_file,
    save_run_report,
)

ROOT = Path(__file__).resolve().parent
PROFILE_PATH = ROOT / "pms_profiles" / "opera_v5.yaml"
REGISTRY_PATH = ROOT / "property_registry.yaml"

# Canonical fixture line count (including trailer)
VALID_TOTAL_ROWS = 11


@pytest.fixture(scope="module")
def profile() -> dict:
    return load_profile(PROFILE_PATH)


@pytest.fixture(scope="module")
def registry() -> dict:
    return load_registry(REGISTRY_PATH)


def _crlf(lines: list[str]) -> bytes:
    return ("\r\n".join(lines) + "\r\n").encode("utf-8")


def _build_valid_file_bytes(
    *,
    declare: int | None = VALID_TOTAL_ROWS,
    property_id: str = "PROP102",
    report_type: str = "TSA01",
    business_date: str = "2026-08-09",
) -> bytes:
    """Canonical valid TSA01 payload for opera_v5.

    Classification:
      headers/footers: 2 HDR + 1 TRL = 3
      ignored: 2 SEC + 1 comment = 3
      rejected: 1 ERR
      accepted: 3 DAT + 1 TAX = 4
      total physical rows: 11
    """
    lines = [
        f"HDR|FILE|opera_v5|{report_type}|{property_id}|{business_date}|",
        "HDR|COLUMNS|rec_type|biz_date|outlet|amount|udf|",
        "SEC|DAILY_SUMMARY|",
        f"DAT|{business_date}|REST|100.00|UDF01=a|UDF02=b|UDF03=c|UDF04=d|",
        f"DAT|{business_date}|BAR|40.00|UDF01=a|UDF02=b|UDF03=c|UDF04=d|",
        f"DAT|{business_date}|SPA|25.00|UDF01=a|UDF02=b|UDF03=c|UDF04=d|",
        "SEC|TAX_RECAP|",
        f"TAX|{business_date}|VAT|12.50|",
        "#|operator note ignored",
        "ERR|dropped vendor stub",
        f"TRL|COUNT|{declare}|",
    ]
    assert len(lines) == VALID_TOTAL_ROWS
    return _crlf(lines)


def _write(path: Path, payload: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return path


def _touch_set_members(landing: Path, property_id: str, yyyymmdd: str, seq: str) -> list[Path]:
    """Create sibling set members so Rule 5 can observe a complete batch."""
    paths: list[Path] = []
    for report_type in ("TSA01", "TSA02", "TSA03", "TSA04", "TSA05", "TSA06"):
        p = landing / f"{report_type}_{property_id}_{yyyymmdd}_{seq}.csv"
        p.parent.mkdir(parents=True, exist_ok=True)
        if not p.exists():
            p.write_bytes(_build_valid_file_bytes(property_id=property_id))
        paths.append(p)
    return paths


def test_valid_single_file_passes_all_checks(
    tmp_path: Path, profile: dict, registry: dict
) -> None:
    landing = tmp_path / "landing"
    batch = _touch_set_members(landing, "PROP102", "20260809", "01")
    target = landing / "TSA01_PROP102_20260809_01.csv"
    _write(target, _build_valid_file_bytes())

    report = process_file(
        target,
        profile,
        registry,
        batch_files=batch,
        as_of_date=date(2026, 8, 10),
        output_dir=tmp_path / "reports",
    )

    assert isinstance(report, ExtractionRunReport)
    assert report.overall_outcome == OverallOutcome.PASS
    assert report.file_identity.property_id == "PROP102"
    assert report.file_identity.report_type == "TSA01"
    assert report.file_identity.business_date == "2026-08-09"
    assert report.file_identity.checksum_sha256
    assert report.row_accounting.conservation_asserted is True
    assert report.row_accounting.total_read_rows == VALID_TOTAL_ROWS
    assert report.row_accounting.declared_total == VALID_TOTAL_ROWS
    assert report.row_accounting.accepted_rows == 4
    assert report.row_accounting.rejected_rows == 1
    assert report.row_accounting.ignored_rows == 3
    assert report.row_accounting.header_footer_rows == 3
    statuses = {r.rule_id: r.status for r in report.rule_evaluations}
    assert statuses["R01_NAMING_CONTRACT"] == RuleStatus.PASS
    assert statuses["R01B_IDENTITY_AGREEMENT"] == RuleStatus.PASS
    assert statuses["R02_PHYSICAL_INTEGRITY"] == RuleStatus.PASS
    assert statuses["R03_ROW_CONSERVATION"] == RuleStatus.PASS
    assert statuses["R04_STATIC_DATE_BOUNDS"] == RuleStatus.PASS
    assert statuses["R05_ATOMIC_SET"] == RuleStatus.PASS
    assert statuses["R06_STRUCTURAL_UDF"] == RuleStatus.PASS
    assert len(list((tmp_path / "reports").glob("extraction_run_*.json"))) == 1


def test_row_conservation_failure_quarantines(
    tmp_path: Path, profile: dict, registry: dict
) -> None:
    landing = tmp_path / "landing"
    batch = _touch_set_members(landing, "PROP102", "20260809", "01")
    target = landing / "TSA01_PROP102_20260809_01.csv"
    # Declare 14 total rows but file only yields 11 → conservation fail
    _write(target, _build_valid_file_bytes(declare=14))

    report = process_file(
        target,
        profile,
        registry,
        batch_files=batch,
        as_of_date=date(2026, 8, 10),
    )

    assert isinstance(report, ExtractionRunReport)
    assert report.overall_outcome == OverallOutcome.QUARANTINE_FILE
    assert report.row_accounting.conservation_asserted is False
    assert report.row_accounting.unaccounted_rows == 3
    r3 = next(r for r in report.rule_evaluations if r.rule_id == "R03_ROW_CONSERVATION")
    assert r3.status == RuleStatus.FAIL


def test_incomplete_atomic_set_hold(
    tmp_path: Path, profile: dict, registry: dict
) -> None:
    landing = tmp_path / "landing"
    target = landing / "TSA01_PROP102_20260809_01.csv"
    _write(target, _build_valid_file_bytes())

    report = process_file(
        target,
        profile,
        registry,
        batch_files=[target],
        as_of_date=date(2026, 8, 10),
    )

    assert isinstance(report, ExtractionRunReport)
    assert report.overall_outcome == OverallOutcome.HOLD_SET
    r5 = next(r for r in report.rule_evaluations if r.rule_id == "R05_ATOMIC_SET")
    assert r5.status == RuleStatus.HOLD
    assert "HOLD_SET" in r5.message
    assert "TSA02" in r5.message


def test_unexpected_filename_immediate_quarantine(
    tmp_path: Path, profile: dict, registry: dict
) -> None:
    landing = tmp_path / "landing"
    target = landing / "WEIRDFILE_NOT_OPERA.txt"
    _write(target, _build_valid_file_bytes())

    report = process_file(
        target,
        profile,
        registry,
        batch_files=[target],
        as_of_date=date(2026, 8, 10),
    )

    assert isinstance(report, ExtractionRunReport)
    assert report.overall_outcome == OverallOutcome.QUARANTINE_FILE
    assert report.file_identity.raw_filename == "WEIRDFILE_NOT_OPERA.txt"
    statuses = {r.rule_id: r.status for r in report.rule_evaluations}
    assert statuses["R01_NAMING_CONTRACT"] == RuleStatus.FAIL
    assert statuses["R01B_IDENTITY_AGREEMENT"] == RuleStatus.SKIPPED
    assert statuses["R02_PHYSICAL_INTEGRITY"] == RuleStatus.SKIPPED
    assert statuses["R03_ROW_CONSERVATION"] == RuleStatus.SKIPPED
    assert statuses["R06_STRUCTURAL_UDF"] == RuleStatus.SKIPPED


def test_misfiled_object_property_mismatch_quarantines(
    tmp_path: Path, profile: dict, registry: dict
) -> None:
    """Filename says PROP102 but content HDR carries PROP200 → MISFILED_OBJECT."""
    landing = tmp_path / "landing"
    batch = _touch_set_members(landing, "PROP102", "20260809", "01")
    target = landing / "TSA01_PROP102_20260809_01.csv"
    _write(
        target,
        _build_valid_file_bytes(property_id="PROP200"),
    )

    report = process_file(
        target,
        profile,
        registry,
        batch_files=batch,
        as_of_date=date(2026, 8, 10),
    )

    assert isinstance(report, ExtractionRunReport)
    assert report.overall_outcome == OverallOutcome.QUARANTINE_FILE
    assert "MISFILED_OBJECT" in report.outcome_reason
    assert "Filename identity does not agree with content identity" in report.outcome_reason
    r1b = next(r for r in report.rule_evaluations if r.rule_id == "R01B_IDENTITY_AGREEMENT")
    assert r1b.status == RuleStatus.FAIL
    assert "MISFILED_OBJECT" in r1b.message


def test_profile_schema_typo_fails_closed_at_load(tmp_path: Path) -> None:
    """A typo / schema-invalid opera profile must raise at load — not silently proceed."""
    bad = yaml.safe_load(PROFILE_PATH.read_text(encoding="utf-8"))
    # Typo: illegal profile_id (uppercase / hyphen) + remove required transport
    bad["profile_id"] = "Opera-V5-TYPO"
    bad["filename"].pop("transport", None)
    bad_path = tmp_path / "opera_v5_typo.yaml"
    bad_path.write_text(yaml.safe_dump(bad), encoding="utf-8")

    with pytest.raises(InvalidProfileConfigException) as excinfo:
        load_profile(bad_path)

    assert "fail-closed" in str(excinfo.value).lower() or "schema validation" in str(
        excinfo.value
    ).lower()


def test_adjacent_date_columns_both_scanned(profile: dict) -> None:
    """Date regex must not consume trailing delimiters (adjacent dates both match)."""
    line = "DAT|2026-08-09|2026-08-10|REST|1.00|"
    import re

    pat = re.compile(profile["date_bounds"]["content_date_pattern"])
    dates = [m.group("biz_date") for m in pat.finditer(line)]
    assert dates == ["2026-08-09", "2026-08-10"]

    # Also via Rule 4 helper on a minimal synthetic line set
    report = ExtractionRunReport(
        run_id="00000000-0000-0000-0000-000000000001",
        timestamp="2026-08-10T00:00:00Z",
        file_identity=FileIdentity(raw_filename="x.csv"),
        overall_outcome=OverallOutcome.PASS,
    )
    evaluation = _rule_date_bounds(
        [line, "HDR|FILE|opera_v5|TSA01|PROP102|2026-08-09|"],
        profile,
        report,
        as_of=date(2026, 8, 10),
    )
    assert evaluation.status == RuleStatus.PASS
    assert "2026-08-09" in evaluation.message
    assert "2026-08-10" in evaluation.message


def test_save_run_report_helper(
    tmp_path: Path, profile: dict, registry: dict
) -> None:
    landing = tmp_path / "landing"
    batch = _touch_set_members(landing, "PROP102", "20260809", "01")
    target = landing / "TSA01_PROP102_20260809_01.csv"
    _write(target, _build_valid_file_bytes())
    report = process_file(
        target,
        profile,
        registry,
        batch_files=batch,
        as_of_date=date(2026, 8, 10),
    )
    out = save_run_report(report, tmp_path / "audit")
    assert out.is_file()
    loaded = ExtractionRunReport.model_validate_json(out.read_text(encoding="utf-8"))
    assert loaded.run_id == report.run_id
    assert loaded.overall_outcome == report.overall_outcome


def test_opera_profile_has_required_schema_keys(profile: dict) -> None:
    required = {
        "profile_id",
        "profile_version",
        "filename",
        "physical",
        "row_classification",
        "date_bounds",
        "atomic_sets",
        "structure",
    }
    assert required.issubset(profile.keys())
    assert profile["profile_id"] == "opera_v5"
    assert profile["filename"]["transport"] == "filename"
    assert "content_identity" in profile
