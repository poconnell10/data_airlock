"""
Data Airlock Suite — FastAPI control-plane engine.

Endpoints:
  GET  /health
  GET  /api/v1/properties/{property_id}
  POST /api/v1/inference/inspect
  POST /api/v1/airlock/dry-run
  POST /api/v1/airlock/ingest
  POST /api/v1/workers/check-slas
  GET  /api/v1/adjudication/queue
  GET  /api/v1/adjudication/metrics
  POST /api/v1/adjudication/override
  POST /api/v1/airlock/contracts
  GET  /api/v1/airlock/contracts/{property_id}/{feed_id}
  GET  /api/v1/properties/{property_id}/journal
  POST /api/v1/properties/{property_id}/journal
  POST /api/v1/airlock/runs/{run_id}/audit-notes
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import logging
import os
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse

import httpx
import polars as pl
import yaml
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from app.db import (  # noqa: E402
    classify_run_report,
    fetch_property_contract,
    fetch_run_report_by_id,
    fetch_run_reports_history,
    insert_run_report,
    is_supabase_configured,
    release_run_report,
)
from app.gates.gate_1_extraction import evaluate_gate_1  # noqa: E402
from app.gates.gate_2_anomaly import Gate2Report, evaluate_gate_2  # noqa: E402
from app.gates.gate_3_quality import Gate3Report, evaluate_gate_3  # noqa: E402
from app.gates.gate_4_revenue import Gate4Report, evaluate_gate_4  # noqa: E402
from app.inference.schema_infer import (  # noqa: E402
    SchemaInferenceResult,
    infer_schema_from_bytes,
)
from app.models.common import GateOutcome, escalate  # noqa: E402
from app.models.gate1 import Gate1Outcome, Gate1Report  # noqa: E402
from app.models.report import (  # noqa: E402
    ClassifyRequest,
    ClassifyResponse,
    QuarantineManifestItem,
    ReadinessStats,
)
from app.routes.evaluation import build_execution_enrichment  # noqa: E402
from app.routers.adjudication import router as adjudication_router  # noqa: E402
from app.routers.contracts import router as contracts_router  # noqa: E402
from app.routers.journal import router as journal_router  # noqa: E402
from app.utils.quarantine_mapper import apply_user_classifications  # noqa: E402
from app.workers.sla_ledger import check_property_sla_deliveries  # noqa: E402

APP_VERSION = "0.6.0"
logger = logging.getLogger("airlock.engine")

_scheduler = AsyncIOScheduler(timezone="UTC")


async def _scheduled_sla_check() -> None:
    try:
        result = await check_property_sla_deliveries(dispatch_alerts=True)
        logger.info(
            "Scheduled SLA check complete checked=%s missing=%s",
            result.get("checked"),
            result.get("missing_delivery_count"),
        )
    except Exception:  # noqa: BLE001
        logger.exception("Scheduled SLA check failed")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Start APScheduler SLA loop (every 15 minutes)."""
    enabled = os.getenv("SLA_SCHEDULER_ENABLED", "true").lower() in {
        "1",
        "true",
        "yes",
    }
    if enabled:
        _scheduler.add_job(
            _scheduled_sla_check,
            trigger="interval",
            minutes=int(os.getenv("SLA_CHECK_INTERVAL_MINUTES", "15") or "15"),
            id="sla_ledger_check",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
        _scheduler.start()
        logger.info("SLA ledger scheduler started (interval=15m)")
    try:
        yield
    finally:
        if _scheduler.running:
            _scheduler.shutdown(wait=False)
            logger.info("SLA ledger scheduler stopped")


app = FastAPI(
    title="Data Airlock Engine",
    description="Pre-transformation data ingestion control plane",
    version=APP_VERSION,
    lifespan=lifespan,
)

_cors_origins = [
    o.strip()
    for o in os.getenv(
        "CORS_ORIGINS",
        "http://localhost:3000,http://127.0.0.1:3000",
    ).split(",")
    if o.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(adjudication_router)
app.include_router(contracts_router)
app.include_router(journal_router)


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class DryRunRequest(BaseModel):
    property_id: str = Field(..., min_length=1)
    filename: str = Field(..., min_length=1)
    path: Optional[str] = None
    s3_uri: Optional[str] = None
    payload_text: Optional[str] = None
    payload_b64: Optional[str] = None
    fetch_uri: bool = False
    present_batch_filenames: list[str] = Field(default_factory=list)
    # Optional inline contract override (otherwise hydrated from Supabase)
    contract_yaml: Optional[str] = None
    contract_json: Optional[dict[str, Any]] = None
    feed_category: Optional[str] = None


class EvaluateRequest(DryRunRequest):
    """Dry-run + optional persistence into adjudication queue (run_reports)."""

    persist_run: bool = False


class DryRunResponse(BaseModel):
    run_id: str
    timestamp: str
    property_id: str
    filename: str
    path: Optional[str]
    overall_outcome: GateOutcome
    outcome_reason: str
    gate1_report: Gate1Report
    gate2_report: Gate2Report
    gate3_report: Gate3Report
    gate4_report: Gate4Report
    contract_profile_id: Optional[str] = None
    contract_version: Optional[Any] = None


class IngestResponse(DryRunResponse):
    """Dry-run result persisted as an append-only run_reports row."""

    persisted: bool = False
    report_type: Optional[str] = None
    business_date: Optional[str] = None
    feed_category: Optional[str] = None


class EvaluateResponse(IngestResponse):
    """Evaluate endpoint response (optionally persisted)."""

    findings: list[dict[str, Any]] = Field(default_factory=list)
    readiness_stats: ReadinessStats = Field(default_factory=ReadinessStats)
    quarantine_manifest: list[QuarantineManifestItem] = Field(default_factory=list)


class ReleaseRequest(BaseModel):
    operator_id: str = Field(..., min_length=1)
    reason: str = Field(default="Verified for ETL release", min_length=3)


class ReleaseResponse(BaseModel):
    success: bool
    run_id: str
    status: str = "RELEASED_TO_ETL"
    released_by: Optional[str] = None
    released_at: Optional[str] = None
    event: str = "airlock.run.released"
    message: str = ""


class InspectRequest(BaseModel):
    s3_uri: Optional[str] = None
    filename: Optional[str] = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_run_id() -> str:
    return str(uuid.uuid4())


def _parse_contract_doc(
    yaml_text: Optional[str], json_doc: Optional[dict[str, Any]]
) -> dict[str, Any]:
    if json_doc and isinstance(json_doc, dict):
        return json_doc
    if not yaml_text or not str(yaml_text).strip():
        return {}
    try:
        data = yaml.safe_load(yaml_text)
        return data if isinstance(data, dict) else {}
    except yaml.YAMLError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid contract YAML: {exc}") from exc


def _decode_payload(req: DryRunRequest) -> bytes:
    if req.payload_b64:
        try:
            return base64.b64decode(req.payload_b64, validate=False)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=400, detail=f"Invalid payload_b64: {exc}") from exc
    if req.payload_text is not None:
        return req.payload_text.encode("utf-8")
    return b""


def _sha256(payload: bytes) -> Optional[str]:
    if not payload:
        return None
    return hashlib.sha256(payload).hexdigest()


def _payload_to_dataframe(payload: bytes, contract: dict[str, Any]) -> pl.DataFrame:
    """Best-effort Polars frame for Gates 3/4 sample evaluation."""
    if not payload:
        return pl.DataFrame()

    fmt = contract.get("file_format") if isinstance(contract.get("file_format"), dict) else {}
    physical = contract.get("physical") if isinstance(contract.get("physical"), dict) else {}
    delimiter = (
        fmt.get("delimiter")
        or physical.get("delimiter")
        or ","
    )
    encoding = str(fmt.get("encoding") or physical.get("encoding") or "utf-8")
    try:
        text = payload.decode(encoding)
    except UnicodeDecodeError:
        text = payload.decode("latin-1", errors="replace")

    try:
        return pl.read_csv(
            io.StringIO(text),
            separator=str(delimiter),
            has_header=True,
            ignore_errors=True,
            truncate_ragged_lines=True,
            infer_schema_length=200,
            n_rows=5000,
        )
    except Exception:  # noqa: BLE001
        return pl.DataFrame()


def _gate1_to_common(outcome: Gate1Outcome) -> GateOutcome:
    return GateOutcome(outcome.value)


def _combine_outcomes(*outcomes: GateOutcome) -> GateOutcome:
    overall = GateOutcome.PASS
    for o in outcomes:
        overall = escalate(overall, o)
    return overall


async def _fetch_uri_bytes(uri: str) -> bytes:
    parsed = urlparse(uri)
    if parsed.scheme in {"http", "https"}:
        try:
            async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
                resp = await client.get(uri)
                resp.raise_for_status()
                return resp.content
        except httpx.HTTPError as exc:
            raise HTTPException(
                status_code=502, detail=f"Failed to fetch URI: {exc}"
            ) from exc

    if parsed.scheme == "s3":
        try:
            import boto3  # type: ignore
            from botocore.exceptions import BotoCoreError, ClientError  # type: ignore
        except ImportError as exc:
            raise HTTPException(
                status_code=501,
                detail=(
                    "s3:// fetch requires boto3. Provide payload_text / payload_b64 "
                    "instead, or install boto3 with AWS/R2 credentials."
                ),
            ) from exc

        bucket = parsed.netloc
        key = parsed.path.lstrip("/")
        try:
            client_kwargs: dict[str, Any] = {}
            endpoint = os.getenv("S3_ENDPOINT_URL") or os.getenv("AWS_ENDPOINT_URL")
            if endpoint:
                client_kwargs["endpoint_url"] = endpoint
            s3 = boto3.client("s3", **client_kwargs)
            obj = s3.get_object(Bucket=bucket, Key=key)
            return obj["Body"].read()
        except (BotoCoreError, ClientError, OSError) as exc:
            raise HTTPException(
                status_code=502, detail=f"S3 fetch failed for {uri}: {exc}"
            ) from exc

    raise HTTPException(
        status_code=400,
        detail=f"Unsupported URI scheme '{parsed.scheme}'. Use https:// or s3://.",
    )


def _hydrate_contract(property_id: str, inline: dict[str, Any]) -> tuple[dict[str, Any], Optional[dict[str, Any]], Optional[dict[str, Any]]]:
    """
    Resolve contract YAML: inline override wins; else Supabase active contract.
    Returns (contract_yaml, property_row, contract_row).
    """
    if inline:
        property_row = None
        contract_row = None
        if is_supabase_configured():
            try:
                property_row, contract_row = fetch_property_contract(property_id)
            except Exception:  # noqa: BLE001
                property_row, contract_row = None, None
        return inline, property_row, contract_row

    if not is_supabase_configured():
        raise HTTPException(
            status_code=503,
            detail="No contract provided and Supabase is not configured.",
        )

    try:
        property_row, contract_row = fetch_property_contract(property_id)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=502, detail=f"Supabase query failed: {exc}"
        ) from exc

    if not property_row:
        raise HTTPException(
            status_code=404, detail=f"Property '{property_id}' not found"
        )
    if not contract_row or not contract_row.get("contract_yaml"):
        raise HTTPException(
            status_code=404,
            detail=f"Property '{property_id}' has no active ingestion contract",
        )

    contract = contract_row["contract_yaml"]
    if not isinstance(contract, dict):
        raise HTTPException(status_code=500, detail="contract_yaml is not an object")

    # Enrich with property landing prefix for path agreement when missing
    if property_row.get("s3_prefix_pattern") and not (
        (contract.get("filename") or {}).get("path_pattern")
        or (contract.get("filename") or {}).get("path_regex")
        or contract.get("s3_prefix_pattern")
    ):
        contract = {
            **contract,
            "s3_prefix_pattern": property_row["s3_prefix_pattern"],
        }

    return contract, property_row, contract_row


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "service": "airlock-engine",
        "version": APP_VERSION,
        "timestamp": _utc_now_iso(),
        "supabase_configured": is_supabase_configured(),
        "sla_scheduler_running": bool(_scheduler.running),
    }


