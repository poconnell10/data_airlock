"""
Gate 1 — Extraction Engine (production).

Supports:
  • File feeds (POS / PMS / Reservations) — multipart uploads or S3 object keys
  • Object feeds (Data Lake / Data Warehouse) — partition paths, commit markers

Entry points:
  evaluate_gate1(contract, ...)           — typed Gate1Contract
  evaluate_gate1_from_yaml(yaml, ...)     — Supabase / UI JSONB adapter
"""

from __future__ import annotations

import fnmatch
import json
import re
from typing import Any, Optional
from urllib.parse import urlparse

from app.models.gate1_contract import (
    Gate1Contract,
    Gate1Finding,
    Gate1Report,
    Gate1Status,
    ObjectLandingConfig,
    gate1_contract_from_yaml,
    to_python_named_groups,
)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def evaluate_gate1(
    contract: Gate1Contract,
    *,
    filename: str,
    path: str = "",
    raw_bytes: Optional[bytes] = None,
    present_batch_filenames: Optional[list[str]] = None,
    present_batch_keys: Optional[list[str]] = None,
) -> Gate1Report:
    """
    Run Gate 1 fail-closed checks for file or object feeds.

    Status precedence: REJECT > QUARANTINE > HOLD > PASS
    """
    payload = raw_bytes if raw_bytes is not None else b""
    bytes_read = len(payload)
    batch_names = list(present_batch_filenames or [])
    batch_keys = list(present_batch_keys or present_batch_filenames or [])

    key_or_name = path or filename
    if _is_noise(key_or_name, contract.noise_filter) or _is_noise(
        filename, contract.noise_filter
    ):
        return _report(
            status="QUARANTINE",
            findings=[
                Gate1Finding(
                    check_name="noise_filter",
                    passed=False,
                    message="Object matches a noise filter pattern and will not be ingested.",
                    details={"filename": filename, "path": path},
                )
            ],
            bytes_read=bytes_read,
            reason="Noise filter matched.",
        )

    # Explicit physical integrity: refuse 0-byte landings before further parsing.
    if bytes_read == 0:
        msg = "PHYSICAL_INTEGRITY_FAIL: File is 0 bytes."
        return _report(
            status="QUARANTINE",
            findings=[
                Gate1Finding(
                    check_name="non_empty_payload",
                    passed=False,
                    message=msg,
                    details={"bytes_read": 0, "data_row_count": 0},
                )
            ],
            bytes_read=0,
            reason=msg,
        )

    if contract.is_object_feed() and contract.object_config is not None:
        return _evaluate_object_feed(
            contract,
            filename=filename,
            path=path,
            raw_bytes=payload,
            present_batch_keys=batch_keys,
        )

    return _evaluate_file_feed(
        contract,
        filename=filename,
        path=path,
        raw_bytes=payload,
        present_batch_filenames=batch_names,
    )


def evaluate_gate1_from_yaml(
    contract_yaml: dict[str, Any],
    *,
    filename: str,
    path: str = "",
    raw_bytes: Optional[bytes] = None,
    present_batch_filenames: Optional[list[str]] = None,
    present_batch_keys: Optional[list[str]] = None,
    property_code: str = "",
) -> Gate1Report:
    """Adapt a legacy / Supabase YAML document then evaluate."""
    contract = gate1_contract_from_yaml(
        contract_yaml,
        property_code=property_code,
    )
    return evaluate_gate1(
        contract,
        filename=filename,
        path=path,
        raw_bytes=raw_bytes,
        present_batch_filenames=present_batch_filenames,
        present_batch_keys=present_batch_keys,
    )


# ---------------------------------------------------------------------------
# File-feed pipeline (POS / PMS / Reservations)
# ---------------------------------------------------------------------------


