#!/usr/bin/env python3
"""
E2E Live Storage Pipeline Simulator.

Generates OneSait POS CSV payloads, optionally lands them on disk / S3,
then triggers POST /api/v1/airlock/ingest (fallback: dry-run).

Usage (from repo root):
  python -m services.engine.scripts.simulate_s3_drops --scenario clean_atomic_set
  python -m services.engine.scripts.simulate_s3_drops --scenario incomplete_atomic_hold
"""

from __future__ import annotations

import argparse
import base64
import json
import secrets
import sys
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

# ---------------------------------------------------------------------------
# ANSI
# ---------------------------------------------------------------------------

_RESET = "\033[0m"
_BOLD = "\033[1m"
_DIM = "\033[2m"
_CYAN = "\033[36m"
_GREEN = "\033[32m"
_YELLOW = "\033[33m"
_RED = "\033[31m"
_MAGENTA = "\033[35m"
_WHITE = "\033[37m"


def _c(color: str, text: str) -> str:
    if not sys.stdout.isatty():
        return text
    return f"{color}{text}{_RESET}"


def _outcome_color(outcome: str) -> str:
    if outcome in {"PASS", "PASS_OVERRIDDEN", "FLAG"}:
        return _GREEN
    if outcome == "HOLD_SET":
        return _YELLOW
    if outcome in {"QUARANTINE_FILE", "REJECT_FILE"}:
        return _RED
    if outcome == "MISSING_DELIVERY":
        return _MAGENTA
    return _WHITE


SCENARIOS = (
    "clean_atomic_set",
    "incomplete_atomic_hold",
    "encoding_corruption",
    "revenue_imbalance",
    "trailing_footer_opera",
)

REPORT_TYPES = ("headers_data", "sales_data", "payments_data")


@dataclass
class DropFile:
    report_type: str
    filename: str
    path: str
    payload: bytes
    encoding_label: str = "utf-8"
    notes: str = ""


@dataclass
class ScenarioPlan:
    name: str
    expected_outcomes: dict[str, str]
    files: list[DropFile]
    delayed_file: Optional[DropFile] = None
    contract_json: Optional[dict[str, Any]] = None
    description: str = ""
    batch_override: Optional[list[str]] = None
    gate4_rules: Optional[dict[str, Any]] = None


@dataclass
class DropResult:
    filename: str
    status_code: int
    overall_outcome: str
    run_id: str = ""
    outcome_reason: str = ""
    gate_summary: dict[str, str] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)
    error: str = ""


# ---------------------------------------------------------------------------
# Payload builders
# ---------------------------------------------------------------------------


def _today_iso() -> str:
    """Business date aligned to the current calendar day (SLA-safe)."""
    return date.today().isoformat()


def _hash8() -> str:
    """8-char hex token matching (?P<hash>[a-f0-9]+)."""
    return secrets.token_hex(4)


def _filename(report_type: str, property_id: str, biz_date: str, file_hash: str) -> str:
    # Live Onesait contract:
    # ^(payments_data|sales_data|headers_data)_(property)_(YYYY-MM-DD)__(hash).csv$
    return f"{report_type}_{property_id}_{biz_date}__{file_hash}.csv"


def _landing_path(property_id: str, biz_date: str, filename: str) -> str:
    return f"landing/onesait/{property_id}/{biz_date}/{filename}"


def _headers_csv(*, guests: list[str] | None = None) -> str:
    guests = guests or ["Ada Lovelace", "Grace Hopper", "Alan Turing"]
    lines = ["check_id,guest_name,check_total,opened_at"]
    totals = ["33.33", "33.33", "33.34"]
    for idx, (guest, total) in enumerate(zip(guests, totals), start=1):
        lines.append(f"CHK{idx:03d},{guest},{total},2026-08-11T20:00:0{idx}Z")
    return "\n".join(lines) + "\n"


def _sales_csv(*, amounts: list[str] | None = None) -> str:
    amounts = amounts or ["40.00", "35.00", "25.00"]  # sum = 100.00
    lines = ["check_id,line_no,item,amount,net_sales"]
    for idx, amount in enumerate(amounts, start=1):
        lines.append(f"CHK{idx:03d},1,ITEM_{idx},{amount},{amount}")
    return "\n".join(lines) + "\n"