@app.post("/api/v1/workers/check-slas")
async def trigger_sla_check(
    dispatch_alerts: bool = True,
) -> dict[str, Any]:
    """
    Manually trigger the SLA Delivery Ledger worker (for external cron).
    """
    if not is_supabase_configured():
        raise HTTPException(
            status_code=503,
            detail="Supabase is not configured on the engine.",
        )
    try:
        return await check_property_sla_deliveries(dispatch_alerts=dispatch_alerts)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=500, detail=f"SLA check failed: {exc}"
        ) from exc


@app.get("/api/v1/properties/{property_id}")
def get_property(property_id: str) -> dict[str, Any]:
    """Fetch property + active ingestion contract from Supabase (service role)."""
    if not is_supabase_configured():
        raise HTTPException(
            status_code=503,
            detail="Supabase is not configured on the engine.",
        )
    try:
        property_row, contract_row = fetch_property_contract(property_id)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=502, detail=f"Supabase query failed: {exc}"
        ) from exc

    if not property_row:
        raise HTTPException(status_code=404, detail=f"Property '{property_id}' not found")

    return {"property": property_row, "contract": contract_row}


@app.post("/api/v1/inference/inspect", response_model=SchemaInferenceResult)
async def inspect_file(
    file: Optional[UploadFile] = File(None),
    s3_uri: Optional[str] = Form(None),
    filename: Optional[str] = Form(None),
) -> SchemaInferenceResult:
    """Infer encoding, delimiter, and sample headers via Polars."""
    raw = b""
    resolved_name = filename

    if file is not None:
        raw = await file.read()
        resolved_name = resolved_name or file.filename
    elif s3_uri:
        raw = await _fetch_uri_bytes(s3_uri.strip())
        if not resolved_name:
            resolved_name = urlparse(s3_uri).path.rsplit("/", 1)[-1] or None
    else:
        raise HTTPException(
            status_code=400,
            detail="Provide a multipart file upload or s3_uri form field.",
        )

    if not raw:
        raise HTTPException(status_code=400, detail="Empty payload; nothing to inspect.")

    return infer_schema_from_bytes(raw, resolved_name or "sample.csv")