def _evaluate_file_feed(
    contract: Gate1Contract,
    *,
    filename: str,
    path: str,
    raw_bytes: bytes,
    present_batch_filenames: list[str],
) -> Gate1Report:
    findings: list[Gate1Finding] = []
    bytes_read = len(raw_bytes)
    tokens: dict[str, Any] = {}

    # 1. Filename identity
    fn_finding, tokens = _check_filename(contract, filename)
    findings.append(fn_finding)
    if not fn_finding.passed:
        # Identity deviations are quarantined (not hard-rejected) by default.
        return _report(
            status="QUARANTINE",
            findings=findings
            + _skipped(
                [
                    "endpoint_registered",
                    "path_agreement",
                    "physical_integrity",
                    "non_empty_payload",
                    "line_conservation",
                    "atomic_set",
                ]
            ),
            tokens=tokens,
            bytes_read=bytes_read,
            reason=fn_finding.message,
        )

    # Property code agreement (when contract declares one)
    if contract.property_code and tokens.get("property"):
        if str(tokens["property"]) != str(contract.property_code):
            finding = Gate1Finding(
                check_name="property_code",
                passed=False,
                message=(
                    f"Property code mismatch: filename={tokens['property']!r} "
                    f"contract={contract.property_code!r}."
                ),
                details=dict(tokens),
            )
            findings.append(finding)
            return _report(
                status="QUARANTINE",
                findings=findings
                + _skipped(
                    [
                        "endpoint_registered",
                        "path_agreement",
                        "physical_integrity",
                        "non_empty_payload",
                        "line_conservation",
                        "atomic_set",
                    ]
                ),
                tokens=tokens,
                bytes_read=bytes_read,
                reason=finding.message,
            )

    # 1b. Endpoint registration (report_type ∈ contract atomic / registered set)
    endpoint_finding = _check_endpoint_registered(contract, tokens)
    findings.append(endpoint_finding)
    if not endpoint_finding.passed:
        return _report(
            status="QUARANTINE",
            findings=findings
            + _skipped(
                [
                    "path_agreement",
                    "physical_integrity",
                    "non_empty_payload",
                    "line_conservation",
                    "atomic_set",
                ]
            ),
            tokens=tokens,
            bytes_read=bytes_read,
            reason=endpoint_finding.message,
        )

    # 2. Path agreement
    path_finding = _check_path_agreement(contract, path, tokens)
    findings.append(path_finding)
    if not path_finding.passed:
        return _report(
            status="QUARANTINE",
            findings=findings
            + _skipped(
                [
                    "physical_integrity",
                    "non_empty_payload",
                    "line_conservation",
                    "atomic_set",
                ]
            ),
            tokens=tokens,
            bytes_read=bytes_read,
            reason=path_finding.message,
        )

    # 3. Physical / encoding
    phys_finding, text = _check_physical_integrity(contract, raw_bytes)
    findings.append(phys_finding)
    if not phys_finding.passed:
        return _report(
            status="REJECT",
            findings=findings
            + _skipped(["non_empty_payload", "line_conservation", "atomic_set"]),
            tokens=tokens,
            bytes_read=bytes_read,
            reason=phys_finding.message,
        )

    # 4. Line conservation
    line_finding, total_rows, data_lines = _check_line_conservation(contract, text)
    findings.append(line_finding)

    # 4b. Non-empty parsed payload (headers/trailers alone are not enough)
    empty_finding = _check_non_empty_data_rows(data_lines)
    findings.append(empty_finding)

    # 5. Atomic set
    atomic_finding, missing = _check_atomic_set(
        contract,
        tokens=tokens,
        filename=filename,
        present_batch_filenames=present_batch_filenames,
    )
    findings.append(atomic_finding)

    if not line_finding.passed:
        return _report(
            status="QUARANTINE",
            findings=findings,
            tokens=tokens,
            missing=missing,
            total_rows=total_rows,
            bytes_read=bytes_read,
            reason=line_finding.message,
        )

    if not empty_finding.passed:
        return _report(
            status="QUARANTINE",
            findings=findings,
            tokens=tokens,
            missing=missing,
            total_rows=total_rows,
            bytes_read=bytes_read,
            reason=empty_finding.message,
        )

    if not atomic_finding.passed:
        status: Gate1Status = "HOLD" if missing else "QUARANTINE"
        return _report(
            status=status,
            findings=findings,
            tokens=tokens,
            missing=missing,
            total_rows=total_rows,
            bytes_read=bytes_read,
            reason=atomic_finding.message,
        )

    return _report(
        status="PASS",
        findings=findings,
        tokens=tokens,
        missing=[],
        # Preserve prior telemetry: total_rows == physical line count
        total_rows=total_rows,
        bytes_read=bytes_read,
        reason="All Gate 1 extraction contract checks passed.",
    )


# ---------------------------------------------------------------------------
# Object-feed pipeline (Lake / DWH)
# ---------------------------------------------------------------------------


