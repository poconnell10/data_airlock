"""
Polars-backed schema / format inference for sample landing files.
"""

from __future__ import annotations

import io
import re
from typing import Optional

import polars as pl
from pydantic import BaseModel, Field


class SchemaInferenceResult(BaseModel):
    detected_format: str  # 'delimited_text', 'json', 'xml'
    inferred_delimiter: Optional[str] = None
    inferred_encoding: str = "utf-8"
    total_sample_lines: int
    header_count: int
    sample_headers: list[str] = Field(default_factory=list)
    suggested_filename_pattern: str
    suggested_tokens: dict[str, str] = Field(default_factory=dict)
    # Optional diagnostics (backward-compatible extras for UI)
    byte_length: int = 0
    notes: list[str] = Field(default_factory=list)


_DELIMITER_CANDIDATES = [",", "\t", "|", ";"]

_ONESAIT_CSV_PATTERN = (
    r"^(?P<report_type>[a-z_]+)_(?P<property>[A-Z0-9\.]+)_"
    r"(?P<date>\d{4}-\d{2}-\d{2})__(?P<hash>[a-f0-9]+)\.csv$"
)

_JSON_PATTERN = (
    r"^(?P<report_type>[a-z_]+)_(?P<property>[A-Z0-9\.]+)_"
    r"(?P<date>\d{4}-\d{2}-\d{2})\.json$"
)

_XML_PATTERN = (
    r"^(?P<report_type>[a-z_]+)_(?P<property>[A-Z0-9\.]+)_"
    r"(?P<date>\d{4}-\d{2}-\d{2})\.xml$"
)


def _decode_bytes(raw_bytes: bytes) -> tuple[str, str, list[str]]:
    """UTF-8 first, then ISO-8859-1 / ASCII fallbacks."""
    notes: list[str] = []
    try:
        return raw_bytes.decode("utf-8"), "utf-8", notes
    except UnicodeDecodeError:
        notes.append("UTF-8 decode failed; falling back to iso-8859-1.")

    try:
        raw_bytes.decode("ascii")
        # Pure ASCII also decodes as latin-1; prefer labeling ascii when possible.
        return raw_bytes.decode("ascii"), "ascii", notes
    except UnicodeDecodeError:
        pass

    return raw_bytes.decode("iso-8859-1"), "iso-8859-1", notes


def _infer_delimiter(first_line: str) -> str:
    if not first_line:
        return ","
    best = max(_DELIMITER_CANDIDATES, key=lambda d: first_line.count(d))
    if first_line.count(best) == 0:
        return ","
    return best


def _clean_header(value: str) -> str:
    cleaned = value.strip()
    if len(cleaned) >= 2 and cleaned[0] == cleaned[-1] and cleaned[0] in {'"', "'"}:
        cleaned = cleaned[1:-1].strip()
    return cleaned.replace('""', '"')


def _parse_headers_polars(
    raw_bytes: bytes,
    text: str,
    delimiter: str,
    encoding: str,
) -> tuple[list[str], list[str]]:
    notes: list[str] = []
    first_line = next((ln for ln in text.splitlines() if ln.strip()), "")
    try:
        # Decode to text buffer — Polars encoding support for arbitrary codecs is limited.
        df = pl.read_csv(
            io.StringIO(text),
            separator=delimiter,
            n_rows=5,
            has_header=True,
            ignore_errors=True,
            truncate_ragged_lines=True,
            infer_schema_length=0,
        )
        headers = [_clean_header(str(c)) for c in df.columns]
        if headers:
            return headers, notes
    except Exception as exc:  # noqa: BLE001
        notes.append(f"Polars parse fallback: {exc}")

    headers = [_clean_header(h) for h in first_line.split(delimiter)] if first_line else []
    return headers, notes


def _infer_report_type(filename: str) -> str:
    lower = filename.lower()
    if "header" in lower:
        return "headers_data"
    if "payment" in lower:
        return "payments_data"
    if "sale" in lower:
        return "sales_data"
    # Try named groups from Onesait-style names
    m = re.match(
        r"^(?P<report_type>[a-z_]+)_(?P<property>[A-Z0-9\.]+)_(?P<date>\d{4}-\d{2}-\d{2})",
        filename.rsplit("/", 1)[-1],
        re.I,
    )
    if m and m.group("report_type"):
        return m.group("report_type").lower()
    return "sales_data"


