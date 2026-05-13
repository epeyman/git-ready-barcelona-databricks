"""Pydantic request/response schemas for the portal HTTP API.

Schemas live here (not in osi_bridge) because they describe the wire format
between the portal's JS frontend and the FastAPI handlers — not the OSI
contract itself. They reference OSI dicts loosely (`dict[str, Any]`) so
custom_extensions and future OSI additions pass through without schema work.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ModelSummary(BaseModel):
    name: str
    description: str | None = None
    source: str | None = None
    metric_count: int
    dimension_count: int
    owner: str | None = None
    domain: str | None = None
    engines: list[str] = Field(default_factory=list)
    default_engine: str | None = None


class MetricSummary(BaseModel):
    model: str
    name: str
    display_name: str | None = None
    description: str | None = None
    synonyms: list[str] = Field(default_factory=list)


class DimensionSummary(BaseModel):
    name: str
    display_name: str | None = None
    is_time: bool = False
    synonyms: list[str] = Field(default_factory=list)
    description: str | None = None


class SearchHit(MetricSummary):
    score: float


class SearchResponse(BaseModel):
    query: str
    hits: list[SearchHit]


class FallbackRequest(BaseModel):
    query: str


class FallbackResponse(BaseModel):
    query: str
    suggested_models: list[str] = Field(default_factory=list)
    rationale: str = ""
    owner_contacts: list[str] = Field(default_factory=list)
    request_action: str = ""


class ChatRequest(BaseModel):
    question: str
    max_steps: int = 8


class ToolCall(BaseModel):
    step: int
    name: str
    arguments: dict[str, Any]
    result_preview: str


class ChatResponse(BaseModel):
    answer: str
    trace: list[ToolCall]


class AccessRequest(BaseModel):
    model: str
    requester: str
    business_justification: str = ""


class AccessRequestResponse(BaseModel):
    id: str
    model: str
    requester: str
    status: str
    note: str