def _evaluate_object_feed(
    contract: Gate1Contract,
    *,
    filename: str,
    path: str,
    raw_bytes: bytes,
    present_batch_keys: list[str],
) -> Gate1Report:
    assert contract.object_config is not None
    cfg = contract.object_config
    findings: list[Gate1Finding] = []
    bytes_read = len(raw_bytes)
    key = _normalize_object_key(path or filename)

    # 1. Partition path / identity
    part_finding, tokens = _check_partition_path(contract, cfg, key)
    findings.append(part_finding)
    if not part_finding.passed:
        return _report(
            status=_failure_status(contract),
            findings=findings
            + _skipped(["commit_marker", "watermark", "object_payload"]),
            tokens=tokens,
            bytes_read=bytes_read,
            reason=part_finding.message,
        )

    if contract.property_code and tokens.get("property"):
        if str(tokens["property"]) != str(contract.property_code):
            finding = Gate1Finding(
                check_name="property_code",
                passed=False,
                message=(
                    f"Property code mismatch: path={tokens['property']!r} "
                    f"contract={contract.property_code!r}."
                ),
            )
            findings.append(finding)
            return _report(
                status=_failure_status(contract),
                findings=findings + _skipped(["commit_marker", "watermark", "object_payload"]),
                tokens=tokens,
                bytes_read=bytes_read,
                reason=finding.message,
            )

    # 2. Commit marker
    marker_finding = _check_commit_marker(cfg, key, present_batch_keys)
    findings.append(marker_finding)
    if not marker_finding.passed:
        # Incomplete partition → HOLD (writer still uploading)
        status: Gate1Status = (
            "HOLD" if marker_finding.details.get("hold") else _failure_status(contract)
        )
        return _report(
            status=status,
            findings=findings + _skipped(["watermark", "object_payload"]),
            tokens=tokens,
            bytes_read=bytes_read,
            reason=marker_finding.message,
        )

    # 3. Watermark / payload spot-check (JSONL only when bytes present)
    wm_finding = _check_watermark(cfg, raw_bytes)
    findings.append(wm_finding)
    if not wm_finding.passed:
        return _report(
            status="QUARANTINE",
            findings=findings + _skipped(["object_payload"]),
            tokens=tokens,
            bytes_read=bytes_read,
            reason=wm_finding.message,
        )

    # 4. Object payload presence (zero-byte data files fail; markers alone OK)
    payload_finding = _check_object_payload(cfg, filename, key, raw_bytes)
    findings.append(payload_finding)
    if not payload_finding.passed:
        return _report(
            status="REJECT",
            findings=findings,
            tokens=tokens,
            bytes_read=bytes_read,
            reason=payload_finding.message,
        )

    return _report(
        status="PASS",
        findings=findings,
        tokens=tokens,
        bytes_read=bytes_read,
        reason="Object landing contract checks passed.",
    )


# ---------------------------------------------------------------------------
# Checks — file
# ---------------------------------------------------------------------------


def _check_filename(
    contract: Gate1Contract, filename: str
) -> tuple[Gate1Finding, dict[str, Any]]:
    pattern = contract.filename_regex
    if not pattern:
        return (
            Gate1Finding(
                check_name="filename_regex",
                passed=False,
                message="Filename syntax deviation: contract missing filename_regex.",
            ),
            {},
        )

    py_pattern = to_python_named_groups(pattern)
    try:
        cre = re.compile(py_pattern)
    except re.error as exc:
        return (
            Gate1Finding(
                check_name="filename_regex",
                passed=False,
                message=f"Filename syntax deviation: invalid regex ({exc}).",
                details={"pattern": pattern},
            ),
            {},
        )

    basename = _basename(filename)
    match = cre.match(basename)
    if not match:
        return (
            Gate1Finding(
                check_name="filename_regex",
                passed=False,
                message="Filename syntax deviation",
                details={"filename": basename, "pattern": pattern},
            ),
            {},
        )

    groups = {k: v for k, v in match.groupdict().items() if v is not None}
    tokens = {
        "report_type": groups.get("report_type"),
        "property": groups.get("property") or groups.get("property_id"),
        "date": groups.get("date"),
        "hash": groups.get("hash")
        or groups.get("checksum")
        or groups.get("sha256")
        or groups.get("md5"),
    }
    tokens = {k: v for k, v in tokens.items() if v is not None}
    # Preserve any extra named groups
    for k, v in groups.items():
        tokens.setdefault(k, v)

    missing = []
    for g in contract.required_groups:
        if g == "property" and tokens.get("property"):
            continue
        if not groups.get(g) and not tokens.get(g):
            missing.append(g)
    if missing:
        return (
            Gate1Finding(
                check_name="filename_regex",
                passed=False,
                message=f"Filename syntax deviation: missing groups {missing}.",
                details={"tokens": tokens, "missing": missing},
            ),
            tokens,
        )

    return (
        Gate1Finding(
            check_name="filename_regex",
            passed=True,
            message="Filename matched identity regex; tokens extracted.",
            details={"tokens": tokens, "filename": basename},
        ),
        tokens,
    )