@app.post("/api/v1/inference/inspect/json", response_model=SchemaInferenceResult)
async def inspect_json(body: InspectRequest) -> SchemaInferenceResult:
    if not body.s3_uri:
        raise HTTPException(status_code=400, detail="s3_uri is required for JSON inspect.")
    raw = await _fetch_uri_bytes(body.s3_uri.strip())
    name = body.filename or urlparse(body.s3_uri).path.rsplit("/", 1)[-1] or "sample.csv"
    if not raw:
        raise HTTPException(status_code=400, detail="Empty object; nothing to inspect.")
    return infer_schema_from_bytes(raw, name)


@app.post("/api/v1/airlock/dry-run", response_model=DryRunResponse)
async def airlock_dry_run(req: DryRunRequest) -> DryRunResponse:
    """
    Execute Gates 1–4 against payload bytes + active property contract YAML.
    """
    inline = _parse_contract_doc(req.contract_yaml, req.contract_json)
    contract, _property_row, contract_row = _hydrate_contract(req.property_id, inline)

    path = req.path or req.s3_uri or ""
    payload = _decode_payload(req)
    uri = req.s3_uri or req.path
    if req.fetch_uri and uri and not payload:
        payload = await _fetch_uri_bytes(uri)

    # Gate 1
    gate1 = evaluate_gate_1(
        raw_bytes=payload,
        filename=req.filename,
        path=path,
        contract_yaml=contract,
        present_batch_filenames=req.present_batch_filenames or None,
    )

    tokens = gate1.filename_tokens
    business_date = tokens.date or ""
    report_type = tokens.report_type
    checksum = _sha256(payload)

    gate1_blocked = gate1.overall_outcome in {
        Gate1Outcome.REJECT_FILE,
        Gate1Outcome.QUARANTINE_FILE,
    }

    gate2_cfg = contract.get("gate_2") if isinstance(contract.get("gate_2"), dict) else {}
    gates_block = contract.get("gates") if isinstance(contract.get("gates"), dict) else {}
    gate2_anomaly = (
        gates_block.get("gate2_anomaly")
        if isinstance(gates_block.get("gate2_anomaly"), dict)
        else {}
    )
    max_z = float(
        gate2_cfg.get(
            "max_z_score",
            gate2_anomaly.get("zscore_threshold", 2.5),
        )
    )
    enforce_dow = bool(gate2_cfg.get("enforce_dow_baseline", False))
    frozen_days = int(
        gate2_cfg.get(
            "frozen_date_threshold_days",
            gate2_anomaly.get(
                "max_allowed_age_days",
                gate2_anomaly.get("frozen_window", {}).get("max_allowed_age_days", 30)
                if isinstance(gate2_anomaly.get("frozen_window"), dict)
                else 30,
            ),
        )
    )
    rolling_days = int(
        gate2_cfg.get(
            "rolling_window_days",
            gate2_anomaly.get("rolling_window_days", 30),
        )
    )
    min_samples = int(
        gate2_cfg.get(
            "min_historical_samples",
            gate2_anomaly.get("min_historical_samples", 7),
        )
    )
    amount_z = float(
        gate2_cfg.get(
            "amount_z_threshold",
            gate2_anomaly.get("amount_z_threshold", 3.0),
        )
    )

    history: list[dict[str, Any]] = []
    if not gate1_blocked and is_supabase_configured():
        try:
            history = fetch_run_reports_history(
                req.property_id,
                report_type=report_type,
                lookback_days=max(45, frozen_days + 15, rolling_days + 15),
            )
        except Exception:  # noqa: BLE001
            history = []

    gate2 = evaluate_gate_2(
        run_reports_history=history,
        current_row_count=int(gate1.total_rows or 0),
        business_date=business_date or datetime.now(timezone.utc).date().isoformat(),
        max_z_score=max_z,
        property_id=req.property_id,
        report_type=report_type,
        current_checksum=checksum,
        enforce_dow_baseline=enforce_dow,
        frozen_date_threshold_days=frozen_days,
        rolling_window_days=rolling_days,
        min_historical_samples=min_samples,
        amount_z_threshold=amount_z,
        skip=gate1_blocked,
        skip_reason=(
            f"Gate 2 skipped: Gate 1 outcome={gate1.overall_outcome.value}."
            if gate1_blocked
            else ""
        ),
    )

    df = _payload_to_dataframe(payload, contract)
    quality_rules = (
        contract.get("gate_3")
        if isinstance(contract.get("gate_3"), dict)
        else contract.get("quality_rules")
        if isinstance(contract.get("quality_rules"), dict)
        else {}
    )
    revenue_rules = (
        contract.get("gate_4")
        if isinstance(contract.get("gate_4"), dict)
        else contract.get("revenue_rules")
        if isinstance(contract.get("revenue_rules"), dict)
        else {}
    )

    gate3 = evaluate_gate_3(df, quality_rules or {})
    gate4 = evaluate_gate_4(df, revenue_rules or {})

    overall = _combine_outcomes(
        _gate1_to_common(gate1.overall_outcome),
        gate2.overall_outcome,
        gate3.overall_outcome,
        gate4.overall_outcome,
    )
    reason_parts = [
        f"G1: {gate1.outcome_reason}"
        if gate1.overall_outcome != Gate1Outcome.PASS
        else "",
        f"G2: {gate2.outcome_reason}"
        if gate2.overall_outcome != GateOutcome.PASS
        else "",
        f"G3: {gate3.outcome_reason}"
        if gate3.overall_outcome != GateOutcome.PASS
        else "",
        f"G4: {gate4.outcome_reason}"
        if gate4.overall_outcome != GateOutcome.PASS
        else "",
    ]
    outcome_reason = "; ".join(p for p in reason_parts if p) or (
        "All Gates 1–4 passed."
    )

    return DryRunResponse(
        run_id=_new_run_id(),
        timestamp=_utc_now_iso(),
        property_id=req.property_id,
        filename=req.filename,
        path=path or None,
        overall_outcome=overall,
        outcome_reason=outcome_reason,
        gate1_report=gate1,
        gate2_report=gate2,
        gate3_report=gate3,
        gate4_report=gate4,
        contract_profile_id=(contract_row or {}).get("profile_id")
        or contract.get("profile_id"),
        contract_version=(contract_row or {}).get("version"),
    )


