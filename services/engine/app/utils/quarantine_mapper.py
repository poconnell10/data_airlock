"""Quarantine category mapping + readiness / manifest enrichment."""

from __future__ import annotations

import csv
import io
from typing import Any, Iterable, Optional

from app.models.report import (
    QuarantineCategory,
    QuarantineManifestItem,
    ReadinessStats,
)

# Canonical rule_id → default operator category
RULE_CATEGORY_MAP: dict[str, QuarantineCategory] = {
    "G1_PHYSICAL_INTEGRITY": QuarantineCategory.DATA_QUALITY_BUG,
    "G1_FILENAME_IDENTITY": QuarantineCategory.VENDOR_CONFIG_CHANGE,
    "G1_PATH_AGREEMENT": QuarantineCategory.VENDOR_CONFIG_CHANGE,
    "G1_UNREGISTERED_ENDPOINT": QuarantineCategory.VENDOR_CONFIG_CHANGE,
    "G1_EMPTY_PAYLOAD": QuarantineCategory.VENDOR_CONFIG_CHANGE,
    "G2_DUPLICATE_PAYLOAD": QuarantineCategory.DUPLICATE_PAYLOAD,
    "G2_OVERLAP_DRIFT": QuarantineCategory.OVERLAP_DRIFT,
    "G2_FROZEN_WINDOW": QuarantineCategory.FROZEN_PERIOD_ATTEMPT,
    "G2_VOLUME_ANOMALY": QuarantineCategory.OVERLAP_DRIFT,
    "G2_ZSCORE_ANOMALY": QuarantineCategory.FALSE_POSITIVE,
    "G3_RAGGED_ROW": QuarantineCategory.DATA_QUALITY_BUG,
    "G3_TYPE_CAST_FAIL": QuarantineCategory.DATA_QUALITY_BUG,
    "G3_UNMAPPED_RVC": QuarantineCategory.UNMAPPED_ENTITY,
    "G4_FINANCIAL_IMBALANCE": QuarantineCategory.UNBALANCED_REVENUE,
    "G4_UNBALANCED_HEADER": QuarantineCategory.UNBALANCED_REVENUE,
    "G4_ZERO_COVER_REVENUE": QuarantineCategory.BUSINESS_EDGE_CASE,
    "G4_FULL_COMP": QuarantineCategory.BUSINESS_EDGE_CASE,
}

# File / physical-level rules (whole-file impact; affected_rows = 0)
FILE_LEVEL_RULE_IDS: set[str] = {
    "G1_PHYSICAL_INTEGRITY",
    "G1_FILENAME_IDENTITY",
    "G1_PATH_AGREEMENT",
    "G1_UNREGISTERED_ENDPOINT",
    "G1_EMPTY_PAYLOAD",
    "G1_NOISE_FILTER",
    "G1_PROPERTY_CODE",
    "G2_DUPLICATE_PAYLOAD",
    "G2_OVERLAP_DRIFT",
    "G2_FROZEN_WINDOW",
    "G2_VOLUME_ANOMALY",
    "G2_ZSCORE_ANOMALY",
    "G4_FINANCIAL_IMBALANCE",
    "G4_UNBALANCED_HEADER",
    "G4_ZERO_COVER_REVENUE",
    "G4_FULL_COMP",
}