def _check_path_agreement(
    contract: Gate1Contract,
    path: str,
    tokens: dict[str, Any],
) -> Gate1Finding:
    if not contract.path_agreement:
        return Gate1Finding(
            check_name="path_agreement",
            passed=True,
            message="Path agreement disabled for this contract.",
            details={"skipped": True},
        )

    path_regex = contract.path_regex
    if not path_regex:
        return Gate1Finding(
            check_name="path_agreement",
            passed=True,
            message="No path regex configured; path agreement skipped.",
            details={"skipped": True},
        )

    key = _normalize_object_key(path)
    if not key:
        return Gate1Finding(
            check_name="path_agreement",
            passed=False,
            message="Path-to-filename agreement failed: empty path.",
            details={"path_regex": path_regex},
        )

    py_pattern = to_python_named_groups(path_regex)
    try:
        cre = re.compile(py_pattern)
    except re.error as exc:
        return Gate1Finding(
            check_name="path_agreement",
            passed=False,
            message=f"Path-to-filename agreement failed: invalid path regex ({exc}).",
            details={"path_regex": path_regex},
        )

    match = cre.search(key)
    if not match:
        return Gate1Finding(
            check_name="path_agreement",
            passed=False,
            message="Path-to-filename agreement failed: path does not match pattern.",
            details={"path": key, "path_regex": path_regex},
        )

    path_tokens = {k: v for k, v in match.groupdict().items() if v is not None}
    if "property_id" in path_tokens and "property" not in path_tokens:
        path_tokens["property"] = path_tokens["property_id"]

    disagreements: list[str] = []
    for name, path_val in path_tokens.items():
        if name in {"property", "property_id"}:
            file_val = tokens.get("property")
            compare_name = "property"
        elif name in tokens:
            file_val = tokens.get(name)
            compare_name = name
        else:
            continue
        if file_val is not None and str(file_val) != str(path_val):
            disagreements.append(
                f"{compare_name}: filename={file_val!r} path={path_val!r}"
            )

    if disagreements:
        return Gate1Finding(
            check_name="path_agreement",
            passed=False,
            message="Path-to-filename agreement failed: " + "; ".join(disagreements),
            details={
                "path": key,
                "path_tokens": path_tokens,
                "filename_tokens": tokens,
            },
        )

    return Gate1Finding(
        check_name="path_agreement",
        passed=True,
        message="Path tokens agree with filename tokens.",
        details={"path": key, "path_tokens": path_tokens},
    )


def _check_endpoint_registered(
    contract: Gate1Contract, tokens: dict[str, Any]
) -> Gate1Finding:
    """
    Ensure filename report_type is a registered airlock endpoint for the property.

    Registered endpoints are the contract atomic_set members (required report types).
    When no registry is configured, identity is limited to filename_regex capture.
    """
    report_type = tokens.get("report_type")
    property_code = tokens.get("property") or contract.property_code or ""
    registered = [str(ep) for ep in (contract.atomic_set or [])]

    if not report_type:
        msg = (
            "UNREGISTERED_ENDPOINT: Report type '' is not registered in "
            f"airlock contract for property '{property_code}'."
        )
        return Gate1Finding(
            check_name="endpoint_registered",
            passed=False,
            message=msg,
            details={
                "report_type": report_type,
                "property": property_code,
                "registered_endpoints": registered,
            },
        )

    if registered and str(report_type) not in registered:
        msg = (
            f"UNREGISTERED_ENDPOINT: Report type '{report_type}' is not registered "
            f"in airlock contract for property '{property_code}'."
        )
        return Gate1Finding(
            check_name="endpoint_registered",
            passed=False,
            message=msg,
            details={
                "report_type": report_type,
                "property": property_code,
                "registered_endpoints": registered,
            },
        )

    return Gate1Finding(
        check_name="endpoint_registered",
        passed=True,
        message=(
            f"Endpoint '{report_type}' is registered for property '{property_code}'."
            if registered
            else f"Endpoint '{report_type}' accepted (no atomic registry configured)."
        ),
        details={
            "report_type": report_type,
            "property": property_code,
            "registered_endpoints": registered,
        },
    )