def _payments_csv(
    *,
    tenders: list[str] | None = None,
    net_sales_total: Optional[str] = None,
) -> str:
    """
    Split-tender precision: 33.33 + 33.33 + 33.34 = 100.00.

    When net_sales_total is set, embed a Gate-4 sales-vs-tender pair so
    imbalance scenarios reject inside a single file evaluation.
    """
    tenders = tenders or ["33.33", "33.33", "33.34"]
    # Put full net sales on first row; remaining rows contribute 0 to the sum.
    sales_each = (
        [net_sales_total] + ["0"] * (len(tenders) - 1)
        if net_sales_total is not None
        else [""] * len(tenders)
    )
    lines = ["check_id,tender_type,tender_payment,net_sales"]
    for idx, tender in enumerate(tenders, start=1):
        lines.append(f"CHK{idx:03d},CARD,{tender},{sales_each[idx - 1]}")
    return "\n".join(lines) + "\n"


def _opera_footer_csv() -> str:
    body = (
        "check_id,amount,guest\n"
        "1,500.00,Ada\n"
        "2,542.20,Grace\n"
        "3,500.00,Alan\n"
        "TOTAL: 1542.20\n"
        "*** END OF REPORT ***\n"
        "TRL|COUNT|3\n"
    )
    return body


def _make_drop(
    *,
    report_type: str,
    property_id: str,
    biz_date: str,
    payload: bytes,
    encoding_label: str = "utf-8",
    notes: str = "",
    file_hash: Optional[str] = None,
) -> DropFile:
    h = file_hash or _hash8()
    name = _filename(report_type, property_id, biz_date, h)
    return DropFile(
        report_type=report_type,
        filename=name,
        path=_landing_path(property_id, biz_date, name),
        payload=payload,
        encoding_label=encoding_label,
        notes=notes,
    )


def _footer_contract_overlay() -> dict[str, Any]:
    """Gate-1 footer isolation rules for Opera-style trailers."""
    return {
        "row_classification": {
            "header_patterns": [r"^check_id,"],
            "footer_patterns": [
                r"^\*\*\* END OF REPORT \*\*\*",
                r"^TOTAL:",
                r"^TRL\|COUNT\|",
            ],
            "ignore_patterns": [r"^\s*$"],
            "row_count_declaration": {
                "pattern": r"^TRL\|COUNT\|(?P<declared_row_count>\d+)",
            },
        },
        "gate_4": {
            "header_vs_line_balance": False,
            "sales_vs_tender_balance": False,
        },
    }