@app.post("/api/v1/airlock/dry-run/upload", response_model=DryRunResponse)
async def airlock_dry_run_upload(
    property_id: str = Form(...),
    filename: Optional[str] = Form(None),
    path: Optional[str] = Form(None),
    s3_uri: Optional[str] = Form(None),
    present_batch_filenames: str = Form(""),
    contract_json: Optional[str] = Form(None),
    fetch_uri: bool = Form(False),
    file: Optional[UploadFile] = File(None),
) -> DryRunResponse:
    """Multipart dry-run for the Property Setup test bench (file upload or S3 key)."""
    resolved_name = filename or (file.filename if file else None)
    if not resolved_name and not s3_uri:
        raise HTTPException(status_code=400, detail="filename, file upload, or s3_uri required")

    if not resolved_name and s3_uri:
        resolved_name = urlparse(s3_uri).path.rsplit("/", 1)[-1] or "object.bin"

    payload_b64: Optional[str] = None
    if file is not None:
        raw = await file.read()
        payload_b64 = base64.b64encode(raw).decode("ascii")

    batch = [s.strip() for s in present_batch_filenames.split(",") if s.strip()]

    inline: Optional[dict[str, Any]] = None
    if contract_json and str(contract_json).strip():
        try:
            parsed = json.loads(contract_json)
        except json.JSONDecodeError as exc:
            raise HTTPException(
                status_code=400, detail=f"Invalid contract_json: {exc}"
            ) from exc
        if not isinstance(parsed, dict):
            raise HTTPException(status_code=400, detail="contract_json must be an object")
        inline = parsed

    return await airlock_dry_run(
        DryRunRequest(
            property_id=property_id,
            filename=resolved_name,
            path=path,
            s3_uri=s3_uri,
            payload_b64=payload_b64,
            fetch_uri=fetch_uri,
            present_batch_filenames=batch,
            contract_json=inline,
        )
    )