def _tokens_from_filename(filename: str, report_type: str) -> dict[str, str]:
    base = filename.rsplit("/", 1)[-1]
    tokens: dict[str, str] = {
        "report_type": report_type,
        "date": "YYYY-MM-DD",
    }
    m = re.match(
        r"^(?P<report_type>[A-Za-z0-9_]+)_(?P<property>[A-Z0-9\.]+)_"
        r"(?P<date>\d{4}-\d{2}-\d{2})(?:__(?P<hash>[a-f0-9]+))?",
        base,
        re.I,
    )
    if m:
        tokens["report_type"] = m.group("report_type")
        tokens["property"] = m.group("property")
        tokens["date"] = m.group("date")
        if m.group("hash"):
            tokens["hash"] = m.group("hash")
    return tokens


def infer_schema_from_bytes(raw_bytes: bytes, filename: str) -> SchemaInferenceResult:
    """
    Infer file format, delimiter, encoding, sample headers, and filename token hints.
    """
    if raw_bytes is None:
        raw_bytes = b""

    basename = (filename or "sample.csv").rsplit("/", 1)[-1]
    byte_length = len(raw_bytes)

    if byte_length == 0:
        return SchemaInferenceResult(
            detected_format="delimited_text",
            inferred_delimiter=",",
            inferred_encoding="utf-8",
            total_sample_lines=0,
            header_count=0,
            sample_headers=[],
            suggested_filename_pattern=_ONESAIT_CSV_PATTERN,
            suggested_tokens={"report_type": "sales_data", "date": "YYYY-MM-DD"},
            byte_length=0,
            notes=["Empty payload; nothing to infer."],
        )

    text, encoding, notes = _decode_bytes(raw_bytes)
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    total_lines = len(lines)
    first_line = lines[0] if lines else ""

    # JSON
    if first_line.startswith("{") or first_line.startswith("["):
        report_type = _infer_report_type(basename) if basename else "api_payload"
        return SchemaInferenceResult(
            detected_format="json",
            inferred_delimiter=None,
            inferred_encoding=encoding,
            total_sample_lines=total_lines,
            header_count=0,
            sample_headers=[],
            suggested_filename_pattern=_JSON_PATTERN,
            suggested_tokens=_tokens_from_filename(basename, report_type or "api_payload"),
            byte_length=byte_length,
            notes=notes,
        )

    # XML
    if first_line.startswith("<") and not first_line.startswith("<?csv"):
        report_type = _infer_report_type(basename)
        return SchemaInferenceResult(
            detected_format="xml",
            inferred_delimiter=None,
            inferred_encoding=encoding,
            total_sample_lines=total_lines,
            header_count=0,
            sample_headers=[],
            suggested_filename_pattern=_XML_PATTERN,
            suggested_tokens=_tokens_from_filename(basename, report_type),
            byte_length=byte_length,
            notes=notes + ["XML detected; header extraction skipped."],
        )

    # Delimited text
    inferred_delimiter = _infer_delimiter(first_line)
    sample_headers, parse_notes = _parse_headers_polars(
        raw_bytes, text, inferred_delimiter, encoding
    )
    notes.extend(parse_notes)

    report_type = _infer_report_type(basename)
    suggested_tokens = _tokens_from_filename(basename, report_type)

    return SchemaInferenceResult(
        detected_format="delimited_text",
        inferred_delimiter=inferred_delimiter,
        inferred_encoding=encoding,
        total_sample_lines=total_lines,
        header_count=len(sample_headers),
        sample_headers=sample_headers,
        suggested_filename_pattern=_ONESAIT_CSV_PATTERN,
        suggested_tokens=suggested_tokens,
        byte_length=byte_length,
        notes=notes,
    )


# Backward-compatible alias used by older call sites
def infer_schema(
    raw: bytes,
    *,
    filename: Optional[str] = None,
    max_sample_bytes: int = 256_000,
) -> SchemaInferenceResult:
    sample = raw[:max_sample_bytes] if raw else b""
    return infer_schema_from_bytes(sample, filename or "sample.csv")