# Engine check_name / rule_name aliases → canonical rule_id
_RULE_ALIASES: dict[str, str] = {
    "physical_integrity": "G1_PHYSICAL_INTEGRITY",
    "g1_physical_integrity": "G1_PHYSICAL_INTEGRITY",
    "filename": "G1_FILENAME_IDENTITY",
    "filename_identity": "G1_FILENAME_IDENTITY",
    "g1_filename_identity": "G1_FILENAME_IDENTITY",
    "path_agreement": "G1_PATH_AGREEMENT",
    "g1_path_agreement": "G1_PATH_AGREEMENT",
    "endpoint_registered": "G1_UNREGISTERED_ENDPOINT",
    "g1_unregistered_endpoint": "G1_UNREGISTERED_ENDPOINT",
    "unregistered_endpoint": "G1_UNREGISTERED_ENDPOINT",
    "non_empty_payload": "G1_EMPTY_PAYLOAD",
    "g1_empty_payload": "G1_EMPTY_PAYLOAD",
    "empty_payload": "G1_EMPTY_PAYLOAD",
    "noise_filter": "G1_NOISE_FILTER",
    "property_code": "G1_PROPERTY_CODE",
    "duplicate_payload": "G2_DUPLICATE_PAYLOAD",
    "g2_duplicate_payload": "G2_DUPLICATE_PAYLOAD",
    "hash_drift": "G2_DUPLICATE_PAYLOAD",
    "overlapping_hash": "G2_DUPLICATE_PAYLOAD",
    "overlap_drift": "G2_OVERLAP_DRIFT",
    "g2_overlap_drift": "G2_OVERLAP_DRIFT",
    "frozen_window": "G2_FROZEN_WINDOW",
    "g2_frozen_window": "G2_FROZEN_WINDOW",
    "frozen_date": "G2_FROZEN_WINDOW",
    "frozen_date_window": "G2_FROZEN_WINDOW",
    "volume_z_score": "G2_ZSCORE_ANOMALY",
    "z_score": "G2_ZSCORE_ANOMALY",
    "dow_volume_zscore": "G2_ZSCORE_ANOMALY",
    "g2_zscore_anomaly": "G2_ZSCORE_ANOMALY",
    "g2_volume_anomaly": "G2_VOLUME_ANOMALY",
    "ragged_row": "G3_RAGGED_ROW",
    "g3_ragged_row": "G3_RAGGED_ROW",
    "type_cast_fail": "G3_TYPE_CAST_FAIL",
    "g3_type_cast_fail": "G3_TYPE_CAST_FAIL",
    "numeric_column_integrity": "G3_TYPE_CAST_FAIL",
    "unmapped_rvc": "G3_UNMAPPED_RVC",
    "g3_unmapped_rvc": "G3_UNMAPPED_RVC",
    "unbalanced_header": "G4_UNBALANCED_HEADER",
    "g4_unbalanced_header": "G4_UNBALANCED_HEADER",
    "header_vs_line_balance": "G4_FINANCIAL_IMBALANCE",
    "sales_vs_tender_balance": "G4_FINANCIAL_IMBALANCE",
    "financial_imbalance": "G4_FINANCIAL_IMBALANCE",
    "g4_financial_imbalance": "G4_FINANCIAL_IMBALANCE",
    "zero_cover_revenue": "G4_ZERO_COVER_REVENUE",
    "g4_zero_cover_revenue": "G4_ZERO_COVER_REVENUE",
    "full_comp": "G4_FULL_COMP",
    "g4_full_comp": "G4_FULL_COMP",
}


def normalize_rule_id(raw: str, *, message: str = "") -> str:
    """Map engine rule/check names onto canonical G{n}_* rule ids."""
    text = (raw or "").strip()
    if not text:
        return "UNKNOWN"
    upper = text.upper()
    if upper in RULE_CATEGORY_MAP or upper in FILE_LEVEL_RULE_IDS:
        return upper
    key = text.lower().replace("-", "_").replace(" ", "_")
    if key in _RULE_ALIASES:
        return _RULE_ALIASES[key]
    msg = message or ""
    if "PHYSICAL_INTEGRITY_FAIL" in msg or "decode error" in msg.lower():
        return "G1_PHYSICAL_INTEGRITY"
    if "EMPTY_PAYLOAD" in msg:
        return "G1_EMPTY_PAYLOAD"
    if "UNREGISTERED_ENDPOINT" in msg:
        return "G1_UNREGISTERED_ENDPOINT"
    if "Financial imbalance" in msg or (
        "Net sales" in msg and "Tender" in msg
    ):
        return "G4_FINANCIAL_IMBALANCE"
    if "100%" in msg and ("comp" in msg.lower() or "discount" in msg.lower()):
        return "G4_FULL_COMP"
    if "zero cover" in msg.lower() or "0 guest" in msg.lower():
        return "G4_ZERO_COVER_REVENUE"
    return upper if upper.startswith("G") else text


def suggest_category(rule_id: str) -> QuarantineCategory:
    rid = normalize_rule_id(rule_id)
    return RULE_CATEGORY_MAP.get(rid, QuarantineCategory.DATA_QUALITY_BUG)


def is_file_level_rule(rule_id: str) -> bool:
    return normalize_rule_id(rule_id) in FILE_LEVEL_RULE_IDS