def _normalize_business_date(raw: str) -> str:
    text = (raw or "").strip()
    if not text:
        return datetime.now(timezone.utc).date().isoformat()
    if len(text) == 8 and text.isdigit():
        return f"{text[0:4]}-{text[4:6]}-{text[6:8]}"
    return text[:10]


def _normalize_feed_category(
    raw: Optional[str],
    contract: Optional[dict[str, Any]] = None,
) -> Optional[str]:
    candidate = (raw or "").strip().lower()
    if not candidate and isinstance(contract, dict):
        candidate = str(contract.get("feed_category") or "").strip().lower()
    aliases = {
        "pos": "pos",
        "pms": "pms",
        "res": "res",
        "reservations": "res",
        "lake": "lake",
        "data_lake": "lake",
        "dwh": "dwh",
        "data_warehouse": "dwh",
    }
    return aliases.get(candidate)


def _findings_from_dry(dry: DryRunResponse) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for report in (
        dry.gate1_report,
        dry.gate2_report,
        dry.gate3_report,
        dry.gate4_report,
    ):
        for ev in getattr(report, "evaluations", []) or []:
            out.append(
                {
                    "check_name": getattr(ev, "rule_name", None)
                    or (ev.get("rule_name") if isinstance(ev, dict) else None),
                    "passed": getattr(ev, "passed", None)
                    if not isinstance(ev, dict)
                    else ev.get("passed"),
                    "message": getattr(ev, "message", None)
                    if not isinstance(ev, dict)
                    else ev.get("message"),
                }
            )
    return out


