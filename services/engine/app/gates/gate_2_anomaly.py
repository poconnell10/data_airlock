"""
Gate 2 — Anomaly Engine.

Core checks:
  G2_DUPLICATE_PAYLOAD  — identical SHA256 already RELEASED
  G2_OVERLAP_DRIFT      — same business date, different payload hash
  G2_FROZEN_WINDOW      — business date outside open accounting window
  G2_ZSCORE_ANOMALY     — rolling volume / net-amount z-score outliers
"""

from __future__ import annotations

import math
import statistics
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

from pydantic import BaseModel, Field

from app.models.common import GateOutcome, SubEvaluation, escalate

_RELEASED_OUTCOMES = frozenset({"RELEASED", "RELEASED_TO_ETL", "PASS_OVERRIDDEN"})
_CERTIFIED_OUTCOMES = frozenset(
    {
        "PASS",
        "FLAG",
        "RELEASED",
        "RELEASED_TO_ETL",
        "PASS_OVERRIDDEN",
    }
)
_BASELINE_OUTCOMES = frozenset({"PASS", "FLAG", "RELEASED_TO_ETL", "PASS_OVERRIDDEN"})


class Gate2Report(BaseModel):
    overall_outcome: GateOutcome
    outcome_reason: str = ""
    evaluations: list[SubEvaluation] = Field(default_factory=list)
    z_score: Optional[float] = None
    baseline_mean: Optional[float] = None
    baseline_std: Optional[float] = None
    baseline_n: int = 0
    payload_hash: Optional[str] = None
    skipped: bool = False


def _parse_date(value: Any) -> Optional[date]:
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    text = str(value).strip()
    if not text:
        return None
    # Normalize compact tokens like 20260811 → 2026-08-11
    if len(text) == 8 and text.isdigit():
        text = f"{text[:4]}-{text[4:6]}-{text[6:8]}"
    for fmt in ("%Y-%m-%d", "%Y%m%d", "%Y/%m/%d"):
        try:
            raw = text[:10] if fmt == "%Y-%m-%d" else text[:8]
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _row_count(rec: dict[str, Any]) -> Optional[int]:
    for key in ("accepted_rows", "total_rows", "row_count", "current_row_count"):
        if rec.get(key) is not None:
            try:
                return int(rec[key])
            except (TypeError, ValueError):
                continue
    accounting = rec.get("row_accounting") or {}
    if isinstance(accounting, dict):
        for key in ("accepted_rows", "total_read_rows", "data_rows", "total_rows"):
            if accounting.get(key) is not None:
                try:
                    return int(accounting[key])
                except (TypeError, ValueError):
                    continue
    raw = rec.get("raw_report") or {}
    if isinstance(raw, dict):
        for key in ("accepted_rows", "total_rows", "row_count"):
            if raw.get(key) is not None:
                try:
                    return int(raw[key])
                except (TypeError, ValueError):
                    continue
    return None


def _checksum(rec: dict[str, Any]) -> Optional[str]:
    for key in ("checksum_sha256", "payload_hash", "sha256"):
        if rec.get(key):
            return str(rec[key])
    identity = rec.get("file_identity") or {}
    if isinstance(identity, dict):
        for key in ("checksum_sha256", "payload_hash", "sha256"):
            if identity.get(key):
                return str(identity[key])
    raw = rec.get("raw_report") or {}
    if isinstance(raw, dict):
        for key in ("checksum_sha256", "payload_hash"):
            if raw.get(key):
                return str(raw[key])
        fi = raw.get("file_identity")
        if isinstance(fi, dict) and fi.get("checksum_sha256"):
            return str(fi["checksum_sha256"])
    return None


def _net_amount(rec: dict[str, Any]) -> Optional[float]:
    for key in ("net_amount", "net_sales", "total_amount", "revenue_total"):
        if rec.get(key) is not None:
            try:
                return float(rec[key])
            except (TypeError, ValueError):
                continue
    accounting = rec.get("row_accounting") or {}
    if isinstance(accounting, dict):
        for key in ("net_amount", "net_sales", "total_amount"):
            if accounting.get(key) is not None:
                try:
                    return float(accounting[key])
                except (TypeError, ValueError):
                    continue
    raw = rec.get("raw_report") or {}
    if isinstance(raw, dict):
        for key in ("net_amount", "net_sales", "total_amount"):
            if raw.get(key) is not None:
                try:
                    return float(raw[key])
                except (TypeError, ValueError):
                    continue
        gates = raw.get("gate_4") or raw.get("gate4_report") or {}
        if isinstance(gates, dict) and gates.get("net_sales") is not None:
            try:
                return float(gates["net_sales"])
            except (TypeError, ValueError):
                pass
    return None