def compute_readiness_stats(
    total_rows: int,
    quarantined_rows: int,
    *,
    outcome: Optional[str] = None,
) -> ReadinessStats:
    """
    File-level rejection / empty payload → 0% ready, 100% quarantine.
    Otherwise readiness_pct = (verified_rows / total_rows) * 100.
    """
    total = max(0, int(total_rows or 0))
    quarantined = max(0, int(quarantined_rows or 0))
    outcome_u = str(outcome or "").strip().upper()

    if total == 0 or outcome_u in ["REJECT_FILE", "QUARANTINE_FILE"]:
        return ReadinessStats(
            total_rows=total,
            verified_rows=0,
            quarantined_rows=total if total > 0 else 1,
            readiness_pct=0.0,
            quarantine_pct=100.0,
        )

    quarantined = min(quarantined, total)
    verified = total - quarantined
    readiness_pct = round((verified / total) * 100.0, 2)
    quarantine_pct = round((quarantined / total) * 100.0, 2)
    return ReadinessStats(
        total_rows=total,
        verified_rows=verified,
        quarantined_rows=quarantined,
        readiness_pct=readiness_pct,
        quarantine_pct=quarantine_pct,
    )


# Prompt alias
calculate_readiness_stats = compute_readiness_stats


def decision_guidance_for(
    rule_id: str,
    category: QuarantineCategory,
    *,
    is_file_level: bool,
    message: str = "",
) -> str:
    """Operator-facing guidance copy for decision cards."""
    rid = normalize_rule_id(rule_id, message=message)
    msg_l = (message or "").lower()

    if category == QuarantineCategory.UNBALANCED_REVENUE or rid in {
        "G4_FINANCIAL_IMBALANCE",
        "G4_UNBALANCED_HEADER",
    }:
        return (
            "Financial balance variance detected between sales and payments "
            "tender. Decide whether to declare short or reject payload."
        )
    if category == QuarantineCategory.BUSINESS_EDGE_CASE or rid in {
        "G4_ZERO_COVER_REVENUE",
        "G4_FULL_COMP",
    }:
        return (
            "Unusual business transaction detected (e.g. 100% comp, zero "
            "covers). Confirm this is an operational exception."
        )
    if category == QuarantineCategory.FALSE_POSITIVE or rid.startswith(
        "G2_VOLUME"
    ) or rid == "G2_ZSCORE_ANOMALY":
        return (
            "Statistical volume/revenue threshold breached. Confirm whether "
            "this anomaly is business-valid before release."
        )
    if category == QuarantineCategory.OVERLAP_DRIFT or rid == "G2_OVERLAP_DRIFT":
        return (
            "Certified historical data exists for this date with different "
            "checksums. Decide whether to overwrite the baseline."
        )
    if (
        is_file_level
        or rid == "G1_PHYSICAL_INTEGRITY"
        or "decode error" in msg_l
        or "physical integrity" in msg_l
    ):
        return (
            "File-level physical integrity failure. Data encoding or file "
            "format is corrupted."
        )
    if category == QuarantineCategory.DATA_QUALITY_BUG:
        return (
            "Row-level data quality failure. Inspect sample diagnostics and "
            "decide whether to reject, retag as false positive, or redrive."
        )
    if category == QuarantineCategory.VENDOR_CONFIG_CHANGE:
        return (
            "Vendor configuration or endpoint registration mismatch. Open a "
            "vendor ticket or update the airlock contract."
        )
    return message or "Review the failing rule and choose an adjudication action."


def _extract_row_indices(details: dict[str, Any]) -> list[int]:
    indices: list[int] = []
    if not isinstance(details, dict):
        return indices

    for key in ("row_indices", "failed_row_indices", "offending_rows"):
        raw = details.get(key)
        if isinstance(raw, list):
            for v in raw:
                try:
                    indices.append(int(v))
                except (TypeError, ValueError):
                    continue

    failures = details.get("failures")
    if isinstance(failures, list):
        for item in failures:
            if not isinstance(item, dict):
                continue
            for k in ("row_index", "row", "index", "line_index"):
                if item.get(k) is None:
                    continue
                try:
                    indices.append(int(item[k]))
                except (TypeError, ValueError):
                    pass

    seen: set[int] = set()
    out: list[int] = []
    for i in indices:
        if i in seen:
            continue
        seen.add(i)
        out.append(i)
    return out


def _parse_sample_records(
    payload_text: str,
    row_indices: list[int],
    *,
    delimiter: str = ",",
    limit: int = 3,
) -> list[dict[str, Any]]:
    if not payload_text or not row_indices:
        return []
    try:
        reader = csv.DictReader(io.StringIO(payload_text), delimiter=delimiter)
        rows = list(reader)
    except Exception:
        lines = payload_text.splitlines()
        samples: list[dict[str, Any]] = []
        for idx in row_indices[:limit]:
            if 0 <= idx < len(lines):
                samples.append({"_raw": lines[idx], "_row_index": idx})
        return samples

    samples = []
    for idx in row_indices[:limit]:
        if 0 <= idx < len(rows):
            rec = dict(rows[idx])
            rec["_row_index"] = idx
            samples.append(rec)
    return samples