def build_scenario(
    name: str,
    *,
    property_id: str,
    delayed_complete: bool = False,
) -> ScenarioPlan:
    biz = _today_iso()

    if name == "clean_atomic_set":
        files = [
            _make_drop(
                report_type="headers_data",
                property_id=property_id,
                biz_date=biz,
                payload=_headers_csv().encode("utf-8"),
            ),
            _make_drop(
                report_type="sales_data",
                property_id=property_id,
                biz_date=biz,
                payload=_sales_csv().encode("utf-8"),
            ),
            _make_drop(
                report_type="payments_data",
                property_id=property_id,
                biz_date=biz,
                payload=_payments_csv(net_sales_total="100.00").encode("utf-8"),
                notes="split tender 33.33+33.33+33.34 == 100.00",
            ),
        ]
        return ScenarioPlan(
            name=name,
            description="Full atomic set, balanced revenue, UTF-8",
            expected_outcomes={
                "headers_data": "PASS",
                "sales_data": "PASS",
                "payments_data": "PASS",
            },
            files=files,
            gate4_rules={
                "max_variance": 0.01,
                "header_vs_line_balance": False,
                "sales_vs_tender_balance": True,
                "net_sales_columns": ["net_sales"],
                "tender_columns": ["tender_payment"],
            },
        )

    if name == "incomplete_atomic_hold":
        headers = _make_drop(
            report_type="headers_data",
            property_id=property_id,
            biz_date=biz,
            payload=_headers_csv().encode("utf-8"),
        )
        sales = _make_drop(
            report_type="sales_data",
            property_id=property_id,
            biz_date=biz,
            payload=_sales_csv().encode("utf-8"),
        )
        payments = _make_drop(
            report_type="payments_data",
            property_id=property_id,
            biz_date=biz,
            payload=_payments_csv(net_sales_total="100.00").encode("utf-8"),
            notes="delayed completion file",
        )
        return ScenarioPlan(
            name=name,
            description="Omit payments_data → HOLD_SET; optional delayed complete",
            expected_outcomes={
                "headers_data": "HOLD_SET",
                "sales_data": "HOLD_SET",
            },
            files=[headers, sales],
            delayed_file=payments if delayed_complete else None,
        )

    if name == "encoding_corruption":
        # ISO-8859-1 ü (0xFC) / é (0xE9) — invalid UTF-8
        text = (
            "check_id,guest_name,check_total\n"
            "CHK001,M\xfcller,50.00\n"
            "CHK002,Caf\xe9,50.00\n"
        )
        payload = text.encode("latin-1")
        drop = _make_drop(
            report_type="headers_data",
            property_id=property_id,
            biz_date=biz,
            payload=payload,
            encoding_label="iso-8859-1",
            notes="latin-1 Müller/Café under utf-8 contract",
        )
        return ScenarioPlan(
            name=name,
            description="Non-UTF8 accented bytes → reject/quarantine with offending_byte",
            # Gate 1 physical integrity fail-closes as REJECT_FILE
            expected_outcomes={"headers_data": "REJECT_FILE"},
            files=[drop],
            batch_override=[drop.filename],  # avoid HOLD masking REJECT
        )

    if name == "revenue_imbalance":
        sales = _make_drop(
            report_type="sales_data",
            property_id=property_id,
            biz_date=biz,
            payload=_sales_csv(amounts=["50.00", "50.00", "50.00"]).encode("utf-8"),
            notes="net sales $150.00",
        )
        payments = _make_drop(
            report_type="payments_data",
            property_id=property_id,
            biz_date=biz,
            payload=_payments_csv(
                tenders=["50.00", "50.00", "42.50"],
                net_sales_total="150.00",
            ).encode("utf-8"),
            notes="tenders $142.50 vs net_sales $150.00 (Δ=$7.50)",
        )
        headers = _make_drop(
            report_type="headers_data",
            property_id=property_id,
            biz_date=biz,
            payload=_headers_csv().encode("utf-8"),
        )
        return ScenarioPlan(
            name=name,
            description="Gate 4 sales/tender imbalance → REJECT_FILE",
            expected_outcomes={
                "headers_data": "PASS",
                "sales_data": "PASS",
                "payments_data": "REJECT_FILE",
            },
            files=[headers, sales, payments],
            gate4_rules={
                "max_variance": 0.01,
                "header_vs_line_balance": False,
                "sales_vs_tender_balance": True,
                "net_sales_columns": ["net_sales"],
                "tender_columns": ["tender_payment"],
            },
        )

    if name == "trailing_footer_opera":
        # Opera-style report type still uses Onesait filename pattern for live contract
        drop = _make_drop(
            report_type="headers_data",
            property_id=property_id,
            biz_date=biz,
            payload=_opera_footer_csv().encode("utf-8"),
            notes="TOTAL + END OF REPORT + TRL|COUNT|3 footers",
        )
        return ScenarioPlan(
            name=name,
            description="Opera trailers excluded from data row conservation",
            expected_outcomes={"headers_data": "PASS"},
            files=[drop],
            batch_override=[
                drop.filename,
                _filename("sales_data", property_id, biz, _hash8()),
                _filename("payments_data", property_id, biz, _hash8()),
            ],
            contract_json=_footer_contract_overlay(),
            gate4_rules={
                "header_vs_line_balance": False,
                "sales_vs_tender_balance": False,
            },
        )

    raise ValueError(f"Unknown scenario: {name}")


# ---------------------------------------------------------------------------
# Transport
# ---------------------------------------------------------------------------