def _check_non_empty_data_rows(data_row_count: int) -> Gate1Finding:
    """Quarantine files that parse but contain zero data rows."""
    if data_row_count == 0:
        msg = (
            "EMPTY_PAYLOAD: File contains headers/trailers but zero data rows."
        )
        return Gate1Finding(
            check_name="non_empty_payload",
            passed=False,
            message=msg,
            details={"data_row_count": 0},
        )
    return Gate1Finding(
        check_name="non_empty_payload",
        passed=True,
        message=f"Payload contains {data_row_count} data row(s).",
        details={"data_row_count": data_row_count},
    )


def _check_physical_integrity(
    contract: Gate1Contract, raw_bytes: bytes
) -> tuple[Gate1Finding, str]:
    payload = raw_bytes if raw_bytes is not None else b""
    # Zero-byte landings are handled earlier via non_empty_payload → QUARANTINE.
    if len(payload) == 0:
        return (
            Gate1Finding(
                check_name="physical_integrity",
                passed=False,
                message="PHYSICAL_INTEGRITY_FAIL: File is 0 bytes.",
                details={"bytes_read": 0},
            ),
            "",
        )

    encoding = str(contract.encoding or "utf-8").strip().lower()
    aliases = {
        "utf8": "utf-8",
        "utf-8-bom": "utf-8-sig",
        "utf-8-sig": "utf-8-sig",
        "ascii": "ascii",
        "us-ascii": "ascii",
        "latin-1": "latin-1",
        "iso-8859-1": "latin-1",
        "iso8859-1": "latin-1",
        "windows-1252": "cp1252",
        "cp1252": "cp1252",
    }
    encoding = aliases.get(encoding, encoding)

    candidates = [encoding]
    if contract.allow_encoding_fallback:
        if encoding == "utf-8":
            candidates.extend(["ascii", "latin-1"])
        elif encoding == "ascii":
            candidates.append("latin-1")

    last_error: Optional[str] = None
    last_details: dict[str, Any] = {
        "bytes_read": len(payload),
        "encoding": encoding,
        "requested_encoding": encoding,
    }
    for enc in candidates:
        try:
            text = payload.decode(enc)
            return (
                Gate1Finding(
                    check_name="physical_integrity",
                    passed=True,
                    message=f"Physical integrity OK ({enc}, {len(payload)} bytes).",
                    details={
                        "bytes_read": len(payload),
                        "encoding": enc,
                        "requested_encoding": encoding,
                    },
                ),
                text,
            )
        except UnicodeDecodeError as exc:
            last_error = str(exc)
            last_details = {
                "bytes_read": len(payload),
                "encoding": encoding,
                "requested_encoding": encoding,
                "failed_encoding": enc,
                "error_start": exc.start,
                "error_end": exc.end,
                "error_reason": exc.reason,
                "offending_byte": payload[exc.start : exc.start + 1].hex()
                if exc.start < len(payload)
                else None,
            }

    return (
        Gate1Finding(
            check_name="physical_integrity",
            passed=False,
            message=(
                "Physical integrity failed: decode error at byte "
                f"{last_details.get('error_start')} ({last_error})."
            ),
            details=last_details,
        ),
        "",
    )