def _delimiter_from_contract(contract: Optional[dict[str, Any]]) -> str:
    if not isinstance(contract, dict):
        return ","
    fmt = contract.get("file_format") if isinstance(contract.get("file_format"), dict) else {}
    return str(fmt.get("delimiter") or contract.get("delimiter") or ",")


def _build_diagnostics_for_dry(
    dry: DryRunResponse,
    *,
    payload: bytes,
    contract: Optional[dict[str, Any]] = None,
) -> tuple[ReadinessStats, list[QuarantineManifestItem]]:
    try:
        text = payload.decode("utf-8", errors="replace") if payload else ""
    except Exception:
        text = ""
    outcome = (
        dry.overall_outcome.value
        if hasattr(dry.overall_outcome, "value")
        else str(dry.overall_outcome)
    )
    enriched = build_execution_enrichment(
        run_id=dry.run_id,
        property_id=dry.property_id,
        business_date=_normalize_business_date(
            dry.gate1_report.filename_tokens.date
            or datetime.now(timezone.utc).date().isoformat()
        ),
        outcome=outcome,
        total_rows=int(dry.gate1_report.total_rows or 0),
        gate_reports={
            "gate_1": dry.gate1_report,
            "gate_2": dry.gate2_report,
            "gate_3": dry.gate3_report,
            "gate_4": dry.gate4_report,
        },
        payload_text=text,
        delimiter=_delimiter_from_contract(contract),
        report_type=dry.gate1_report.filename_tokens.report_type or "",
        feed_category=_normalize_feed_category(
            None, contract
        ),
        findings=_findings_from_dry(dry),
        s3_path=dry.path,
        outcome_reason=dry.outcome_reason,
    )
    return enriched.readiness_stats, enriched.quarantine_manifest


