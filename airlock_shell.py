"""
Extraction Layer Airlock — vendor-agnostic, profile-driven shell engine.

Phase 1: pure stateless structural checks. No per-PMS code branches, no business
transformation, no type casting of UDF/payload values.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import date, datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Optional

import yaml
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError
from pydantic import BaseModel, Field, field_validator

# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class InvalidProfileConfigException(Exception):
    """Raised when a PMS structural profile fails fail-closed schema validation."""

    def __init__(self, message: str, *, schema_errors: Optional[list[str]] = None):
        super().__init__(message)
        self.schema_errors = schema_errors or []


# ---------------------------------------------------------------------------
# Report models
# ---------------------------------------------------------------------------


class OverallOutcome(str, Enum):
    PASS = "PASS"
    FLAG = "FLAG"
    QUARANTINE_FILE = "QUARANTINE_FILE"
    REJECT_FILE = "REJECT_FILE"
    HOLD_SET = "HOLD_SET"


class RuleStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    SKIPPED = "SKIPPED"
    HOLD = "HOLD"
    FLAG = "FLAG"


class FileIdentity(BaseModel):
    raw_filename: str
    property_id: Optional[str] = None
    pms_profile: Optional[str] = None
    report_type: Optional[str] = None
    business_date: Optional[str] = None
    checksum_sha256: Optional[str] = None


class RowAccounting(BaseModel):
    total_read_rows: int = 0
    header_footer_rows: int = 0
    accepted_rows: int = 0
    rejected_rows: int = 0
    quarantined_rows: int = 0
    ignored_rows: int = 0
    unaccounted_rows: int = 0
    conservation_asserted: bool = False
    declared_total: Optional[int] = None
    physical_line_segments: int = 0
    parse_skipped_segments: int = 0


class StructuralInventory(BaseModel):
    expected_sections_found: list[str] = Field(default_factory=list)
    missing_sections: list[str] = Field(default_factory=list)
    udf_slots_detected: int = 0
    unmapped_tokens: list[str] = Field(default_factory=list)


class RuleEvaluation(BaseModel):
    rule_id: str
    status: RuleStatus
    message: str


class ExtractionRunReport(BaseModel):
    run_id: str
    timestamp: str
    file_identity: FileIdentity
    overall_outcome: OverallOutcome
    outcome_reason: str = ""
    row_accounting: RowAccounting = Field(default_factory=RowAccounting)
    structural_inventory: StructuralInventory = Field(default_factory=StructuralInventory)
    rule_evaluations: list[RuleEvaluation] = Field(default_factory=list)

    @field_validator("run_id")
    @classmethod
    def _run_id_nonempty(cls, v: str) -> str:
        if not v:
            raise ValueError("run_id must be non-empty")
        return v


# ---------------------------------------------------------------------------
# Profile / registry loaders (fail-closed)
# ---------------------------------------------------------------------------

_SCHEMA_PATH = Path(__file__).resolve().parent / "pms_profile_schema.json"


def load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if not isinstance(data, dict):
        raise ValueError(f"Expected mapping in {path}")
    return data


def load_profile(
    profile_path: Path,
    *,
    schema_path: Optional[Path] = None,
) -> dict[str, Any]:
    """Load a PMS profile and validate it against the JSON Schema (fail-closed)."""
    data = load_yaml(profile_path)
    schema_file = schema_path or _SCHEMA_PATH
    try:
        schema = json.loads(schema_file.read_text(encoding="utf-8"))
    except OSError as exc:
        raise InvalidProfileConfigException(
            f"Unable to read profile schema at {schema_file}: {exc}"
        ) from exc

    validator = Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(data), key=lambda e: list(e.path))
    if errors:
        details = [
            f"{'/'.join(str(p) for p in err.path) or '<root>'}: {err.message}"
            for err in errors
        ]
        raise InvalidProfileConfigException(
            f"Profile '{profile_path}' failed schema validation (fail-closed): "
            + "; ".join(details),
            schema_errors=details,
        )
    return data


def load_registry(registry_path: Path) -> dict[str, Any]:
    return load_yaml(registry_path)


def reject_report_for_invalid_profile(
    *,
    raw_filename: str,
    profile_id: Optional[str],
    exc: InvalidProfileConfigException,
) -> ExtractionRunReport:
    """Emit a REJECT_FILE ExtractionRunReport when profile load is abortive."""
    return ExtractionRunReport(
        run_id=_new_run_id(),
        timestamp=_utc_now_iso(),
        file_identity=FileIdentity(
            raw_filename=raw_filename,
            pms_profile=profile_id,
        ),
        overall_outcome=OverallOutcome.REJECT_FILE,
        outcome_reason=f"INVALID_PROFILE_CONFIG: {exc}",
        rule_evaluations=[
            RuleEvaluation(
                rule_id="R00_PROFILE_SCHEMA",
                status=RuleStatus.FAIL,
                message=str(exc),
            )
        ],
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _new_run_id() -> str:
    return str(uuid.uuid4())


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _split_lines_with_accounting(
    text: str, line_ending: str
) -> tuple[list[str], int, int]:
    """
    Split decoded text into physical rows.

    Returns:
      lines: successfully extracted line records (terminator stripped)
      physical_segments: independent count of line segments observed at byte/scan level
      parse_skipped: segments/fragments skipped due to structural parse issues
                     (e.g. embedded NUL runs removed without producing a bucketable row)
    """
    parse_skipped = 0
    # Structural skip: embedded NULs are removed and counted as skipped fragments
    if "\x00" in text:
        nul_runs = re.findall(r"\x00+", text)
        parse_skipped += len(nul_runs)
        text = text.replace("\x00", "")

    if line_ending == "crlf":
        if "\r\n" in text:
            # Independent physical segment count from terminator occurrences
            physical_segments = text.count("\r\n")
            parts = text.split("\r\n")
            # A trailing non-empty fragment without terminator is an extra segment
            if parts and parts[-1] != "":
                physical_segments += 1
            elif parts and parts[-1] == "":
                parts = parts[:-1]
            # Orphan CR/LF not part of CRLF pairs → skipped structural noise
            stripped = text.replace("\r\n", "")
            if "\r" in stripped or "\n" in stripped:
                orphan_crs = stripped.count("\r")
                orphan_lfs = stripped.count("\n")
                parse_skipped += orphan_crs + orphan_lfs
                # Remove orphans from parts by re-splitting cleaned text only on CRLF
                cleaned = (
                    text.replace("\r\n", "\u0000")
                    .replace("\r", "")
                    .replace("\n", "")
                    .replace("\u0000", "\r\n")
                )
                parts = cleaned.split("\r\n")
                if parts and parts[-1] == "":
                    parts = parts[:-1]
                physical_segments = cleaned.count("\r\n") + (
                    1 if parts and not cleaned.endswith("\r\n") else 0
                )
        else:
            # Expected CRLF but absent — fall back; treat as parse degradation
            parts = text.splitlines()
            physical_segments = len(parts)
            if text and not text.endswith(("\n", "\r")):
                pass
            parse_skipped += 0
    elif line_ending == "lf":
        physical_segments = text.count("\n")
        parts = text.split("\n")
        if parts and parts[-1] == "":
            parts = parts[:-1]
        elif parts and parts[-1] != "":
            physical_segments += 1
        if "\r" in text:
            parse_skipped += text.count("\r")
            text_clean = text.replace("\r", "")
            physical_segments = text_clean.count("\n")
            parts = text_clean.split("\n")
            if parts and parts[-1] == "":
                parts = parts[:-1]
            elif parts and parts[-1] != "":
                physical_segments += 1
    elif line_ending == "cr":
        physical_segments = text.count("\r")
        parts = text.split("\r")
        if parts and parts[-1] == "":
            parts = parts[:-1]
        elif parts and parts[-1] != "":
            physical_segments += 1
    else:
        parts = text.splitlines()
        physical_segments = len(parts)

    return parts, physical_segments, parse_skipped


def _line_ending_ok(raw: bytes, expected: str) -> tuple[bool, str]:
    if expected == "any":
        return True, "Line ending policy is 'any'."
    has_crlf = b"\r\n" in raw
    stripped = raw.replace(b"\r\n", b"")
    has_lf = b"\n" in stripped
    has_cr = b"\r" in stripped
    if expected == "crlf":
        ok = has_crlf and not has_lf and not has_cr
        return ok, "CRLF required" if ok else "Expected CRLF; found mixed or non-CRLF endings."
    if expected == "lf":
        ok = has_lf and not has_crlf and not has_cr
        return ok, "LF required" if ok else "Expected LF; found CR or CRLF."
    if expected == "cr":
        ok = has_cr and not has_crlf and not has_lf
        return ok, "CR required" if ok else "Expected CR; found LF or CRLF."
    return False, f"Unknown line_ending expectation: {expected}"


def _field_count(line: str, delimiter: str) -> int:
    if line == "":
        return 0
    return len(line.split(delimiter))


def _matches_any(line: str, rules: list[dict[str, Any]]) -> bool:
    for rule in rules:
        if re.search(rule["pattern"], line):
            return True
    return False


def _shape_ok(line: str, delimiter: str, shape: Optional[dict[str, Any]]) -> bool:
    if not shape:
        return True
    n = _field_count(line, delimiter)
    if "exact_fields" in shape and shape["exact_fields"] is not None:
        return n == int(shape["exact_fields"])
    if "min_fields" in shape and n < int(shape["min_fields"]):
        return False
    if "max_fields" in shape and n > int(shape["max_fields"]):
        return False
    return True


def _severity_rank(outcome: OverallOutcome) -> int:
    order = {
        OverallOutcome.PASS: 0,
        OverallOutcome.FLAG: 1,
        OverallOutcome.HOLD_SET: 2,
        OverallOutcome.REJECT_FILE: 3,
        OverallOutcome.QUARANTINE_FILE: 4,
    }
    return order[outcome]


def _escalate(current: OverallOutcome, candidate: OverallOutcome) -> OverallOutcome:
    return candidate if _severity_rank(candidate) > _severity_rank(current) else current


def _extract_declared_row_count(lines: list[str], declaration: dict[str, Any]) -> Optional[int]:
    decl_re = re.compile(declaration["pattern"])
    for line in lines:
        m = decl_re.search(line)
        if not m:
            continue
        groups = m.groupdict()
        raw = groups.get("declared_row_count")
        if raw is None:
            raw = groups.get("declared_total")
        if raw is not None:
            return int(raw)
    return None


def save_run_report(report: ExtractionRunReport, output_dir: Path) -> Path:
    """Write the run report JSON alongside (or under) the configured output directory."""
    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / f"extraction_run_{report.run_id}.json"
    out_path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    return out_path


# ---------------------------------------------------------------------------
# Core engine
# ---------------------------------------------------------------------------


def process_file(
    file_path: Path,
    profile: dict[str, Any],
    registry: dict[str, Any],
    *,
    batch_files: Optional[list[Path]] = None,
    as_of_date: Optional[date] = None,
    output_dir: Optional[Path] = None,
    manifest_text: Optional[str] = None,
) -> ExtractionRunReport:
    """
    Execute Rules 1–6 against a landed file using a declarative PMS profile.

    Always returns an ExtractionRunReport, including early QUARANTINE_FILE /
    REJECT_FILE paths.
    """
    as_of = as_of_date or datetime.now(timezone.utc).date()
    report = ExtractionRunReport(
        run_id=_new_run_id(),
        timestamp=_utc_now_iso(),
        file_identity=FileIdentity(
            raw_filename=file_path.name,
            pms_profile=profile.get("profile_id"),
        ),
        overall_outcome=OverallOutcome.PASS,
        outcome_reason="",
    )

    # ---- Rule 1: Identity Contract (filename / uri_path / manifest) -------
    r1, tokens = _rule_identity_contract(
        file_path, profile, registry, report, manifest_text=manifest_text
    )
    report.rule_evaluations.append(r1)
    if r1.status == RuleStatus.FAIL:
        report.overall_outcome = OverallOutcome.QUARANTINE_FILE
        report.outcome_reason = r1.message
        _skip_remaining(report, start_from=2, include_identity_agreement=True)
        if output_dir is not None:
            save_run_report(report, output_dir)
        return report

    # ---- Rule 2: Physical Landing Integrity -------------------------------
    r2, raw, text = _rule_physical_integrity(file_path, profile, report)
    report.rule_evaluations.append(r2)
    if r2.status == RuleStatus.FAIL:
        min_bytes = int(profile.get("physical", {}).get("min_bytes", 1))
        if file_path.exists() and file_path.stat().st_size < min_bytes:
            report.overall_outcome = OverallOutcome.REJECT_FILE
        else:
            report.overall_outcome = OverallOutcome.QUARANTINE_FILE
        report.outcome_reason = r2.message
        _skip_remaining(report, start_from=3, include_identity_agreement=True)
        if output_dir is not None:
            save_run_report(report, output_dir)
        return report

    lines, physical_segments, parse_skipped = _split_lines_with_accounting(
        text, profile["physical"]["line_ending"]
    )

    # ---- Rule 1b: Filename vs Content Agreement ---------------------------
    r1b = _rule_identity_agreement(lines, profile, tokens, report)
    report.rule_evaluations.append(r1b)
    if r1b.status == RuleStatus.FAIL:
        report.overall_outcome = OverallOutcome.QUARANTINE_FILE
        report.outcome_reason = r1b.message
        _skip_remaining(report, start_from=3, include_identity_agreement=False)
        if output_dir is not None:
            save_run_report(report, output_dir)
        return report

    # ---- Rule 3: Row Conservation ----------------------------------------
    r3 = _rule_row_conservation(
        lines,
        profile,
        report,
        physical_segments=physical_segments,
        parse_skipped=parse_skipped,
    )
    report.rule_evaluations.append(r3)
    if r3.status == RuleStatus.FAIL:
        report.overall_outcome = _escalate(
            report.overall_outcome, OverallOutcome.QUARANTINE_FILE
        )
        report.outcome_reason = r3.message

    # ---- Rule 4: Static Date Bounds --------------------------------------
    r4 = _rule_date_bounds(lines, profile, report, as_of=as_of)
    report.rule_evaluations.append(r4)
    if r4.status == RuleStatus.FAIL:
        report.overall_outcome = _escalate(
            report.overall_outcome, OverallOutcome.QUARANTINE_FILE
        )
        if not report.outcome_reason:
            report.outcome_reason = r4.message

    # ---- Rule 5: Atomic Set Completeness ---------------------------------
    r5 = _rule_atomic_set(file_path, profile, tokens, batch_files=batch_files)
    report.rule_evaluations.append(r5)
    if r5.status == RuleStatus.HOLD:
        report.overall_outcome = _escalate(report.overall_outcome, OverallOutcome.HOLD_SET)
        if not report.outcome_reason:
            report.outcome_reason = r5.message
    elif r5.status == RuleStatus.FAIL:
        report.overall_outcome = _escalate(
            report.overall_outcome, OverallOutcome.QUARANTINE_FILE
        )
        if not report.outcome_reason:
            report.outcome_reason = r5.message

    # ---- Rule 6: Structural & UDF Inventory ------------------------------
    r6 = _rule_structure_udf(lines, profile, report)
    report.rule_evaluations.append(r6)
    if r6.status == RuleStatus.FAIL:
        report.overall_outcome = _escalate(
            report.overall_outcome, OverallOutcome.QUARANTINE_FILE
        )
        if not report.outcome_reason:
            report.outcome_reason = r6.message
    elif r6.status == RuleStatus.FLAG:
        report.overall_outcome = _escalate(report.overall_outcome, OverallOutcome.FLAG)
        if not report.outcome_reason:
            report.outcome_reason = r6.message

    if report.overall_outcome == OverallOutcome.PASS and not report.outcome_reason:
        report.outcome_reason = "All extraction airlock rules passed."

    if output_dir is not None:
        save_run_report(report, output_dir)
    return report


def _skip_remaining(
    report: ExtractionRunReport,
    start_from: int,
    *,
    include_identity_agreement: bool,
) -> None:
    labels = {
        2: "R02_PHYSICAL_INTEGRITY",
        3: "R03_ROW_CONSERVATION",
        4: "R04_STATIC_DATE_BOUNDS",
        5: "R05_ATOMIC_SET",
        6: "R06_STRUCTURAL_UDF",
    }
    if include_identity_agreement:
        report.rule_evaluations.append(
            RuleEvaluation(
                rule_id="R01B_IDENTITY_AGREEMENT",
                status=RuleStatus.SKIPPED,
                message="Skipped due to earlier hard failure.",
            )
        )
    for idx in range(start_from, 7):
        report.rule_evaluations.append(
            RuleEvaluation(
                rule_id=labels[idx],
                status=RuleStatus.SKIPPED,
                message="Skipped due to earlier hard failure.",
            )
        )


# ---------------------------------------------------------------------------
# Individual rules
# ---------------------------------------------------------------------------


def _rule_identity_contract(
    file_path: Path,
    profile: dict[str, Any],
    registry: dict[str, Any],
    report: ExtractionRunReport,
    *,
    manifest_text: Optional[str],
) -> tuple[RuleEvaluation, dict[str, str]]:
    rule_id = "R01_NAMING_CONTRACT"
    fn_cfg = profile["filename"]
    transport = fn_cfg.get("transport", "filename")
    required = list(fn_cfg.get("required_groups") or [])

    groups: dict[str, str] = {}
    if transport == "filename":
        pattern = fn_cfg.get("pattern")
        if not pattern:
            return (
                RuleEvaluation(
                    rule_id=rule_id,
                    status=RuleStatus.FAIL,
                    message="transport=filename requires filename.pattern.",
                ),
                {},
            )
        m = re.match(pattern, file_path.name)
        if not m:
            return (
                RuleEvaluation(
                    rule_id=rule_id,
                    status=RuleStatus.FAIL,
                    message=(
                        f"Filename '{file_path.name}' does not match profile "
                        f"'{profile.get('profile_id')}' naming regex."
                    ),
                ),
                {},
            )
        groups = {k: v for k, v in m.groupdict().items() if v is not None}
    elif transport == "uri_path":
        pattern = fn_cfg.get("uri_path_pattern")
        if not pattern:
            return (
                RuleEvaluation(
                    rule_id=rule_id,
                    status=RuleStatus.FAIL,
                    message="transport=uri_path requires filename.uri_path_pattern.",
                ),
                {},
            )
        path_text = file_path.as_posix()
        m = re.search(pattern, path_text)
        if not m:
            return (
                RuleEvaluation(
                    rule_id=rule_id,
                    status=RuleStatus.FAIL,
                    message=(
                        f"URI/path '{path_text}' does not match profile "
                        f"'{profile.get('profile_id')}' uri_path_pattern."
                    ),
                ),
                {},
            )
        groups = {k: v for k, v in m.groupdict().items() if v is not None}
    elif transport == "manifest":
        manifest_cfg = fn_cfg.get("manifest_identity") or {}
        pattern = manifest_cfg.get("pattern")
        source = manifest_text
        if source is None and file_path.is_file():
            # Fallback: treat payload body as the manifest identity source
            try:
                source = file_path.read_text(encoding=profile["physical"]["encoding"])
            except OSError:
                source = None
        if not pattern or source is None:
            return (
                RuleEvaluation(
                    rule_id=rule_id,
                    status=RuleStatus.FAIL,
                    message="transport=manifest requires manifest_identity.pattern and payload text.",
                ),
                {},
            )
        m = re.search(pattern, source)
        if not m:
            return (
                RuleEvaluation(
                    rule_id=rule_id,
                    status=RuleStatus.FAIL,
                    message="Manifest/payload identity pattern did not match.",
                ),
                {},
            )
        groups = {k: v for k, v in m.groupdict().items() if v is not None}
    else:
        return (
            RuleEvaluation(
                rule_id=rule_id,
                status=RuleStatus.FAIL,
                message=f"Unsupported identity transport '{transport}'.",
            ),
            {},
        )

    missing = [g for g in required if not groups.get(g)]
    if missing:
        return (
            RuleEvaluation(
                rule_id=rule_id,
                status=RuleStatus.FAIL,
                message=f"Identity match missing required named groups: {missing}.",
            ),
            {},
        )

    property_id = groups.get("property")
    report_type = groups.get("report_type")
    date_token = groups.get("date")
    business_date: Optional[str] = None
    if date_token:
        date_fmt = fn_cfg.get("date_format", "%Y%m%d")
        try:
            business_date = datetime.strptime(date_token, date_fmt).date().isoformat()
        except ValueError:
            return (
                RuleEvaluation(
                    rule_id=rule_id,
                    status=RuleStatus.FAIL,
                    message=f"Identity date token '{date_token}' failed format '{date_fmt}'.",
                ),
                {},
            )

    if property_id:
        props = registry.get("properties") or {}
        if property_id not in props:
            return (
                RuleEvaluation(
                    rule_id=rule_id,
                    status=RuleStatus.FAIL,
                    message=f"Property '{property_id}' is not registered.",
                ),
                {},
            )
        entry = props[property_id]
        if not entry.get("active", True):
            return (
                RuleEvaluation(
                    rule_id=rule_id,
                    status=RuleStatus.FAIL,
                    message=f"Property '{property_id}' is registered but inactive.",
                ),
                {},
            )
        expected_profile = entry.get("pms_profile")
        if expected_profile and expected_profile != profile.get("profile_id"):
            return (
                RuleEvaluation(
                    rule_id=rule_id,
                    status=RuleStatus.FAIL,
                    message=(
                        f"Property '{property_id}' bound to profile '{expected_profile}', "
                        f"not '{profile.get('profile_id')}'."
                    ),
                ),
                {},
            )

    report.file_identity.property_id = property_id
    report.file_identity.report_type = report_type
    report.file_identity.business_date = business_date
    tokens = dict(groups)
    if business_date:
        tokens["business_date"] = business_date

    return (
        RuleEvaluation(
            rule_id=rule_id,
            status=RuleStatus.PASS,
            message=(
                f"Identity transport '{transport}' matched profile "
                f"'{profile.get('profile_id')}' successfully."
            ),
        ),
        tokens,
    )


def _rule_identity_agreement(
    lines: list[str],
    profile: dict[str, Any],
    tokens: dict[str, str],
    report: ExtractionRunReport,
) -> RuleEvaluation:
    rule_id = "R01B_IDENTITY_AGREEMENT"
    cfg = profile.get("content_identity")
    if not cfg:
        return RuleEvaluation(
            rule_id=rule_id,
            status=RuleStatus.PASS,
            message="No content_identity configured; agreement check skipped.",
        )

    content: dict[str, str] = {}
    mapping = [
        ("property", cfg.get("property_pattern"), "property"),
        ("report_type", cfg.get("report_type_pattern"), "report_type"),
        ("business_date", cfg.get("business_date_pattern"), "business_date"),
    ]
    for key, pattern, group in mapping:
        if not pattern:
            continue
        cre = re.compile(pattern)
        for line in lines:
            m = cre.search(line)
            if m and m.groupdict().get(group):
                content[key] = m.group(group)
                break

    if "business_date" in content:
        bfmt = cfg.get("business_date_format", "%Y-%m-%d")
        try:
            content["business_date"] = (
                datetime.strptime(content["business_date"], bfmt).date().isoformat()
            )
        except ValueError:
            return RuleEvaluation(
                rule_id=rule_id,
                status=RuleStatus.FAIL,
                message=(
                    "MISFILED_OBJECT: Filename identity does not agree with content identity "
                    f"(unparseable content business_date)."
                ),
            )

    # Compare overlapping keys present on both sides
    filename_side = {
        "property": tokens.get("property") or report.file_identity.property_id,
        "report_type": tokens.get("report_type") or report.file_identity.report_type,
        "business_date": tokens.get("business_date") or report.file_identity.business_date,
    }
    disagreements: list[str] = []
    for key, cval in content.items():
        fval = filename_side.get(key)
        if fval is None:
            continue
        if str(fval) != str(cval):
            disagreements.append(f"{key}: filename={fval!r} content={cval!r}")

    if disagreements:
        return RuleEvaluation(
            rule_id=rule_id,
            status=RuleStatus.FAIL,
            message=(
                "MISFILED_OBJECT: Filename identity does not agree with content identity "
                f"({'; '.join(disagreements)})."
            ),
        )

    if not content:
        return RuleEvaluation(
            rule_id=rule_id,
            status=RuleStatus.FAIL,
            message=(
                "MISFILED_OBJECT: Filename identity does not agree with content identity "
                "(no content identity tokens found)."
            ),
        )

    return RuleEvaluation(
        rule_id=rule_id,
        status=RuleStatus.PASS,
        message="Filename/path identity agrees with content identity tokens.",
    )


def _rule_physical_integrity(
    file_path: Path,
    profile: dict[str, Any],
    report: ExtractionRunReport,
) -> tuple[RuleEvaluation, bytes, str]:
    rule_id = "R02_PHYSICAL_INTEGRITY"
    phys = profile["physical"]
    empty = b""
    if not file_path.is_file():
        return (
            RuleEvaluation(
                rule_id=rule_id,
                status=RuleStatus.FAIL,
                message=f"Path is not a file: {file_path}",
            ),
            empty,
            "",
        )

    compression = phys.get("compression", "none")
    if compression != "none":
        return (
            RuleEvaluation(
                rule_id=rule_id,
                status=RuleStatus.FAIL,
                message=(
                    f"Compression '{compression}' declared but Phase-1 shell "
                    "only accepts compression=none."
                ),
            ),
            empty,
            "",
        )

    raw = file_path.read_bytes()
    report.file_identity.checksum_sha256 = _sha256_bytes(raw)
    min_bytes = int(phys.get("min_bytes", 1))
    if len(raw) < min_bytes:
        return (
            RuleEvaluation(
                rule_id=rule_id,
                status=RuleStatus.FAIL,
                message=f"File size {len(raw)} below min_bytes={min_bytes}.",
            ),
            raw,
            "",
        )

    encoding = phys["encoding"]
    allow_bom = bool(phys.get("allow_bom", False))
    try:
        text = raw.decode(encoding)
    except UnicodeDecodeError as exc:
        return (
            RuleEvaluation(
                rule_id=rule_id,
                status=RuleStatus.FAIL,
                message=f"Decode failed for encoding '{encoding}': {exc}.",
            ),
            raw,
            "",
        )

    if text.startswith("\ufeff") and not allow_bom:
        return (
            RuleEvaluation(
                rule_id=rule_id,
                status=RuleStatus.FAIL,
                message="BOM present but allow_bom=false.",
            ),
            raw,
            text,
        )

    ok, msg = _line_ending_ok(raw, phys["line_ending"])
    if not ok:
        return (
            RuleEvaluation(rule_id=rule_id, status=RuleStatus.FAIL, message=msg),
            raw,
            text,
        )

    return (
        RuleEvaluation(
            rule_id=rule_id,
            status=RuleStatus.PASS,
            message=(
                f"Valid {encoding}, non-zero size ({len(raw)} bytes), "
                f"{phys['line_ending'].upper()} line endings."
            ),
        ),
        raw,
        text,
    )


def _rule_row_conservation(
    lines: list[str],
    profile: dict[str, Any],
    report: ExtractionRunReport,
    *,
    physical_segments: int,
    parse_skipped: int,
) -> RuleEvaluation:
    """
    Non-tautological Rule 3.

    - If declared_row_count is present: assert total_read_rows == declared_row_count.
    - Else: assert physical_line_segments == sum(bucketed_rows); parse skips that
      drop bytes/segments without bucketing yield unaccounted_rows > 0.
    """
    rule_id = "R03_ROW_CONSERVATION"
    rc = profile["row_classification"]
    delimiter = profile["physical"]["delimiter"]
    shape = rc.get("data_row_shape")

    header_footer = 0
    accepted = 0
    rejected = 0
    quarantined = 0
    ignored = 0

    for line in lines:
        if _matches_any(line, rc.get("header_rules") or []) or _matches_any(
            line, rc.get("footer_rules") or []
        ):
            header_footer += 1
            continue
        if _matches_any(line, rc.get("ignore_rules") or []):
            ignored += 1
            continue
        if _matches_any(line, rc.get("reject_rules") or []):
            rejected += 1
            continue
        if _shape_ok(line, delimiter, shape):
            accepted += 1
        else:
            quarantined += 1

    total_read_rows = len(lines)
    bucketed = accepted + rejected + quarantined + header_footer + ignored
    declaration = rc.get("row_count_declaration")
    declared_total = (
        _extract_declared_row_count(lines, declaration) if declaration else None
    )

    if declared_total is not None:
        # Independent assertion against vendor-declared count (not bucket arithmetic).
        compares_to = (declaration or {}).get("compares_to", "total_read_rows")
        observed = total_read_rows if compares_to == "total_read_rows" else accepted
        delta = abs(declared_total - observed)
        conservation_ok = declared_total == observed and parse_skipped == 0
        unaccounted = delta + parse_skipped
        report.row_accounting = RowAccounting(
            total_read_rows=total_read_rows,
            header_footer_rows=header_footer,
            accepted_rows=accepted,
            rejected_rows=rejected,
            quarantined_rows=quarantined,
            ignored_rows=ignored,
            unaccounted_rows=unaccounted,
            conservation_asserted=conservation_ok,
            declared_total=declared_total,
            physical_line_segments=physical_segments,
            parse_skipped_segments=parse_skipped,
        )
        if not conservation_ok:
            return RuleEvaluation(
                rule_id=rule_id,
                status=RuleStatus.FAIL,
                message=(
                    f"Row conservation invariant violated: declared_row_count={declared_total} "
                    f"vs {compares_to}={observed} "
                    f"(unaccounted_rows={unaccounted}, parse_skipped={parse_skipped})."
                ),
            )
        return RuleEvaluation(
            rule_id=rule_id,
            status=RuleStatus.PASS,
            message=(
                f"Declared row count matches {compares_to}={observed} "
                f"(declared_row_count={declared_total})."
            ),
        )

    # No declaration: independent physical segment count vs bucketed rows.
    # parse_skipped captures structural drops that never entered a bucket.
    unaccounted = abs(physical_segments - bucketed) + parse_skipped
    # Also flag if extracted lines diverge from physical segment scan
    if physical_segments != total_read_rows:
        unaccounted = abs(physical_segments - total_read_rows) + parse_skipped
    conservation_ok = unaccounted == 0

    report.row_accounting = RowAccounting(
        total_read_rows=total_read_rows,
        header_footer_rows=header_footer,
        accepted_rows=accepted,
        rejected_rows=rejected,
        quarantined_rows=quarantined,
        ignored_rows=ignored,
        unaccounted_rows=unaccounted,
        conservation_asserted=conservation_ok,
        declared_total=None,
        physical_line_segments=physical_segments,
        parse_skipped_segments=parse_skipped,
    )

    if not conservation_ok:
        return RuleEvaluation(
            rule_id=rule_id,
            status=RuleStatus.FAIL,
            message=(
                f"Row conservation invariant violated: physical_line_segments="
                f"{physical_segments} vs bucketed_rows={bucketed} "
                f"(parse_skipped={parse_skipped}, unaccounted_rows={unaccounted})."
            ),
        )

    return RuleEvaluation(
        rule_id=rule_id,
        status=RuleStatus.PASS,
        message=(
            f"Row conservation holds without declaration: physical_line_segments="
            f"{physical_segments} == bucketed_rows={bucketed}."
        ),
    )


def _rule_date_bounds(
    lines: list[str],
    profile: dict[str, Any],
    report: ExtractionRunReport,
    *,
    as_of: date,
) -> RuleEvaluation:
    rule_id = "R04_STATIC_DATE_BOUNDS"
    cfg = profile["date_bounds"]
    pat = re.compile(cfg["content_date_pattern"])
    fmt = cfg["date_format"]
    floor = date.fromisoformat(cfg["floor_date"])
    allow_future = bool(cfg.get("allow_future", False))

    observed: list[date] = []
    for line in lines:
        for m in pat.finditer(line):
            token = m.groupdict().get("biz_date")
            if not token:
                continue
            try:
                observed.append(datetime.strptime(token, fmt).date())
            except ValueError:
                return RuleEvaluation(
                    rule_id=rule_id,
                    status=RuleStatus.FAIL,
                    message=f"Unparseable content date token '{token}' for format '{fmt}'.",
                )

    if not observed:
        return RuleEvaluation(
            rule_id=rule_id,
            status=RuleStatus.FAIL,
            message="No content dates matched date_bounds.content_date_pattern.",
        )

    dmin, dmax = min(observed), max(observed)
    if dmin < floor:
        return RuleEvaluation(
            rule_id=rule_id,
            status=RuleStatus.FAIL,
            message=f"Observed min date {dmin.isoformat()} below floor {floor.isoformat()}.",
        )
    if not allow_future and dmax > as_of:
        return RuleEvaluation(
            rule_id=rule_id,
            status=RuleStatus.FAIL,
            message=(
                f"Observed max date {dmax.isoformat()} is in the future "
                f"relative to as_of {as_of.isoformat()}."
            ),
        )

    return RuleEvaluation(
        rule_id=rule_id,
        status=RuleStatus.PASS,
        message=(
            f"Observed dates ({dmin.isoformat()} .. {dmax.isoformat()}) within allowed bounds."
        ),
    )


def _rule_atomic_set(
    file_path: Path,
    profile: dict[str, Any],
    tokens: dict[str, str],
    *,
    batch_files: Optional[list[Path]],
) -> RuleEvaluation:
    rule_id = "R05_ATOMIC_SET"
    if not tokens:
        return RuleEvaluation(
            rule_id=rule_id,
            status=RuleStatus.FAIL,
            message="No identity tokens available for atomic set grouping.",
        )

    sets = profile.get("atomic_sets") or []
    if not sets:
        return RuleEvaluation(
            rule_id=rule_id,
            status=RuleStatus.PASS,
            message="No atomic sets defined for profile.",
        )

    siblings = batch_files
    if siblings is None:
        siblings = sorted(p for p in file_path.parent.iterdir() if p.is_file())

    fn_pattern = (profile.get("filename") or {}).get("pattern")
    parsed: list[dict[str, str]] = []
    if fn_pattern:
        fn_re = re.compile(fn_pattern)
        for sib in siblings:
            m = fn_re.match(sib.name)
            if m:
                parsed.append({k: v for k, v in m.groupdict().items() if v is not None})

    holds: list[str] = []
    for aset in sets:
        applies = aset.get("applies_to_report_types")
        if applies and tokens.get("report_type") not in applies:
            continue
        group_by = aset["group_by"]
        try:
            batch_key = tuple(tokens[g] for g in group_by)
        except KeyError as exc:
            return RuleEvaluation(
                rule_id=rule_id,
                status=RuleStatus.FAIL,
                message=f"Atomic set group_by token missing from identity: {exc}.",
            )
        present = {
            p.get("report_type")
            for p in parsed
            if tuple(p.get(g) for g in group_by) == batch_key
        }
        missing = [m for m in aset["members"] if m not in present]
        if missing:
            holds.append(
                f"set '{aset['set_id']}' missing members {missing} for batch key {batch_key}"
            )

    if holds:
        return RuleEvaluation(
            rule_id=rule_id,
            status=RuleStatus.HOLD,
            message="HOLD_SET: " + "; ".join(holds),
        )

    return RuleEvaluation(
        rule_id=rule_id,
        status=RuleStatus.PASS,
        message="All applicable atomic set members present in batch.",
    )


def _rule_structure_udf(
    lines: list[str],
    profile: dict[str, Any],
    report: ExtractionRunReport,
) -> RuleEvaluation:
    rule_id = "R06_STRUCTURAL_UDF"
    structure = profile["structure"]
    found: list[str] = []
    missing: list[str] = []

    for section in structure.get("expected_sections") or []:
        pat = re.compile(section["marker_pattern"])
        if any(pat.search(line) for line in lines):
            found.append(section["section_id"])
        elif section.get("required", True):
            missing.append(section["section_id"])

    udf_cfg = structure["udf"]
    slot_re = re.compile(udf_cfg["slot_pattern"])
    mode = udf_cfg.get("count_mode", "distinct_slots")
    expected = int(udf_cfg["expected_slot_count"])

    distinct: set[str] = set()
    total_matches = 0
    max_per_row = 0
    for line in lines:
        matches = list(slot_re.finditer(line))
        total_matches += len(matches)
        row_count = 0
        for m in matches:
            slot = m.groupdict().get("slot") or m.group(0)
            distinct.add(slot)
            row_count += 1
        max_per_row = max(max_per_row, row_count)

    if mode == "distinct_slots":
        detected = len(distinct)
    elif mode == "max_per_row":
        detected = max_per_row
    else:
        detected = total_matches

    unmapped: list[str] = []
    if mode == "distinct_slots" and detected > expected:
        unmapped = sorted(distinct)[expected:]

    report.structural_inventory = StructuralInventory(
        expected_sections_found=found,
        missing_sections=missing,
        udf_slots_detected=detected,
        unmapped_tokens=unmapped,
    )

    if missing:
        return RuleEvaluation(
            rule_id=rule_id,
            status=RuleStatus.FAIL,
            message=f"Required sections missing: {missing}.",
        )
    if detected < expected:
        return RuleEvaluation(
            rule_id=rule_id,
            status=RuleStatus.FLAG,
            message=(
                f"UDF slot inventory below expected: detected={detected}, expected={expected}."
            ),
        )
    if unmapped:
        return RuleEvaluation(
            rule_id=rule_id,
            status=RuleStatus.FLAG,
            message=f"Unmapped UDF tokens inventoried: {unmapped}.",
        )

    return RuleEvaluation(
        rule_id=rule_id,
        status=RuleStatus.PASS,
        message=(
            f"Sections {found} present; UDF slots detected={detected} "
            f"(expected={expected})."
        ),
    )


# ---------------------------------------------------------------------------
# CLI convenience
# ---------------------------------------------------------------------------


def main(argv: Optional[list[str]] = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="PMS Extraction Airlock Shell")
    parser.add_argument("file", type=Path, help="Landed file path")
    parser.add_argument("--profile", type=Path, required=True, help="PMS profile YAML")
    parser.add_argument(
        "--registry", type=Path, required=True, help="Property registry YAML"
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Directory for ExtractionRunReport JSON",
    )
    parser.add_argument(
        "--as-of",
        type=str,
        default=None,
        help="As-of date YYYY-MM-DD for future-date checks (default: UTC today)",
    )
    args = parser.parse_args(argv)

    try:
        profile = load_profile(args.profile)
    except InvalidProfileConfigException as exc:
        report = reject_report_for_invalid_profile(
            raw_filename=args.file.name,
            profile_id=None,
            exc=exc,
        )
        if args.output_dir is not None:
            save_run_report(report, args.output_dir)
        print(report.model_dump_json(indent=2))
        return 1

    registry = load_registry(args.registry)
    as_of = date.fromisoformat(args.as_of) if args.as_of else None
    report = process_file(
        args.file,
        profile,
        registry,
        as_of_date=as_of,
        output_dir=args.output_dir,
    )
    print(report.model_dump_json(indent=2))
    return 0 if report.overall_outcome == OverallOutcome.PASS else 1


if __name__ == "__main__":
    raise SystemExit(main())
