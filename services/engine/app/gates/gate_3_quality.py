"""
Gate 3 — Data Quality (required columns, non-null, numeric bounds).
"""

from __future__ import annotations

from typing import Any, Optional

import polars as pl
from pydantic import BaseModel, Field

from app.models.common import GateOutcome, SubEvaluation, escalate


class Gate3Report(BaseModel):
    overall_outcome: GateOutcome
    outcome_reason: str = ""
    evaluations: list[SubEvaluation] = Field(default_factory=list)


def evaluate_gate_3(
    df_sample: pl.DataFrame,
    quality_rules: dict,
) -> Gate3Report:
    """Evaluate structural / value quality rules against a Polars sample frame."""
    rules = quality_rules if isinstance(quality_rules, dict) else {}
    evaluations: list[SubEvaluation] = []
    overall = GateOutcome.PASS
    reasons: list[str] = []

    if df_sample is None or df_sample.is_empty() and df_sample.width == 0:
        return Gate3Report(
            overall_outcome=GateOutcome.QUARANTINE_FILE,
            outcome_reason="Quality check failed: empty dataframe sample.",
            evaluations=[
                SubEvaluation(
                    rule_name="dataframe_present",
                    passed=False,
                    message="No dataframe sample available for Gate 3.",
                )
            ],
        )

    columns = set(df_sample.columns)

    # Required columns
    required = list(rules.get("required_columns") or [])
    missing = [c for c in required if c not in columns]
    if required:
        if missing:
            msg = f"Required columns missing: {missing}."
            evaluations.append(
                SubEvaluation(
                    rule_name="required_columns",
                    passed=False,
                    message=msg,
                    details={"required_columns": required, "missing": missing},
                )
            )
            overall = escalate(overall, GateOutcome.QUARANTINE_FILE)
            reasons.append(msg)
        else:
            evaluations.append(
                SubEvaluation(
                    rule_name="required_columns",
                    passed=True,
                    message="All required columns present.",
                    details={"required_columns": required},
                )
            )
    else:
        evaluations.append(
            SubEvaluation(
                rule_name="required_columns",
                passed=True,
                message="No required_columns configured.",
                details={"skipped": True},
            )
        )

    # Non-null constraints
    non_null_cols = list(
        rules.get("non_null_columns")
        or rules.get("required_non_null")
        or []
    )
    null_failures: list[dict[str, Any]] = []
    for col in non_null_cols:
        if col not in columns:
            null_failures.append({"column": col, "error": "column_missing"})
            continue
        null_count = int(df_sample.get_column(col).null_count())
        if null_count > 0:
            null_failures.append({"column": col, "null_count": null_count})

    if non_null_cols:
        if null_failures:
            msg = f"Non-null constraints failed: {null_failures}."
            evaluations.append(
                SubEvaluation(
                    rule_name="non_null_constraints",
                    passed=False,
                    message=msg,
                    details={"failures": null_failures},
                )
            )
            overall = escalate(overall, GateOutcome.QUARANTINE_FILE)
            reasons.append("Non-null constraints violated.")
        else:
            evaluations.append(
                SubEvaluation(
                    rule_name="non_null_constraints",
                    passed=True,
                    message="Non-null constraints satisfied.",
                    details={"non_null_columns": non_null_cols},
                )
            )
    else:
        evaluations.append(
            SubEvaluation(
                rule_name="non_null_constraints",
                passed=True,
                message="No non-null columns configured.",
                details={"skipped": True},
            )
        )

    # Numeric columns — catch mid-stream string poison (e.g. "ERR") that
    # would otherwise become null under loose Float64 casts.
    numeric_cols = list(rules.get("numeric_columns") or [])
    range_rules = list(rules.get("numeric_ranges") or rules.get("value_ranges") or [])
    for rule in range_rules:
        if isinstance(rule, dict):
            col = rule.get("column_name") or rule.get("column")
            if col and col not in numeric_cols:
                numeric_cols.append(str(col))

    poison_failures: list[dict[str, Any]] = []
    for col in numeric_cols:
        if col not in columns:
            poison_failures.append({"column": col, "error": "column_missing"})
            continue
        series = df_sample.get_column(col)
        loose = series.cast(pl.Float64, strict=False)
        # Non-null originals that failed numeric cast → poison tokens
        poisoned_mask = series.is_not_null() & loose.is_null()
        # Also catch Utf8/String dtype values that are non-numeric text
        if series.dtype in (pl.Utf8, pl.String) or str(series.dtype).startswith("String"):
            for idx, (raw, casted) in enumerate(
                zip(series.to_list(), loose.to_list())
            ):
                if raw is None:
                    continue
                if casted is None:
                    poison_failures.append(
                        {
                            "column": col,
                            "row_index": idx,
                            "poison_value": str(raw),
                            "error": "non_numeric_value",
                        }
                    )
        elif int(poisoned_mask.sum()) > 0:
            for idx, (raw, is_poison) in enumerate(
                zip(series.to_list(), poisoned_mask.to_list())
            ):
                if is_poison:
                    poison_failures.append(
                        {
                            "column": col,
                            "row_index": idx,
                            "poison_value": str(raw),
                            "error": "non_numeric_value",
                        }
                    )

    if numeric_cols or any(
        isinstance(r, dict) and (r.get("column_name") or r.get("column"))
        for r in range_rules
    ):
        if poison_failures:
            msg = f"Numeric column poison detected: {poison_failures}."
            evaluations.append(
                SubEvaluation(
                    rule_name="numeric_column_integrity",
                    passed=False,
                    message=msg,
                    details={"failures": poison_failures},
                )
            )
            overall = escalate(overall, GateOutcome.QUARANTINE_FILE)
            reasons.append("Non-numeric values found in numeric columns.")
        elif numeric_cols:
            evaluations.append(
                SubEvaluation(
                    rule_name="numeric_column_integrity",
                    passed=True,
                    message="Numeric columns contain only parseable values.",
                    details={"numeric_columns": numeric_cols},
                )
            )

    # Numeric range bounds
    range_failures: list[dict[str, Any]] = []
    for rule in range_rules:
        if not isinstance(rule, dict):
            continue
        col = rule.get("column_name") or rule.get("column")
        if not col:
            continue
        if col not in columns:
            range_failures.append({"column": col, "error": "column_missing"})
            continue
        series = df_sample.get_column(col)
        try:
            numeric = series.cast(pl.Float64, strict=False)
        except Exception:  # noqa: BLE001
            range_failures.append({"column": col, "error": "not_numeric"})
            continue

        min_value = rule.get("min_value")
        max_value = rule.get("max_value")
        if min_value is not None:
            below = numeric.filter(numeric.is_not_null() & (numeric < float(min_value)))
            if below.len() > 0:
                range_failures.append(
                    {
                        "column": col,
                        "violation": "min",
                        "min_value": min_value,
                        "failing_rows": below.len(),
                    }
                )
        if max_value is not None:
            above = numeric.filter(numeric.is_not_null() & (numeric > float(max_value)))
            if above.len() > 0:
                range_failures.append(
                    {
                        "column": col,
                        "violation": "max",
                        "max_value": max_value,
                        "failing_rows": above.len(),
                    }
                )

    if range_rules:
        if range_failures:
            msg = f"Numeric range bounds failed: {range_failures}."
            evaluations.append(
                SubEvaluation(
                    rule_name="numeric_range_bounds",
                    passed=False,
                    message=msg,
                    details={"failures": range_failures},
                )
            )
            overall = escalate(overall, GateOutcome.QUARANTINE_FILE)
            reasons.append("Numeric range bounds violated.")
        else:
            evaluations.append(
                SubEvaluation(
                    rule_name="numeric_range_bounds",
                    passed=True,
                    message="Numeric range bounds satisfied.",
                    details={"rules": range_rules},
                )
            )
    else:
        evaluations.append(
            SubEvaluation(
                rule_name="numeric_range_bounds",
                passed=True,
                message="No numeric range rules configured.",
                details={"skipped": True},
            )
        )

    return Gate3Report(
        overall_outcome=overall,
        outcome_reason="; ".join(reasons)
        if reasons
        else "All Gate 3 quality checks passed.",
        evaluations=evaluations,
    )