def _http_json(
    method: str,
    url: str,
    payload: Optional[dict[str, Any]] = None,
    timeout: float = 60.0,
) -> tuple[int, dict[str, Any]]:
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = Request(url, data=data, headers=headers, method=method)
    try:
        with urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8")
            parsed = json.loads(body) if body else {}
            return int(resp.status), parsed if isinstance(parsed, dict) else {"data": parsed}
    except HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            parsed = {"detail": raw}
        return int(exc.code), parsed if isinstance(parsed, dict) else {"detail": raw}
    except URLError as exc:
        return 0, {"detail": f"connection error: {exc.reason}"}


def _merge_contract(
    base: Optional[dict[str, Any]],
    overlay: Optional[dict[str, Any]],
    gate4: Optional[dict[str, Any]],
) -> Optional[dict[str, Any]]:
    if not base and not overlay and not gate4:
        return None
    out: dict[str, Any] = {}
    if isinstance(base, dict):
        out.update(base)
    if isinstance(overlay, dict):
        for key, value in overlay.items():
            if isinstance(value, dict) and isinstance(out.get(key), dict):
                merged = dict(out[key])
                merged.update(value)
                out[key] = merged
            else:
                out[key] = value
    if gate4:
        out["gate_4"] = {**(out.get("gate_4") or {}), **gate4}
    return out


def fetch_live_contract(engine_url: str, property_id: str) -> Optional[dict[str, Any]]:
    code, body = _http_json("GET", f"{engine_url.rstrip('/')}/api/v1/properties/{property_id}")
    if code != 200:
        return None
    contract = (body.get("contract") or {}).get("contract_yaml")
    return contract if isinstance(contract, dict) else None


def land_locally(drop: DropFile, landing_root: Path) -> Path:
    dest = landing_root / drop.path
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(drop.payload)
    return dest


def maybe_upload_s3(drop: DropFile, bucket: str, endpoint_url: Optional[str]) -> Optional[str]:
    try:
        import boto3  # type: ignore
    except ImportError:
        print(_c(_YELLOW, "  ! boto3 not installed — skipping S3 upload"))
        return None
    kwargs: dict[str, Any] = {}
    if endpoint_url:
        kwargs["endpoint_url"] = endpoint_url
    client = boto3.client("s3", **kwargs)
    key = drop.path
    client.put_object(Bucket=bucket, Key=key, Body=drop.payload)
    return f"s3://{bucket}/{key}"


def ingest_drop(
    *,
    engine_url: str,
    property_id: str,
    drop: DropFile,
    batch: list[str],
    contract_json: Optional[dict[str, Any]],
    use_ingest: bool = True,
) -> DropResult:
    endpoint = "/api/v1/airlock/ingest" if use_ingest else "/api/v1/airlock/dry-run"
    url = f"{engine_url.rstrip('/')}{endpoint}"
    payload = {
        "property_id": property_id,
        "filename": drop.filename,
        "path": drop.path,
        "payload_b64": base64.b64encode(drop.payload).decode("ascii"),
        "present_batch_filenames": batch,
    }
    if contract_json:
        payload["contract_json"] = contract_json

    status, body = _http_json("POST", url, payload)
    if status == 404 and use_ingest:
        # Older engine without ingest — fall back
        return ingest_drop(
            engine_url=engine_url,
            property_id=property_id,
            drop=drop,
            batch=batch,
            contract_json=contract_json,
            use_ingest=False,
        )

    if status == 0 or status >= 400:
        return DropResult(
            filename=drop.filename,
            status_code=status,
            overall_outcome="ERROR",
            error=str(body.get("detail") or body),
            raw=body,
        )

    gates = {
        "G1": str((body.get("gate1_report") or {}).get("overall_outcome") or ""),
        "G2": str((body.get("gate2_report") or {}).get("overall_outcome") or ""),
        "G3": str((body.get("gate3_report") or {}).get("overall_outcome") or ""),
        "G4": str((body.get("gate4_report") or {}).get("overall_outcome") or ""),
    }
    return DropResult(
        filename=drop.filename,
        status_code=status,
        overall_outcome=str(body.get("overall_outcome") or ""),
        run_id=str(body.get("run_id") or ""),
        outcome_reason=str(body.get("outcome_reason") or ""),
        gate_summary=gates,
        raw=body,
    )


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


