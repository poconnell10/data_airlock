"""Pydantic v2 Gate 1 contract models — file feeds and object/warehouse feeds."""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator


FeedCategory = Literal["pos", "pms", "res", "lake", "dwh"]
ObjectFormat = Literal["Parquet", "Delta", "Avro", "JSONL"]
FailureRoute = Literal["REJECT_FILE", "QUARANTINE_FILE"]
Gate1Status = Literal["PASS", "REJECT", "QUARANTINE", "HOLD"]


class LineConservationConfig(BaseModel):
    header_pattern: Optional[str] = None
    footer_pattern: Optional[str] = None
    declared_count_regex: Optional[str] = None
    # Multi-pattern lists (YAML / UI may supply these)
    header_patterns: list[str] = Field(default_factory=list)
    footer_patterns: list[str] = Field(default_factory=list)
    ignore_patterns: list[str] = Field(default_factory=list)

    def all_header_patterns(self) -> list[str]:
        out = list(self.header_patterns)
        if self.header_pattern:
            out.append(self.header_pattern)
        return out

    def all_footer_patterns(self) -> list[str]:
        out = list(self.footer_patterns)
        if self.footer_pattern:
            out.append(self.footer_pattern)
        return out


class ObjectLandingConfig(BaseModel):
    format: ObjectFormat = "Parquet"
    partition_key: str = "business_date"
    watermark_column: str = "_ingested_at"
    partition_path_template: str = "raw/{property}/{feed}/dt={date}/"
    require_commit_marker: bool = True
    commit_marker: str = "_SUCCESS"

    @field_validator("format", mode="before")
    @classmethod
    def _normalize_format(cls, value: Any) -> str:
        if value is None:
            return "Parquet"
        text = str(value).strip()
        aliases = {
            "parquet": "Parquet",
            "delta": "Delta",
            "avro": "Avro",
            "jsonl": "JSONL",
            "json": "JSONL",
            "ndjson": "JSONL",
        }
        return aliases.get(text.lower(), text if text in {"Parquet", "Delta", "Avro", "JSONL"} else "Parquet")


class Gate1Contract(BaseModel):
    property_code: str
    feed_category: FeedCategory
    preset_id: str

    # File-based contract properties
    encoding: str = "UTF-8"
    delimiter: str = ","
    line_ending: str = "\n"
    filename_regex: Optional[str] = None
    sample_filename: Optional[str] = None
    path_agreement: bool = True
    path_regex: Optional[str] = None
    atomic_set: list[str] = Field(default_factory=list)
    line_conservation: Optional[LineConservationConfig] = None
    noise_filter: list[str] = Field(
        default_factory=lambda: ["__MACOSX/", "._*", "*.tmp"]
    )

    # Object/Warehouse contract properties
    object_config: Optional[ObjectLandingConfig] = None

    failure_route: FailureRoute = "REJECT_FILE"
    allow_encoding_fallback: bool = False
    required_groups: list[str] = Field(
        default_factory=lambda: ["property", "report_type", "date"]
    )

    def is_object_feed(self) -> bool:
        return self.feed_category in {"lake", "dwh"} or self.object_config is not None

    def is_file_feed(self) -> bool:
        return self.feed_category in {"pos", "pms", "res"} and self.object_config is None


class Gate1Finding(BaseModel):
    check_name: str
    passed: bool
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class Gate1Report(BaseModel):
    status: Gate1Status
    findings: list[Gate1Finding]
    captured_tokens: dict[str, Any] = Field(default_factory=dict)
    missing_atomic_members: list[str] = Field(default_factory=list)
    # Production telemetry (optional; defaults keep the public shape intact)
    total_rows: int = 0
    bytes_read: int = 0
    outcome_reason: str = ""


def to_python_named_groups(pattern: str) -> str:
    """Normalize JS `(?<name>...)` named groups to Python `(?P<name>...)`."""
    return pattern.replace("(?<", "(?P<")


def _as_list(raw: Any) -> list[str]:
    if not raw:
        return []
    if isinstance(raw, str):
        return [raw]
    if isinstance(raw, list):
        out: list[str] = []
        for item in raw:
            if isinstance(item, str):
                out.append(item)
            elif isinstance(item, dict) and item.get("pattern"):
                out.append(str(item["pattern"]))
        return out
    return []


