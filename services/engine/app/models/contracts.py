"""Pydantic models for Airlock contract persistence API."""

from __future__ import annotations

from typing import Any, Optional, Union

from pydantic import BaseModel, Field


# JS epoch-ms fits in signed 64-bit; INT4 overflows ~2038 for seconds and
# immediately for millisecond timestamps (e.g. 1786501628757).
ContractVersion = Union[int, str]


class AirlockContractPayload(BaseModel):
    """POST /api/v1/airlock/contracts body."""

    property_id: str = Field(..., min_length=1)
    feed_id: str = Field(..., min_length=1)
    feed_category: Optional[str] = None
    system_preset: str = Field(..., min_length=1)
    file_format: str = Field(default="delimited_text")
    contract_yaml: dict[str, Any] = Field(default_factory=dict)
    engine_contract: dict[str, Any] = Field(default_factory=dict)
    timezone: Optional[str] = None
    sla_cutoff_time: Optional[str] = None
    grace_period_minutes: Optional[int] = None
    alert_emails: Optional[list[str]] = None
    slack_channel: Optional[str] = None
    existing_ingestion_contract_id: Optional[str] = None
    # Optional BIGINT-safe revision token (epoch-ms or numeric string).
    version: Optional[ContractVersion] = None
    contract_version: Optional[ContractVersion] = None
    created_at_ms: Optional[int] = Field(default=None, ge=0)
    updated_at_ms: Optional[int] = Field(default=None, ge=0)


class IngestionContractRow(BaseModel):
    """Row shape for ingestion_contracts (version is BIGINT-capable)."""

    id: Optional[str] = None
    profile_id: str
    version: ContractVersion
    file_format: str
    contract_yaml: dict[str, Any] = Field(default_factory=dict)
    description: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class AirlockContractResponse(BaseModel):
    id: str
    property_id: str
    feed_id: str
    feed_category: Optional[str] = None
    system_preset: str
    status: str = "published"
    version: ContractVersion = "2.0"
    updated_at: str
    ingestion_contract_id: Optional[str] = None
    contract_yaml: dict[str, Any] = Field(default_factory=dict)
    engine_contract: dict[str, Any] = Field(default_factory=dict)
    source: str = "database"  # database | preset_fallback
