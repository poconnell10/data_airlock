"""
Gate 4 — Revenue Reconciliation (header/line balance, sales/tender balance).
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Optional

import polars as pl
from pydantic import BaseModel, Field

from app.models.common import GateOutcome, SubEvaluation, escalate

_CENTS = Decimal("0.01")


class Gate4Report(BaseModel):
    overall_outcome: GateOutcome
    outcome_reason: str = ""
    evaluations: list[SubEvaluation] = Field(default_factory=list)
    header_total: Optional[float] = None
    line_sum: Optional[float] = None
    net_sales: Optional[float] = None
    tender_payments: Optional[float] = None
    max_variance: float = 0.02


def _to_decimal(value: Any) -> Optional[Decimal]:
    if value is None:
        return None
    try:
        return Decimal(str(value)).quantize(_CENTS, rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError, TypeError):
        return None


def _first_matching_col(df: pl.DataFrame, names: list[str]) -> Optional[str]:
    for name in names:
        if name in df.columns:
            return name
    return None


def _col_sum(df: pl.DataFrame, names: list[str]) -> Optional[float]:
    """Sum the first matching alias column using Decimal cents (no float drift)."""
    col = _first_matching_col(df, names)
    if col is None:
        return None
    total = Decimal("0.00")
    for val in df.get_column(col).to_list():
        dec = _to_decimal(val)
        if dec is not None:
            total += dec
    return float(total)


def _sum_columns(df: pl.DataFrame, names: list[str]) -> Optional[float]:
    """Sum all listed columns that exist (used for line + tax composition)."""
    present = [n for n in names if n in df.columns]
    if not present:
        return None
    total = Decimal("0.00")
    for name in present:
        for val in df.get_column(name).to_list():
            dec = _to_decimal(val)
            if dec is not None:
                total += dec
    return float(total)


def _first_numeric(df: pl.DataFrame, names: list[str]) -> Optional[float]:
    for name in names:
        if name not in df.columns:
            continue
        for val in df.get_column(name).to_list():
            dec = _to_decimal(val)
            if dec is not None:
                return float(dec)
    return None


def _within_variance(left: float, right: float, max_variance: float) -> tuple[float, bool]:
    left_d = _to_decimal(left) or Decimal("0.00")
    right_d = _to_decimal(right) or Decimal("0.00")
    variance = float(abs(left_d - right_d))
    return variance, variance <= float(max_variance) + 1e-12

def evaluate_gate_4(
    df_sample: pl.DataFrame,
    revenue_rules: dict,
) -> Gate4Report:
    """
    Macro-balancing checks with configurable rounding variance tolerance.
    """
    rules = revenue_rules if isinstance(revenue_rules, dict) else {}
    max_variance = float(rules.get("max_variance", rules.get("max_allowed_variance", 0.02)))
    check_header_line = bool(
        rules.get("header_vs_line_balance", rules.get("enable_header_line_balance", True))
    )
    check_sales_tender = bool(
        rules.get(
            "sales_vs_tender_balance",
            rules.get("enable_sales_tender_balance", True),
        )
    )

    evaluations: list[SubEvaluation] = []
    overall = GateOutcome.PASS
    reasons: list[str] = []

    header_total: Optional[float] = None
    line_sum: Optional[float] = None
    net_sales: Optional[float] = None
    tender_payments: Optional[float] = None

    if df_sample is None or (df_sample.height == 0 and df_sample.width == 0):
        return Gate4Report(
            overall_outcome=GateOutcome.REJECT_FILE,
            outcome_reason="Revenue check failed: empty dataframe sample.",
            evaluations=[
                SubEvaluation(
                    rule_name="dataframe_present",
                    passed=False,
                    message="No dataframe sample available for Gate 4.",
                )
            ],
            max_variance=max_variance,
        )

    # Column name aliases (Onesait / generic POS)
    header_cols = list(
        rules.get("header_total_columns")
        or ["header_total", "check_total", "total_amount", "grand_total"]
    )
    line_cols = list(
        rules.get("line_amount_columns") or ["line_item_amount", "amount", "line_total"]
    )
    tax_cols = list(rules.get("tax_columns") or ["tax", "taxes", "tax_amount"])
    sales_cols = list(
        rules.get("net_sales_columns") or ["net_sales", "sales_amount", "amount"]
    )
    tender_cols = list(
        rules.get("tender_columns")
        or ["tender_payment", "tender_payments", "payment_amount", "tender_amount"]
    )

    # ---- Header vs Line ----
    if check_header_line:
        header_total = _first_numeric(df_sample, header_cols)
        line_part = _sum_columns(df_sample, line_cols)
        tax_part = _sum_columns(df_sample, tax_cols) or 0.0
        if line_part is not None:
            line_sum = line_part + tax_part

        if header_total is None or line_sum is None:
            evaluations.append(
                SubEvaluation(
                    rule_name="header_vs_line_balance",
                    passed=True,
                    message=(
                        "Header-vs-line balance skipped — required columns not present "
                        "in sample."
                    ),
                    details={
                        "skipped": True,
                        "header_columns": header_cols,
                        "line_columns": line_cols,
                        "tax_columns": tax_cols,
                    },
                )
            )
        else:
            variance, ok = _within_variance(header_total, line_sum, max_variance)
            details = {
                "header_total": header_total,
                "line_sum": line_sum,
                "variance": round(variance, 4),
                "max_variance": max_variance,
            }
            if not ok:
                msg = (
                    f"Financial imbalance detected: Header total ${header_total:.2f} "
                    f"vs Line sum ${line_sum:.2f}. Variance: {variance:.2f}."
                )
                evaluations.append(
                    SubEvaluation(
                        rule_name="header_vs_line_balance",
                        passed=False,
                        message=msg,
                        details=details,
                    )
                )
                overall = escalate(overall, GateOutcome.REJECT_FILE)
                reasons.append(msg)
            else:
                evaluations.append(
                    SubEvaluation(
                        rule_name="header_vs_line_balance",
                        passed=True,
                        message=(
                            f"Header-vs-line balanced within ${max_variance:.2f} "
                            f"(Δ=${variance:.4f})."
                        ),
                        details=details,
                    )
                )
    else:
        evaluations.append(
            SubEvaluation(
                rule_name="header_vs_line_balance",
                passed=True,
                message="Header-vs-line balance disabled.",
                details={"skipped": True},
            )
        )

    # ---- Sales vs Tender ----
    if check_sales_tender:
        net_sales = _col_sum(df_sample, sales_cols)
        tender_payments = _col_sum(df_sample, tender_cols)
        if net_sales is None or tender_payments is None:
            evaluations.append(
                SubEvaluation(
                    rule_name="sales_vs_tender_balance",
                    passed=True,
                    message=(
                        "Sales-vs-tender balance skipped — required columns not present "
                        "in sample."
                    ),
                    details={
                        "skipped": True,
                        "sales_columns": sales_cols,
                        "tender_columns": tender_cols,
                    },
                )
            )
        else:
            variance, ok = _within_variance(net_sales, tender_payments, max_variance)
            details = {
                "net_sales": net_sales,
                "tender_payments": tender_payments,
                "variance": round(variance, 4),
                "max_variance": max_variance,
            }
            if not ok:
                msg = (
                    f"Financial imbalance detected: Net sales ${net_sales:.2f} "
                    f"vs Tender payments ${tender_payments:.2f}. "
                    f"Variance: {variance:.2f}."
                )
                evaluations.append(
                    SubEvaluation(
                        rule_name="sales_vs_tender_balance",
                        passed=False,
                        message=msg,
                        details=details,
                    )
                )
                overall = escalate(overall, GateOutcome.REJECT_FILE)
                reasons.append(msg)
            else:
                evaluations.append(
                    SubEvaluation(
                        rule_name="sales_vs_tender_balance",
                        passed=True,
                        message=(
                            f"Sales-vs-tender balanced within ${max_variance:.2f} "
                            f"(Δ=${variance:.4f})."
                        ),
                        details=details,
                    )
                )
    else:
        evaluations.append(
            SubEvaluation(
                rule_name="sales_vs_tender_balance",
                passed=True,
                message="Sales-vs-tender balance disabled.",
                details={"skipped": True},
            )
        )

    return Gate4Report(
        overall_outcome=overall,
        outcome_reason="; ".join(reasons)
        if reasons
        else "All Gate 4 revenue checks passed.",
        evaluations=evaluations,
        header_total=header_total,
        line_sum=line_sum,
        net_sales=net_sales,
        tender_payments=tender_payments,
        max_variance=max_variance,
    )