def gate1_contract_from_yaml(
    contract_yaml: dict[str, Any],
    *,
    property_code: str = "",
    feed_category: Optional[str] = None,
    preset_id: Optional[str] = None,
) -> Gate1Contract:
    """
    Adapt Supabase / UI contract JSONB (and legacy Opera profiles) into Gate1Contract.
    """
    doc = contract_yaml if isinstance(contract_yaml, dict) else {}
    filename = doc.get("filename") if isinstance(doc.get("filename"), dict) else {}
    file_format = doc.get("file_format") if isinstance(doc.get("file_format"), dict) else {}
    if not file_format and isinstance(doc.get("physical"), dict):
        file_format = doc["physical"]
    atomic = doc.get("atomic_set") if isinstance(doc.get("atomic_set"), dict) else {}
    if not atomic and isinstance(doc.get("atomic_sets"), list) and doc["atomic_sets"]:
        first = doc["atomic_sets"][0] if isinstance(doc["atomic_sets"][0], dict) else {}
        atomic = {
            "is_multi_file": True,
            "required_endpoints": list(first.get("members") or []),
        }
    row_cls = (
        doc.get("row_classification")
        if isinstance(doc.get("row_classification"), dict)
        else {}
    )
    obj = doc.get("object_landing") if isinstance(doc.get("object_landing"), dict) else {}

    cat = str(
        feed_category
        or doc.get("feed_category")
        or ("lake" if obj else "pos")
    ).lower()
    if cat not in {"pos", "pms", "res", "lake", "dwh"}:
        cat = "lake" if obj else "pos"

    header_patterns = _as_list(
        row_cls.get("header_rules")
        or row_cls.get("header_patterns")
        or doc.get("header_patterns")
    )
    footer_patterns = _as_list(
        row_cls.get("footer_rules")
        or row_cls.get("footer_patterns")
        or doc.get("footer_patterns")
    )
    ignore_patterns = _as_list(
        row_cls.get("ignore_rules")
        or row_cls.get("ignore_patterns")
        or doc.get("ignore_patterns")
    )
    declaration = row_cls.get("row_count_declaration") or {}
    declared = None
    if isinstance(declaration, dict):
        declared = declaration.get("pattern")
    declared = declared or doc.get("declared_line_count_regex")

    line_cfg = None
    if header_patterns or footer_patterns or declared or ignore_patterns:
        line_cfg = LineConservationConfig(
            header_patterns=header_patterns,
            footer_patterns=footer_patterns,
            ignore_patterns=ignore_patterns,
            declared_count_regex=str(declared) if declared else None,
        )

    members: list[str] = []
    if atomic.get("is_multi_file") or atomic.get("is_multi_file_atomic_set"):
        members = list(
            atomic.get("required_endpoints")
            or atomic.get("required_set_endpoints")
            or atomic.get("members")
            or []
        )

    object_config = None
    if obj or cat in {"lake", "dwh"}:
        object_config = ObjectLandingConfig(
            format=obj.get("format") or "Parquet",
            partition_key=str(obj.get("partition_key") or "business_date"),
            watermark_column=str(obj.get("watermark_column") or "_ingested_at"),
            partition_path_template=str(
                obj.get("partition_path")
                or obj.get("partition_path_template")
                or "raw/{property}/{feed}/dt={date}/"
            ),
            require_commit_marker=bool(
                obj.get("require_commit_marker", True) if obj else True
            ),
            commit_marker=str(obj.get("commit_marker") or "_SUCCESS"),
        )

    path_regex = (
        filename.get("path_pattern")
        or filename.get("path_regex")
        or filename.get("uri_path_pattern")
    )
    path_agree = filename.get("path_agree")
    if path_agree is None:
        path_agree = True

    prop = (
        property_code
        or str(doc.get("property_code") or doc.get("property_id") or "")
    )
    preset = str(preset_id or doc.get("profile_id") or doc.get("preset_id") or "custom")

    encoding = str(file_format.get("encoding") or doc.get("encoding") or "UTF-8")
    delimiter = str(file_format.get("delimiter") or doc.get("delimiter") or ",")
    line_ending = str(file_format.get("line_ending") or "\n")
    if line_ending.lower() == "crlf":
        line_ending = "\r\n"
    elif line_ending.lower() == "lf":
        line_ending = "\n"

    noise = _as_list(doc.get("noise_filter")) or [
        "__MACOSX/",
        "._*",
        "*.tmp",
    ]

    failure = str(doc.get("failure_route") or "REJECT_FILE")
    if failure not in {"REJECT_FILE", "QUARANTINE_FILE"}:
        failure = "REJECT_FILE"

    pattern = filename.get("pattern") or doc.get("filename_regex")
    required = list(
        filename.get("required_groups") or ["property", "report_type", "date"]
    )

    return Gate1Contract(
        property_code=prop,
        feed_category=cat,  # type: ignore[arg-type]
        preset_id=preset,
        encoding=encoding,
        delimiter=delimiter,
        line_ending=line_ending,
        filename_regex=str(pattern) if pattern else None,
        sample_filename=doc.get("sample_filename"),
        path_agreement=bool(path_agree),
        path_regex=str(path_regex) if path_regex else None,
        atomic_set=members,
        line_conservation=line_cfg,
        noise_filter=noise,
        object_config=object_config,
        failure_route=failure,  # type: ignore[arg-type]
        allow_encoding_fallback=bool(
            file_format.get("allow_encoding_fallback")
            or doc.get("allow_encoding_fallback")
        ),
        required_groups=required,
    )