def _iter_failed_evals(gate_blob: Any) -> Iterable[dict[str, Any]]:
    if gate_blob is None:
        return
    if hasattr(gate_blob, "model_dump"):
        gate_blob = gate_blob.model_dump(mode="json")
    if not isinstance(gate_blob, dict):
        return
    evaluations = gate_blob.get("evaluations") or gate_blob.get("findings") or []
    if not isinstance(evaluations, list):
        return
    for ev in evaluations:
        if hasattr(ev, "model_dump"):
            ev = ev.model_dump(mode="json")
        if not isinstance(ev, dict):
            continue
        passed = ev.get("passed")
        if passed is True:
            continue
        # Skip "skipped" placeholder findings
        details = ev.get("details") if isinstance(ev.get("details"), dict) else {}
        if details.get("skipped") is True:
            continue
        yield ev


def _gate_key_is_file_level(gate_key: str) -> bool:
    key = (gate_key or "").lower().replace("-", "_")
    return key in {
        "gate_1",
        "gate1",
        "g1",
        "gate_2",
        "gate2",
        "g2",
        "gate_4",
        "gate4",
        "g4",
    }


def _enrich_gate4_message(message: str, details: dict[str, Any]) -> str:
    """Ensure financial imbalance messages include an explicit Variance: amount."""
    text = message or ""
    if "Variance:" in text or "variance" in (details or {}):
        variance = details.get("variance")
        if variance is not None and "Variance:" not in text:
            text = f"{text.rstrip('.')} Variance: {float(variance):.2f}."
        return text
    # Try to derive from amounts in details
    for left_key, right_key in (
        ("net_sales", "tender_payments"),
        ("header_total", "line_sum"),
    ):
        left = details.get(left_key)
        right = details.get(right_key)
        if left is None or right is None:
            continue
        try:
            variance = abs(float(left) - float(right))
            if "Financial imbalance" in text:
                return f"{text.rstrip('.')} Variance: {variance:.2f}."
            return (
                f"Financial imbalance detected: "
                f"{left_key.replace('_', ' ').title()} ${float(left):.2f} "
                f"vs {right_key.replace('_', ' ').title()} ${float(right):.2f}. "
                f"Variance: {variance:.2f}."
            )
        except (TypeError, ValueError):
            continue
    return text