def _check_line_conservation(
    contract: Gate1Contract, text: str
) -> tuple[Gate1Finding, int, int]:
    lines = _split_lines(text)
    total_lines = len(lines)
    cfg = contract.line_conservation

    header_patterns = cfg.all_header_patterns() if cfg else []
    footer_patterns = cfg.all_footer_patterns() if cfg else []
    ignore_patterns = list(cfg.ignore_patterns) if cfg else []
    declared_regex = cfg.declared_count_regex if cfg else None

    header_lines = footer_lines = ignore_lines = data_lines = 0

    if header_patterns or footer_patterns:
        for line in lines:
            if ignore_patterns and _matches_any(line, ignore_patterns):
                ignore_lines += 1
                continue
            if header_patterns and _matches_any(line, header_patterns):
                header_lines += 1
                continue
            if footer_patterns and _matches_any(line, footer_patterns):
                footer_lines += 1
                continue
            data_lines += 1
    else:
        started = False
        for line in lines:
            if ignore_patterns and _matches_any(line, ignore_patterns):
                ignore_lines += 1
                continue
            if not started:
                header_lines += 1
                started = True
            else:
                data_lines += 1

    bucketed = header_lines + data_lines + footer_lines + ignore_lines
    details: dict[str, Any] = {
        "total_lines": total_lines,
        "header_lines": header_lines,
        "data_lines": data_lines,
        "footer_lines": footer_lines,
        "ignore_lines": ignore_lines,
    }

    if total_lines != bucketed:
        return (
            Gate1Finding(
                check_name="line_conservation",
                passed=False,
                message=(
                    f"Line conservation failed: total_lines={total_lines} != "
                    f"header+data+footer+ignore={bucketed}."
                ),
                details=details,
            ),
            total_lines,
            data_lines,
        )

    declared_count: Optional[int] = None
    if declared_regex:
        py_pat = to_python_named_groups(str(declared_regex))
        try:
            cre = re.compile(py_pat)
        except re.error:
            cre = None
        if cre is not None:
            for line in lines:
                m = cre.search(line)
                if not m:
                    continue
                groups = m.groupdict()
                raw = (
                    groups.get("declared_row_count")
                    or groups.get("declared_count")
                    or groups.get("count")
                    or groups.get("rows")
                )
                if raw is None and m.lastindex:
                    raw = m.group(1)
                if raw is None:
                    continue
                try:
                    declared_count = int(raw)
                except ValueError:
                    continue
                break

    details["declared_count"] = declared_count
    if declared_count is not None and declared_count != data_lines:
        return (
            Gate1Finding(
                check_name="line_conservation",
                passed=False,
                message=(
                    f"Line conservation failed: data_lines={data_lines} != "
                    f"declared_count={declared_count}."
                ),
                details=details,
            ),
            total_lines,
            data_lines,
        )

    return (
        Gate1Finding(
            check_name="line_conservation",
            passed=True,
            message=(
                f"Line conservation OK: total={total_lines} "
                f"(header={header_lines}, data={data_lines}, footer={footer_lines})."
            ),
            details=details,
        ),
        total_lines,
        data_lines,
    )


def _check_atomic_set(
    contract: Gate1Contract,
    *,
    tokens: dict[str, Any],
    filename: str,
    present_batch_filenames: list[str],
) -> tuple[Gate1Finding, list[str]]:
    required = list(contract.atomic_set or [])
    if not required:
        return (
            Gate1Finding(
                check_name="atomic_set",
                passed=True,
                message="Atomic set not required for this contract.",
                details={"skipped": True},
            ),
            [],
        )

    pattern = contract.filename_regex
    batch = list(present_batch_filenames or [])
    current = _basename(filename)
    if current not in batch:
        batch.append(current)

    present_types: set[str] = set()
    if pattern:
        try:
            cre = re.compile(to_python_named_groups(pattern))
        except re.error:
            cre = None
        if cre is not None:
            for name in batch:
                m = cre.match(_basename(name))
                if not m:
                    continue
                g = m.groupdict()
                prop = g.get("property") or g.get("property_id")
                date = g.get("date")
                rtype = g.get("report_type")
                if not rtype:
                    continue
                if tokens.get("property") and prop and prop != tokens["property"]:
                    continue
                if tokens.get("date") and date and date != tokens["date"]:
                    continue
                present_types.add(rtype)
    else:
        for name in batch:
            present_types.add(_basename(name).split("_", 1)[0])

    if tokens.get("report_type"):
        present_types.add(str(tokens["report_type"]))

    missing = [ep for ep in required if ep not in present_types]
    details = {
        "required_endpoints": required,
        "present_endpoints": sorted(present_types),
        "missing_endpoints": missing,
        "batch_filenames": batch,
        "hold": bool(missing),
    }

    if tokens.get("report_type") and tokens["report_type"] not in required:
        return (
            Gate1Finding(
                check_name="atomic_set",
                passed=False,
                message=(
                    f"Atomic set failed: report_type '{tokens['report_type']}' "
                    "is not a required endpoint."
                ),
                details={**details, "hold": False},
            ),
            missing,
        )

    if missing:
        return (
            Gate1Finding(
                check_name="atomic_set",
                passed=False,
                message="HOLD_SET: atomic set incomplete; waiting for: "
                + ", ".join(missing),
                details=details,
            ),
            missing,
        )

    return (
        Gate1Finding(
            check_name="atomic_set",
            passed=True,
            message="All required atomic-set endpoints present in batch.",
            details=details,
        ),
        [],
    )


# ---------------------------------------------------------------------------
# Checks — object
# ---------------------------------------------------------------------------


def _template_to_regex(template: str) -> str:
    """Convert `{token}` path template to a Python named-group regex."""
    escaped = re.escape(template)
    return re.sub(
        r"\\\{([A-Za-z_][A-Za-z0-9_]*)\\\}",
        lambda m: rf"(?P<{m.group(1)}>[^/]+)",
        escaped,
    )