def _safe_z(value: float, mean: float, std: float) -> float:
    if std == 0 or math.isclose(std, 0.0):
        return 0.0 if math.isclose(value, mean) else float("inf")
    return (value - mean) / std


def _filter_history(
    history: list[dict[str, Any]],
    *,
    property_id: Optional[str],
    report_type: Optional[str],
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for rec in history:
        if not isinstance(rec, dict):
            continue
        if property_id and rec.get("property_id") not in (None, property_id):
            continue
        if report_type and rec.get("report_type") not in (None, report_type):
            continue
        out.append(rec)
    return out


def evaluate_gate_2(
    run_reports_history: list,
    current_row_count: int,
    business_date: str,
    max_z_score: float = 2.5,
    *,
    property_id: Optional[str] = None,
    report_type: Optional[str] = None,
    current_checksum: Optional[str] = None,
    current_net_amount: Optional[float] = None,
    enforce_dow_baseline: bool = False,
    frozen_date_threshold_days: int = 30,
    rolling_window_days: int = 30,
    min_historical_samples: int = 7,
    amount_z_threshold: float = 3.0,
    as_of: Optional[date] = None,
    skip: bool = False,
    skip_reason: str = "",
) -> Gate2Report:
    """
    Stateless Gate 2 anomaly checks against historical run_reports.

    Outcomes:
      DUPLICATE_PAYLOAD / FROZEN_WINDOW → QUARANTINE_FILE
      OVERLAP_DRIFT / ZSCORE_ANOMALY    → FLAG
    """
    if skip:
        msg = skip_reason or "Gate 2 skipped because Gate 1 blocked the file."
        return Gate2Report(
            overall_outcome=GateOutcome.PASS,
            outcome_reason=msg,
            evaluations=[
                SubEvaluation(
                    rule_name="G2_SKIPPED",
                    passed=True,
                    message=msg,
                    details={"skipped": True},
                )
            ],
            payload_hash=current_checksum,
            skipped=True,
        )

    history = _filter_history(
        [r for r in (run_reports_history or []) if isinstance(r, dict)],
        property_id=property_id,
        report_type=report_type,
    )
    biz = _parse_date(business_date)
    today = as_of or datetime.now(timezone.utc).date()
    evaluations: list[SubEvaluation] = []
    overall = GateOutcome.PASS
    reasons: list[str] = []
    z_score: Optional[float] = None
    mean: Optional[float] = None
    std: Optional[float] = None
    baseline_n = 0

    # ------------------------------------------------------------------
    # 1) G2_DUPLICATE_PAYLOAD — identical hash already released
    # ------------------------------------------------------------------
    if not current_checksum:
        evaluations.append(
            SubEvaluation(
                rule_name="G2_DUPLICATE_PAYLOAD",
                passed=True,
                message="No payload hash provided; duplicate check skipped.",
                details={"skipped": True},
            )
        )
    else:
        dup_hits: list[dict[str, Any]] = []
        for rec in history:
            prior = _checksum(rec)
            if not prior or prior != current_checksum:
                continue
            outcome = str(rec.get("overall_outcome") or "").upper()
            if outcome not in _RELEASED_OUTCOMES:
                continue
            dup_hits.append(
                {
                    "run_id": rec.get("run_id"),
                    "business_date": str(rec.get("business_date") or ""),
                    "overall_outcome": outcome,
                }
            )
        if dup_hits:
            msg = (
                "FILE_ALREADY_INGESTED: Identical SHA256 payload hash exists "
                "in run history."
            )
            evaluations.append(
                SubEvaluation(
                    rule_name="G2_DUPLICATE_PAYLOAD",
                    passed=False,
                    message=msg,
                    details={
                        "suggested_category": "DUPLICATE_PAYLOAD",
                        "payload_hash": current_checksum,
                        "matches": dup_hits[:10],
                    },
                )
            )
            overall = escalate(overall, GateOutcome.QUARANTINE_FILE)
            reasons.append(msg)
        else:
            evaluations.append(
                SubEvaluation(
                    rule_name="G2_DUPLICATE_PAYLOAD",
                    passed=True,
                    message="Payload hash is not an already-released duplicate.",
                    details={
                        "suggested_category": "DUPLICATE_PAYLOAD",
                        "payload_hash": current_checksum,
                    },
                )
            )

    # ------------------------------------------------------------------
    # 2) G2_OVERLAP_DRIFT — same date certified, different hash
    # ------------------------------------------------------------------
    if biz is None or not current_checksum:
        evaluations.append(
            SubEvaluation(
                rule_name="G2_OVERLAP_DRIFT",
                passed=True,
                message="Overlap drift check skipped (missing date or hash).",
                details={"skipped": True},
            )
        )
    else:
        drift_hits: list[dict[str, Any]] = []
        for rec in history:
            prior_date = _parse_date(rec.get("business_date"))
            if prior_date != biz:
                continue
            outcome = str(rec.get("overall_outcome") or "").upper()
            if outcome not in _CERTIFIED_OUTCOMES:
                continue
            prior = _checksum(rec)
            if not prior or prior == current_checksum:
                continue
            drift_hits.append(
                {
                    "run_id": rec.get("run_id"),
                    "business_date": prior_date.isoformat(),
                    "prior_hash": prior,
                    "overall_outcome": outcome,
                }
            )
        if drift_hits:
            msg = (
                "OVERLAP_DRIFT_DETECTED: New payload received for an already "
                "certified business date."
            )
            evaluations.append(
                SubEvaluation(
                    rule_name="G2_OVERLAP_DRIFT",
                    passed=False,
                    message=msg,
                    details={
                        "suggested_category": "OVERLAP_DRIFT",
                        "payload_hash": current_checksum,
                        "conflicts": drift_hits[:10],
                    },
                )
            )
            overall = escalate(overall, GateOutcome.FLAG)
            reasons.append(msg)
        else:
            evaluations.append(
                SubEvaluation(
                    rule_name="G2_OVERLAP_DRIFT",
                    passed=True,
                    message="No modified-payload overlap for this business date.",
                    details={
                        "suggested_category": "OVERLAP_DRIFT",
                        "business_date": biz.isoformat(),
                    },
                )
            )

    # ------------------------------------------------------------------
    # 3) G2_FROZEN_WINDOW — date older than open accounting window
    # ------------------------------------------------------------------
    if biz is None:
        evaluations.append(
            SubEvaluation(
                rule_name="G2_FROZEN_WINDOW",
                passed=False,
                message="FROZEN_WINDOW_VIOLATION: unparseable business_date.",
                details={
                    "suggested_category": "FROZEN_PERIOD_ATTEMPT",
                    "business_date": business_date,
                },
            )
        )
        overall = escalate(overall, GateOutcome.QUARANTINE_FILE)
        reasons.append("Unparseable business_date for frozen window.")
    else:
        cutoff = today - timedelta(days=max(0, frozen_date_threshold_days))
        if biz < cutoff:
            msg = (
                "FROZEN_WINDOW_VIOLATION: Business date is outside the open "
                "accounting window."
            )
            evaluations.append(
                SubEvaluation(
                    rule_name="G2_FROZEN_WINDOW",
                    passed=False,
                    message=msg,
                    details={
                        "suggested_category": "FROZEN_PERIOD_ATTEMPT",
                        "business_date": biz.isoformat(),
                        "cutoff": cutoff.isoformat(),
                        "max_allowed_age_days": frozen_date_threshold_days,
                    },
                )
            )
            overall = escalate(overall, GateOutcome.QUARANTINE_FILE)
            reasons.append(msg)
        else:
            evaluations.append(
                SubEvaluation(
                    rule_name="G2_FROZEN_WINDOW",
                    passed=True,
                    message="Business date is within the open accounting window.",
                    details={
                        "suggested_category": "FROZEN_PERIOD_ATTEMPT",
                        "business_date": biz.isoformat(),
                        "cutoff": cutoff.isoformat(),
                        "max_allowed_age_days": frozen_date_threshold_days,
                    },
                )
            )

    # ------------------------------------------------------------------
    # 4) G2_ZSCORE_ANOMALY — rolling volume (+ optional net amount)
    # ------------------------------------------------------------------
    if biz is None:
        evaluations.append(
            SubEvaluation(
                rule_name="G2_ZSCORE_ANOMALY",
                passed=True,
                message="Z-score check skipped: unparseable business_date.",
                details={"skipped": True},
            )
        )
    else:
        window_start = biz - timedelta(days=max(1, rolling_window_days))
        row_cohort: list[int] = []
        amount_cohort: list[float] = []
        for rec in history:
            rec_date = _parse_date(rec.get("business_date"))
            if rec_date is None or rec_date < window_start or rec_date >= biz:
                continue
            if enforce_dow_baseline and rec_date.weekday() != biz.weekday():
                continue
            outcome = str(rec.get("overall_outcome") or "PASS").upper()
            if outcome not in _BASELINE_OUTCOMES:
                continue
            count = _row_count(rec)
            if count is not None:
                row_cohort.append(count)
            amt = _net_amount(rec)
            if amt is not None:
                amount_cohort.append(amt)

        baseline_n = len(row_cohort)
        details: dict[str, Any] = {
            "suggested_category": "FALSE_POSITIVE",
            "window_days": rolling_window_days,
            "baseline_n": baseline_n,
            "current_row_count": current_row_count,
            "row_z_threshold": max_z_score,
            "amount_z_threshold": amount_z_threshold,
            "enforce_dow_baseline": enforce_dow_baseline,
            "min_historical_samples": min_historical_samples,
        }

        if baseline_n < max(1, min_historical_samples):
            evaluations.append(
                SubEvaluation(
                    rule_name="G2_ZSCORE_ANOMALY",
                    passed=True,
                    message=(
                        f"Insufficient historical samples (n={baseline_n}); "
                        "z-score check skipped (cold-start)."
                    ),
                    details={**details, "skipped": True, "cold_start": True},
                )
            )
        else:
            mean = statistics.fmean(row_cohort)
            std = statistics.pstdev(row_cohort)
            z_score = _safe_z(float(current_row_count), mean, std)
            abs_z = abs(z_score) if not math.isinf(z_score) else float("inf")
            details["baseline_mean"] = mean
            details["baseline_std"] = std
            details["z_score"] = None if math.isinf(z_score) else round(z_score, 4)

            amount_z: Optional[float] = None
            if (
                current_net_amount is not None
                and len(amount_cohort) >= max(1, min_historical_samples)
            ):
                a_mean = statistics.fmean(amount_cohort)
                a_std = statistics.pstdev(amount_cohort)
                amount_z = _safe_z(float(current_net_amount), a_mean, a_std)
                details["amount_baseline_n"] = len(amount_cohort)
                details["amount_mean"] = a_mean
                details["amount_std"] = a_std
                details["amount_z_score"] = (
                    None if math.isinf(amount_z) else round(amount_z, 4)
                )
                details["current_net_amount"] = current_net_amount

            row_fail = abs_z > max_z_score
            amount_fail = (
                amount_z is not None
                and (
                    abs(amount_z) if not math.isinf(amount_z) else float("inf")
                )
                > amount_z_threshold
            )

            if row_fail or amount_fail:
                z_disp = "inf" if math.isinf(abs_z) else f"{z_score:.2f}"
                parts = [
                    f"row_count Z={z_disp} (threshold ±{max_z_score})",
                ]
                if amount_z is not None:
                    az = (
                        "inf"
                        if math.isinf(amount_z)
                        else f"{amount_z:.2f}"
                    )
                    parts.append(
                        f"net_amount Z={az} (threshold ±{amount_z_threshold})"
                    )
                msg = (
                    "G2_ZSCORE_ANOMALY: Volume/financial variance exceeds "
                    f"rolling baseline — {'; '.join(parts)}."
                )
                evaluations.append(
                    SubEvaluation(
                        rule_name="G2_ZSCORE_ANOMALY",
                        passed=False,
                        message=msg,
                        details=details,
                    )
                )
                overall = escalate(overall, GateOutcome.FLAG)
                reasons.append(msg)
            else:
                z_ok = "inf" if math.isinf(abs_z) else f"{abs_z:.2f}"
                evaluations.append(
                    SubEvaluation(
                        rule_name="G2_ZSCORE_ANOMALY",
                        passed=True,
                        message=f"Volume within rolling baseline (|z|={z_ok}).",
                        details=details,
                    )
                )

    return Gate2Report(
        overall_outcome=overall,
        outcome_reason="; ".join(reasons)
        if reasons
        else "All Gate 2 anomaly checks passed.",
        evaluations=evaluations,
        z_score=None
        if z_score is None or (isinstance(z_score, float) and math.isinf(z_score))
        else round(z_score, 4),
        baseline_mean=None if mean is None else round(mean, 4),
        baseline_std=None if std is None else round(std, 4),
        baseline_n=baseline_n,
        payload_hash=current_checksum,
    )


# Prompt alias
evaluate_gate2 = evaluate_gate_2