def build_quarantine_manifest(
    *,
    gate_reports: dict[str, Any],
    payload_text: str = "",
    delimiter: str = ",",
    outcome: Optional[str] = None,
    outcome_reason: str = "",
) -> list[QuarantineManifestItem]:
    """
    Group failing evaluations into QuarantineManifestItem rows.

    Scans Gates 1–4. Gate 1/2/4 physical/macro failures get affected_rows=0.
    """
    items: list[QuarantineManifestItem] = []
    for gate_key, report in (gate_reports or {}).items():
        for ev in _iter_failed_evals(report):
            raw_name = (
                ev.get("rule_name")
                or ev.get("check_name")
                or ev.get("rule_id")
                or "UNKNOWN"
            )
            message = str(ev.get("message") or "")
            details = ev.get("details") if isinstance(ev.get("details"), dict) else {}
            if str(gate_key).lower() in {"gate_4", "gate4", "g4"} or str(
                raw_name
            ).lower() in {
                "sales_vs_tender_balance",
                "header_vs_line_balance",
            }:
                message = _enrich_gate4_message(message, details or {})

            rule_id = normalize_rule_id(str(raw_name), message=message)
            if str(raw_name).upper() in RULE_CATEGORY_MAP:
                rule_id = str(raw_name).upper()

            indices = _extract_row_indices(details or {})
            file_level = (
                is_file_level_rule(rule_id)
                or (_gate_key_is_file_level(str(gate_key)) and not indices)
            )

            if file_level and not indices:
                affected = 0
            else:
                affected = int(details.get("affected_rows") or 0) if details else 0
                if not affected:
                    affected = len(indices) if indices else 1

            samples = _parse_sample_records(
                payload_text, indices, delimiter=delimiter, limit=3
            )
            if not samples and isinstance(details.get("sample_records"), list):
                samples = [
                    r for r in details["sample_records"] if isinstance(r, dict)
                ][:3]

            category = suggest_category(rule_id)
            if file_level and not indices and rule_id in {
                "G1_PHYSICAL_INTEGRITY",
                "G1_EMPTY_PAYLOAD",
            }:
                category = QuarantineCategory.DATA_QUALITY_BUG
            if rule_id in {"G4_FINANCIAL_IMBALANCE", "G4_UNBALANCED_HEADER"}:
                category = QuarantineCategory.UNBALANCED_REVENUE

            items.append(
                QuarantineManifestItem(
                    rule_id=rule_id,
                    affected_rows=affected,
                    row_indices=indices,
                    suggested_category=category,
                    message=message,
                    sample_records=samples,
                    is_file_level=bool(file_level and not indices),
                    decision_guidance=decision_guidance_for(
                        rule_id,
                        category,
                        is_file_level=bool(file_level and not indices),
                        message=message,
                    ),
                )
            )

    # Guarantee at least one manifest item when the run is blocked/flagged
    outcome_u = str(outcome or "").strip().upper()
    if not items and outcome_u in {
        "REJECT_FILE",
        "QUARANTINE_FILE",
        "FLAG",
        "FLAGGED",
        "HOLD_SET",
    }:
        reason = (outcome_reason or "Run blocked without detailed sub-check findings.").strip()
        rule_id = normalize_rule_id("", message=reason)
        if rule_id in {"", "UNKNOWN"}:
            rule_id = "G4_FINANCIAL_IMBALANCE" if "imbalance" in reason.lower() or "variance" in reason.lower() else "RUN_BLOCKED"
        category = suggest_category(rule_id)
        if "imbalance" in reason.lower() or "tender" in reason.lower():
            category = QuarantineCategory.UNBALANCED_REVENUE
            rule_id = "G4_FINANCIAL_IMBALANCE"
        items.append(
            QuarantineManifestItem(
                rule_id=rule_id,
                affected_rows=0,
                row_indices=[],
                suggested_category=category,
                message=reason,
                sample_records=[],
                is_file_level=True,
                decision_guidance=decision_guidance_for(
                    rule_id, category, is_file_level=True, message=reason
                ),
            )
        )
    return items


def quarantined_row_count(manifest: list[QuarantineManifestItem]) -> int:
    """Unique offending row indices across the manifest (fallback to sum)."""
    seen: set[int] = set()
    for item in manifest:
        for idx in item.row_indices:
            seen.add(idx)
    if seen:
        return len(seen)
    # File-level items (affected_rows=0) do not contribute row counts
    return sum(max(0, int(item.affected_rows or 0)) for item in manifest)


def enrich_execution_diagnostics(
    *,
    total_rows: int,
    gate_reports: dict[str, Any],
    payload_text: str = "",
    delimiter: str = ",",
    outcome: Optional[str] = None,
    outcome_reason: str = "",
) -> tuple[ReadinessStats, list[QuarantineManifestItem]]:
    manifest = build_quarantine_manifest(
        gate_reports=gate_reports,
        payload_text=payload_text,
        delimiter=delimiter,
        outcome=outcome,
        outcome_reason=outcome_reason,
    )
    q_rows = quarantined_row_count(manifest)
    # Row-level fallback when indices missing but affected_rows > 0
    if q_rows == 0 and manifest and total_rows > 0:
        row_level_affected = [
            int(i.affected_rows or 0)
            for i in manifest
            if int(i.affected_rows or 0) > 0
        ]
        if row_level_affected:
            q_rows = min(total_rows, max(row_level_affected))

    stats = compute_readiness_stats(
        total_rows, q_rows, outcome=outcome
    )
    return stats, manifest


def apply_user_classifications(
    manifest: list[dict[str, Any]] | list[QuarantineManifestItem],
    patches: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Merge operator category/notes onto matching rule_id entries."""
    by_rule = {
        str(p.get("rule_id")): p
        for p in patches
        if isinstance(p, dict) and p.get("rule_id")
    }
    out: list[dict[str, Any]] = []
    for item in manifest:
        data = item.model_dump(mode="json") if hasattr(item, "model_dump") else dict(item)
        patch = by_rule.get(str(data.get("rule_id")))
        if patch:
            cat = patch.get("user_category")
            if cat is not None:
                data["user_category"] = (
                    cat.value if isinstance(cat, QuarantineCategory) else str(cat)
                )
            if "user_notes" in patch:
                data["user_notes"] = patch.get("user_notes")
        out.append(data)
    return out