def _print_banner(plan: ScenarioPlan, property_id: str, biz: str) -> None:
    print()
    print(_c(_BOLD, "═" * 72))
    print(_c(_BOLD + _CYAN, f"  Airlock S3 Drop Simulator · {plan.name}"))
    print(_c(_DIM, f"  {plan.description}"))
    print(_c(_DIM, f"  property={property_id}  business_date={biz}  ts={datetime.now(timezone.utc).isoformat()}"))
    print(_c(_BOLD, "═" * 72))


def _print_drop(drop: DropFile) -> None:
    print(
        f"\n{_c(_CYAN, '→ DROP')} {_c(_BOLD, drop.filename)} "
        f"{_c(_DIM, f'({drop.encoding_label}, {len(drop.payload)} bytes)')}"
    )
    print(_c(_DIM, f"  path: {drop.path}"))
    if drop.notes:
        print(_c(_DIM, f"  note: {drop.notes}"))


def _print_result(result: DropResult, expected: Optional[str]) -> bool:
    color = _outcome_color(result.overall_outcome)
    ok = True
    if result.error:
        print(_c(_RED, f"  ✗ HTTP {result.status_code}: {result.error}"))
        return False
    print(
        f"  {_c(color, f'● {result.overall_outcome}')}  "
        f"http={result.status_code}  run_id={result.run_id}"
    )
    gates = " ".join(f"{k}={v}" for k, v in result.gate_summary.items() if v)
    if gates:
        print(_c(_DIM, f"  gates: {gates}"))
    if result.outcome_reason:
        print(_c(_DIM, f"  reason: {result.outcome_reason[:160]}"))

    # Surface encoding landmine details
    g1 = (result.raw.get("gate1_report") or {})
    for ev in g1.get("evaluations") or []:
        details = ev.get("details") or {}
        if details.get("offending_byte") is not None:
            print(
                _c(
                    _YELLOW,
                    f"  landmine: offending_byte=0x{details.get('offending_byte')} "
                    f"at byte {details.get('error_start')}",
                )
            )

    if expected:
        match = result.overall_outcome == expected
        # Soft-accept: encoding may surface as REJECT or QUARANTINE depending on gate mapping
        if not match and {result.overall_outcome, expected} <= {
            "REJECT_FILE",
            "QUARANTINE_FILE",
        }:
            match = True
            print(_c(_YELLOW, f"  ~ expected {expected}, accepted {result.overall_outcome}"))
        elif match:
            print(_c(_GREEN, f"  ✓ matches expected {expected}"))
        else:
            ok = False
            print(_c(_RED, f"  ✗ expected {expected}, got {result.overall_outcome}"))
    return ok