def _check_partition_path(
    contract: Gate1Contract,
    cfg: ObjectLandingConfig,
    key: str,
) -> tuple[Gate1Finding, dict[str, Any]]:
    if not key:
        return (
            Gate1Finding(
                check_name="partition_path",
                passed=False,
                message="Partition path check failed: empty object key.",
            ),
            {},
        )

    template = cfg.partition_path_template or ""
    # Allow optional object filename after the partition directory prefix.
    regex = _template_to_regex(template.rstrip("/")) + r"(?:/.*)?$"

    try:
        cre = re.compile(regex)
    except re.error as exc:
        return (
            Gate1Finding(
                check_name="partition_path",
                passed=False,
                message=f"Partition path check failed: invalid template ({exc}).",
                details={"template": template},
            ),
            {},
        )

    match = cre.search(key)
    if not match:
        # Soft fallback: search for dt= / property segment
        soft = {}
        m_dt = re.search(r"(?:dt|business_date)=([^/]+)", key)
        if m_dt:
            soft["date"] = m_dt.group(1)
        if contract.property_code and contract.property_code in key:
            soft["property"] = contract.property_code
        if soft.get("date") and soft.get("property"):
            return (
                Gate1Finding(
                    check_name="partition_path",
                    passed=True,
                    message="Partition tokens recovered via soft path parse.",
                    details={"path": key, "tokens": soft, "soft": True},
                ),
                soft,
            )
        return (
            Gate1Finding(
                check_name="partition_path",
                passed=False,
                message="Partition path does not match the configured template.",
                details={"path": key, "template": template},
            ),
            {},
        )

    tokens = {k: v for k, v in match.groupdict().items() if v is not None}
    if "feed" not in tokens:
        tokens["feed"] = contract.feed_category
    if "report_type" not in tokens:
        tokens["report_type"] = cfg.format.lower()
    return (
        Gate1Finding(
            check_name="partition_path",
            passed=True,
            message="Partition path matched; identity tokens extracted.",
            details={"path": key, "tokens": tokens},
        ),
        tokens,
    )


def _partition_prefix(key: str) -> str:
    """Directory containing the object (partition root)."""
    normalized = key.replace("\\", "/").rstrip("/")
    if "/" not in normalized:
        return ""
    return normalized.rsplit("/", 1)[0]


def _check_commit_marker(
    cfg: ObjectLandingConfig,
    key: str,
    present_batch_keys: list[str],
) -> Gate1Finding:
    if not cfg.require_commit_marker:
        return Gate1Finding(
            check_name="commit_marker",
            passed=True,
            message="Commit marker not required for this contract.",
            details={"skipped": True},
        )

    marker = cfg.commit_marker or "_SUCCESS"
    prefix = _partition_prefix(key)
    normalized_batch = [_normalize_object_key(k) for k in present_batch_keys]
    # Always consider the current key's partition
    candidates = set(normalized_batch)
    if key:
        candidates.add(_normalize_object_key(key))

    expected = f"{prefix}/{marker}" if prefix else marker
    # Delta tables may use _delta_log/ as commit signal when marker is _SUCCESS
    found = any(
        c.endswith("/" + marker) or c.endswith(marker) or c == expected
        for c in candidates
    )
    if not found and cfg.format == "Delta":
        found = any("/_delta_log" in c or c.rstrip("/").endswith("_delta_log") for c in candidates)

    if not found:
        return Gate1Finding(
            check_name="commit_marker",
            passed=False,
            message=f"HOLD: commit marker '{marker}' not present in partition.",
            details={
                "hold": True,
                "expected": expected,
                "partition_prefix": prefix,
                "batch_keys": sorted(candidates),
            },
        )

    return Gate1Finding(
        check_name="commit_marker",
        passed=True,
        message=f"Commit marker '{marker}' present for partition.",
        details={"expected": expected, "partition_prefix": prefix},
    )