def _persist_execution_run(
    dry: DryRunResponse,
    req: DryRunRequest,
    *,
    payload: bytes,
    contract: Optional[dict[str, Any]] = None,
) -> tuple[str, str, Optional[str], list[dict[str, Any]], ReadinessStats, list[QuarantineManifestItem]]:
    """Insert ExecutionRunReport into run_reports. Returns metadata tuple."""
    report_type = dry.gate1_report.filename_tokens.report_type or "unknown"
    business_date = _normalize_business_date(
        dry.gate1_report.filename_tokens.date
        or datetime.now(timezone.utc).date().isoformat()
    )
    try:
        biz_dt = datetime.strptime(business_date[:10], "%Y-%m-%d")
        dow = str(biz_dt.weekday())
    except ValueError:
        dow = str(datetime.now(timezone.utc).weekday())

    feed_category = _normalize_feed_category(
        getattr(req, "feed_category", None), contract
    )
    findings = _findings_from_dry(dry)
    readiness_stats, quarantine_manifest = _build_diagnostics_for_dry(
        dry, payload=payload, contract=contract
    )
    gate_evaluations = {
        "gate_1": dry.gate1_report.model_dump(mode="json"),
        "gate_2": dry.gate2_report.model_dump(mode="json"),
        "gate_3": dry.gate3_report.model_dump(mode="json"),
        "gate_4": dry.gate4_report.model_dump(mode="json"),
        "outcome_reason": dry.outcome_reason,
        "filename": dry.filename,
        "present_batch_filenames": list(req.present_batch_filenames or []),
        "s3_path": dry.path,
        "findings": findings,
        "feed_category": feed_category,
        "readiness_stats": readiness_stats.model_dump(mode="json"),
        "quarantine_manifest": [
            m.model_dump(mode="json") for m in quarantine_manifest
        ],
    }
    checksum = _sha256(payload) or "0" * 64
    row = {
        "run_id": dry.run_id,
        "property_id": dry.property_id,
        "report_type": report_type,
        "business_date": business_date[:10],
        "day_of_week": dow,
        "overall_outcome": dry.overall_outcome.value
        if hasattr(dry.overall_outcome, "value")
        else str(dry.overall_outcome),
        "total_read_rows": int(dry.gate1_report.total_rows or 0),
        "file_size_bytes": int(dry.gate1_report.bytes_read or len(payload) or 0),
        "checksum_sha256": checksum,
        "gate_evaluations": gate_evaluations,
        "findings": findings,
        "s3_path": dry.path,
        "outcome_reason": dry.outcome_reason,
        "feed_category": feed_category,
        "readiness_stats": readiness_stats.model_dump(mode="json"),
        "quarantine_manifest": [
            m.model_dump(mode="json") for m in quarantine_manifest
        ],
    }
    insert_run_report(row)
    return (
        report_type,
        business_date[:10],
        feed_category,
        findings,
        readiness_stats,
        quarantine_manifest,
    )


@app.post("/api/v1/airlock/evaluate", response_model=EvaluateResponse)
async def airlock_evaluate(req: EvaluateRequest) -> EvaluateResponse:
    """
    Evaluate Gates 1–4. When persist_run=true, write to run_reports for the
    adjudication queue (ExecutionRunReport).
    """
    dry = await airlock_dry_run(req)
    findings = _findings_from_dry(dry)
    payload = _decode_payload(req)
    uri = req.s3_uri or req.path
    if req.fetch_uri and uri and not payload:
        try:
            payload = await _fetch_uri_bytes(uri)
        except HTTPException:
            payload = b""

    inline = _parse_contract_doc(req.contract_yaml, req.contract_json)
    contract, _prop, _crow = _hydrate_contract(req.property_id, inline)
    readiness_stats, quarantine_manifest = _build_diagnostics_for_dry(
        dry, payload=payload, contract=contract
    )

    if not req.persist_run:
        return EvaluateResponse(
            **dry.model_dump(),
            persisted=False,
            findings=findings,
            readiness_stats=readiness_stats,
            quarantine_manifest=quarantine_manifest,
        )

    if not is_supabase_configured():
        raise HTTPException(
            status_code=503,
            detail="Supabase is required when persist_run=true.",
        )

    try:
        (
            report_type,
            business_date,
            feed_category,
            findings,
            readiness_stats,
            quarantine_manifest,
        ) = _persist_execution_run(dry, req, payload=payload, contract=contract)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=502,
            detail=f"Failed to persist run report to adjudication queue: {exc}",
        ) from exc

    return EvaluateResponse(
        **dry.model_dump(),
        persisted=True,
        report_type=report_type,
        business_date=business_date,
        feed_category=feed_category,
        findings=findings,
        readiness_stats=readiness_stats,
        quarantine_manifest=quarantine_manifest,
    )