def run_scenario(args: argparse.Namespace) -> int:
    engine_url = args.engine_url.rstrip("/")
    property_id = args.property_id
    biz = _today_iso()

    # Health ping
    code, health = _http_json("GET", f"{engine_url}/health")
    if code != 200:
        print(_c(_RED, f"Engine unreachable at {engine_url}/health (status={code})"))
        print(_c(_DIM, str(health)))
        return 2
    print(
        _c(
            _GREEN,
            f"Engine online v{health.get('version')}  supabase={health.get('supabase_configured')}",
        )
    )

    plan = build_scenario(
        args.scenario,
        property_id=property_id,
        delayed_complete=bool(args.delayed_complete),
    )
    _print_banner(plan, property_id, biz)

    live_contract = fetch_live_contract(engine_url, property_id)
    contract_json = _merge_contract(live_contract, plan.contract_json, plan.gate4_rules)

    landing_root = Path(args.landing_dir).expanduser().resolve() if args.landing_dir else None
    if landing_root:
        print(_c(_DIM, f"Local landing root: {landing_root}"))

    batch = plan.batch_override or [f.filename for f in plan.files]
    if plan.delayed_file and plan.delayed_file.filename not in batch:
        # incomplete hold: batch is only current files
        pass

    results: list[DropResult] = []
    all_ok = True

    for idx, drop in enumerate(plan.files):
        if idx > 0 and args.delay_seconds > 0:
            time.sleep(float(args.delay_seconds))

        _print_drop(drop)
        if landing_root:
            dest = land_locally(drop, landing_root)
            print(_c(_DIM, f"  wrote: {dest}"))
        if args.s3_bucket:
            uri = maybe_upload_s3(drop, args.s3_bucket, args.s3_endpoint)
            if uri:
                print(_c(_DIM, f"  uploaded: {uri}"))
                drop.path = uri

        # For incomplete hold, batch = files dropped so far (or all planned non-delayed)
        if plan.name == "incomplete_atomic_hold":
            batch = [f.filename for f in plan.files[: idx + 1]]
        elif plan.batch_override:
            batch = plan.batch_override
        else:
            batch = [f.filename for f in plan.files]

        result = ingest_drop(
            engine_url=engine_url,
            property_id=property_id,
            drop=drop,
            batch=batch,
            contract_json=contract_json,
            use_ingest=not args.dry_run_only,
        )
        results.append(result)
        expected = plan.expected_outcomes.get(drop.report_type)
        if not _print_result(result, expected):
            all_ok = False

    if plan.delayed_file:
        print(_c(_YELLOW, "\n⏳ --delayed-complete: waiting 5s before dropping payments_data…"))
        time.sleep(5.0)
        drop = plan.delayed_file
        _print_drop(drop)
        if landing_root:
            land_locally(drop, landing_root)
        if args.s3_bucket:
            uri = maybe_upload_s3(drop, args.s3_bucket, args.s3_endpoint)
            if uri:
                drop.path = uri
        batch = [f.filename for f in plan.files] + [drop.filename]
        result = ingest_drop(
            engine_url=engine_url,
            property_id=property_id,
            drop=drop,
            batch=batch,
            contract_json=contract_json,
            use_ingest=not args.dry_run_only,
        )
        results.append(result)
        # After completion, expect PASS (hold released for this file)
        if not _print_result(result, "PASS"):
            all_ok = False

    print()
    print(_c(_BOLD, "─" * 72))
    print(_c(_BOLD, "  Summary"))
    for r in results:
        mark = "✓" if r.overall_outcome not in {"ERROR", ""} else "✗"
        print(
            f"  {mark} {r.filename}: "
            f"{_c(_outcome_color(r.overall_outcome), r.overall_outcome)} "
            f"(HTTP {r.status_code})"
        )
    print(_c(_BOLD, "─" * 72))
    if all_ok:
        print(_c(_GREEN, "All scenario expectations met."))
        return 0
    print(_c(_RED, "One or more expectations failed."))
    return 1


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="simulate_s3_drops",
        description="E2E Live Storage Pipeline Simulator for the Data Airlock engine",
    )
    p.add_argument(
        "--scenario",
        choices=SCENARIOS,
        default="clean_atomic_set",
        help="Simulation mode (default: clean_atomic_set)",
    )
    p.add_argument("--property-id", default="ESMA.MALAG")
    p.add_argument("--engine-url", default="http://localhost:8000")
    p.add_argument(
        "--delay-seconds",
        type=float,
        default=1.0,
        help="Delay between multi-file drops (default: 1.0)",
    )
    p.add_argument(
        "--delayed-complete",
        action="store_true",
        help="For incomplete_atomic_hold: drop payments_data after 5s",
    )
    p.add_argument(
        "--landing-dir",
        default="",
        help="Optional local root to write landing/onesait/... files",
    )
    p.add_argument("--s3-bucket", default="", help="Optional S3/MinIO bucket for upload")
    p.add_argument(
        "--s3-endpoint",
        default="",
        help="Optional S3-compatible endpoint URL (MinIO)",
    )
    p.add_argument(
        "--dry-run-only",
        action="store_true",
        help="Call /airlock/dry-run instead of /airlock/ingest (no run_reports persist)",
    )
    return p


def main(argv: Optional[list[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.landing_dir:
        args.landing_dir = ""
    if not args.s3_bucket:
        args.s3_bucket = ""
    if not args.s3_endpoint:
        args.s3_endpoint = ""
    try:
        return run_scenario(args)
    except KeyboardInterrupt:
        print(_c(_YELLOW, "\nInterrupted."))
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