def _check_watermark(cfg: ObjectLandingConfig, raw_bytes: bytes) -> Gate1Finding:
    if cfg.format != "JSONL":
        return Gate1Finding(
            check_name="watermark",
            passed=True,
            message=f"Watermark column '{cfg.watermark_column}' deferred for {cfg.format} "
            "(validated at read time).",
            details={"deferred": True, "column": cfg.watermark_column},
        )

    if not raw_bytes:
        return Gate1Finding(
            check_name="watermark",
            passed=True,
            message="No JSONL payload provided; watermark check skipped.",
            details={"skipped": True},
        )

    column = cfg.watermark_column
    try:
        text = raw_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        return Gate1Finding(
            check_name="watermark",
            passed=False,
            message=f"JSONL watermark check failed: decode error ({exc}).",
        )

    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            return Gate1Finding(
                check_name="watermark",
                passed=False,
                message="JSONL watermark check failed: invalid JSON line.",
            )
        if not isinstance(obj, dict):
            return Gate1Finding(
                check_name="watermark",
                passed=False,
                message="JSONL watermark check failed: row is not an object.",
            )
        if column not in obj:
            return Gate1Finding(
                check_name="watermark",
                passed=False,
                message=f"JSONL watermark column '{column}' missing from row.",
                details={"columns": sorted(obj.keys())},
            )
        return Gate1Finding(
            check_name="watermark",
            passed=True,
            message=f"Watermark column '{column}' present.",
            details={"column": column, "sample": obj.get(column)},
        )

    return Gate1Finding(
        check_name="watermark",
        passed=False,
        message="JSONL watermark check failed: empty payload.",
    )


def _check_object_payload(
    cfg: ObjectLandingConfig,
    filename: str,
    key: str,
    raw_bytes: bytes,
) -> Gate1Finding:
    base = _basename(filename or key)
    if base in {cfg.commit_marker, "_SUCCESS", "_DONE"} or base.startswith("_"):
        return Gate1Finding(
            check_name="object_payload",
            passed=True,
            message="Control/marker object — payload check skipped.",
            details={"skipped": True, "filename": base},
        )

    # For binary lake formats, empty local bytes are OK when evaluating key-only
    # (production fetch may stream later). Reject only when explicitly empty
    # *and* format is JSONL (text must be present for dry-run).
    if cfg.format == "JSONL" and len(raw_bytes) == 0:
        return Gate1Finding(
            check_name="object_payload",
            passed=False,
            message="Object payload failed: zero-byte JSONL data file.",
            details={"bytes_read": 0, "format": cfg.format},
        )

    return Gate1Finding(
        check_name="object_payload",
        passed=True,
        message=f"Object payload accepted ({cfg.format}, {len(raw_bytes)} bytes).",
        details={"bytes_read": len(raw_bytes), "format": cfg.format},
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _failure_status(contract: Gate1Contract) -> Gate1Status:
    return "REJECT" if contract.failure_route == "REJECT_FILE" else "QUARANTINE"


def _report(
    *,
    status: Gate1Status,
    findings: list[Gate1Finding],
    tokens: Optional[dict[str, Any]] = None,
    missing: Optional[list[str]] = None,
    total_rows: int = 0,
    bytes_read: int = 0,
    reason: str = "",
) -> Gate1Report:
    return Gate1Report(
        status=status,
        findings=findings,
        captured_tokens=dict(tokens or {}),
        missing_atomic_members=list(missing or []),
        total_rows=total_rows,
        bytes_read=bytes_read,
        outcome_reason=reason,
    )


def _skipped(names: list[str]) -> list[Gate1Finding]:
    return [
        Gate1Finding(
            check_name=name,
            passed=True,
            message="Skipped after prior failure.",
            details={"skipped": True},
        )
        for name in names
    ]


def _basename(filename: str) -> str:
    return filename.replace("\\", "/").rsplit("/", 1)[-1]


def _normalize_object_key(path: str) -> str:
    text = (path or "").strip()
    if not text:
        return ""
    if "://" in text:
        parsed = urlparse(text)
        if parsed.scheme == "s3":
            bucket = parsed.netloc
            key = parsed.path.lstrip("/")
            return f"{bucket}/{key}" if bucket else key
        return parsed.path.lstrip("/")
    return text.lstrip("/")


def _is_noise(name: str, patterns: list[str]) -> bool:
    if not name or not patterns:
        return False
    text = name.replace("\\", "/")
    base = _basename(text)
    for pat in patterns:
        if not pat:
            continue
        # Support both glob and substring directory markers
        if pat.endswith("/") and pat in text:
            return True
        if fnmatch.fnmatch(base, pat) or fnmatch.fnmatch(text, pat):
            return True
    return False


def _matches_any(line: str, patterns: list[str]) -> bool:
    for pat in patterns:
        try:
            if re.search(pat, line):
                return True
        except re.error:
            continue
    return False


def _split_lines(text: str) -> list[str]:
    if not text:
        return []
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    if normalized.endswith("\n"):
        return normalized[:-1].split("\n")
    return normalized.split("\n")