@app.post("/api/v1/airlock/runs/{run_id}/release", response_model=ReleaseResponse)
async def airlock_release_run(run_id: str, req: ReleaseRequest) -> ReleaseResponse:
    """
    Approve a blocked run for downstream ETL (RELEASED_TO_ETL).

    Emits logical event airlock.run.released for dbt/Spark consumers.
    """
    if not is_supabase_configured():
        raise HTTPException(status_code=503, detail="Supabase is required for release.")

    existing = fetch_run_report_by_id(run_id)
    if not existing:
        raise HTTPException(status_code=404, detail=f"run_id not found: {run_id}")

    outcome = str(existing.get("overall_outcome") or "")
    releasable = {"HOLD_SET", "QUARANTINE_FILE", "FLAG", "REJECT_FILE"}
    if outcome == "RELEASED_TO_ETL":
        return ReleaseResponse(
            success=True,
            run_id=run_id,
            status="RELEASED_TO_ETL",
            released_by=str(existing.get("released_by") or req.operator_id),
            released_at=str(existing.get("released_at") or ""),
            message="Run already released to ETL.",
        )
    if outcome not in releasable:
        raise HTTPException(
            status_code=409,
            detail=f"Run outcome {outcome} cannot be released (allowed: {sorted(releasable)}).",
        )

    try:
        updated = release_run_report(
            run_id, operator_id=req.operator_id, reason=req.reason
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Release failed: {exc}") from exc

    event_payload = {
        "event": "airlock.run.released",
        "run_id": run_id,
        "property_id": updated.get("property_id") or existing.get("property_id"),
        "report_type": updated.get("report_type") or existing.get("report_type"),
        "business_date": str(
            updated.get("business_date") or existing.get("business_date") or ""
        ),
        "feed_category": updated.get("feed_category") or existing.get("feed_category"),
        "s3_path": updated.get("s3_path") or existing.get("s3_path"),
        "released_by": req.operator_id,
        "released_at": updated.get("released_at"),
        "reason": req.reason,
    }
    logging.getLogger("airlock.events").info(
        "airlock.run.released %s", json.dumps(event_payload, default=str)
    )

    return ReleaseResponse(
        success=True,
        run_id=run_id,
        status="RELEASED_TO_ETL",
        released_by=str(updated.get("released_by") or req.operator_id),
        released_at=str(updated.get("released_at") or ""),
        message="Run released to ETL.",
    )


@app.post("/api/v1/airlock/runs/{run_id}/classify", response_model=ClassifyResponse)
async def airlock_classify_run(run_id: str, req: ClassifyRequest) -> ClassifyResponse:
    """
    Persist operator re-classification tags onto quarantine_manifest items.
    """
    if not is_supabase_configured():
        raise HTTPException(
            status_code=503, detail="Supabase is required for classification."
        )
    if not req.classifications:
        raise HTTPException(status_code=400, detail="classifications list is required.")

    existing = fetch_run_report_by_id(run_id)
    if not existing:
        raise HTTPException(status_code=404, detail=f"run_id not found: {run_id}")

    current = existing.get("quarantine_manifest") or []
    if not isinstance(current, list):
        current = []
    patches = [c.model_dump(mode="json") for c in req.classifications]
    merged = apply_user_classifications(current, patches)

    try:
        updated = classify_run_report(
            run_id,
            quarantine_manifest=merged,
            operator_id=req.operator_id,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=502, detail=f"Classification persist failed: {exc}"
        ) from exc

    manifest_raw = updated.get("quarantine_manifest") or merged
    items: list[QuarantineManifestItem] = []
    for row in manifest_raw:
        if isinstance(row, dict):
            try:
                items.append(QuarantineManifestItem.model_validate(row))
            except Exception:
                continue

    return ClassifyResponse(
        success=True,
        run_id=run_id,
        quarantine_manifest=items,
        message=f"Updated {len(req.classifications)} classification(s).",
    )


@app.post("/api/v1/airlock/ingest", response_model=IngestResponse)
async def airlock_ingest(req: DryRunRequest) -> IngestResponse:
    """
    Live ingestion path: evaluate Gates 1–4 then append an immutable run_report.

    Used by the S3/landing simulator and future landing-bucket listeners.
    """
    if not is_supabase_configured():
        raise HTTPException(
            status_code=503,
            detail="Supabase is required for /airlock/ingest persistence.",
        )

    dry = await airlock_dry_run(req)
    payload = _decode_payload(req)
    uri = req.s3_uri or req.path
    if req.fetch_uri and uri and not payload:
        try:
            payload = await _fetch_uri_bytes(uri)
        except HTTPException:
            payload = b""

    inline = _parse_contract_doc(req.contract_yaml, req.contract_json)
    contract, _prop, _crow = _hydrate_contract(req.property_id, inline)
    try:
        (
            report_type,
            business_date,
            feed_category,
            _findings,
            _stats,
            _manifest,
        ) = _persist_execution_run(dry, req, payload=payload, contract=contract)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=502,
            detail=f"Failed to persist run report to adjudication queue: {exc}",
        ) from exc

    return IngestResponse(
        **dry.model_dump(),
        persisted=True,
        report_type=report_type,
        business_date=business_date,
        feed_category=feed_category,
    )
