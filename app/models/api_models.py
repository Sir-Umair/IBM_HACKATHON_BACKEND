"""Pydantic API models for request/response validation."""
from pydantic import BaseModel, Field, field_validator
from typing import Optional, Any
from datetime import date
import re


# ─── Transaction Models ───────────────────────────────────────────────────────

class TransactionBase(BaseModel):
    transaction_id: str
    date: date
    transaction_type: str
    category: str
    subcategory: Optional[str] = None
    description: str
    amount: float
    quantity: Optional[float] = None
    unit_price: Optional[float] = None
    cost: Optional[float] = None
    customer: Optional[str] = None
    supplier: Optional[str] = None
    product: Optional[str] = None
    status: str = "completed"
    period: str


class TransactionCreate(BaseModel):
    transaction_id: Optional[str] = None
    date: date
    transaction_type: str  # sale, purchase, expense, refund, fee
    category: str
    subcategory: Optional[str] = None
    description: str
    amount: float
    quantity: Optional[float] = 1.0
    unit_price: Optional[float] = None
    cost: Optional[float] = None
    customer: Optional[str] = None
    supplier: Optional[str] = None
    product: Optional[str] = None
    status: Optional[str] = "completed"
    period: Optional[str] = None


class TransactionRead(TransactionBase):
    id: int

    model_config = {"from_attributes": True}


class BatchDeleteRequest(BaseModel):
    transaction_ids: list[str]


# ─── Chat / Interactive AI Models ──────────────────────────────────────────


class ChatQueryRequest(BaseModel):
    question: str
    investigation_id: Optional[str] = None
    period: Optional[str] = None


class ChatQueryResponse(BaseModel):
    answer: str
    evidence_ids: list[str] = []
    metrics: dict[str, Any] = {}
    timestamp: str = ""


# ─── Investigation Models ─────────────────────────────────────────────────────

class InvestigateRequest(BaseModel):
    question: str = Field(..., min_length=3, max_length=1000)
    current_period: str = Field(..., pattern=r"^\d{4}-\d{2}$")
    comparison_period: str = Field(..., pattern=r"^\d{4}-\d{2}$")

    @field_validator("current_period", "comparison_period")
    @classmethod
    def validate_period(cls, v: str) -> str:
        parts = v.split("-")
        month = int(parts[1])
        if not 1 <= month <= 12:
            raise ValueError("Month must be between 01 and 12")
        return v


class FindingModel(BaseModel):
    finding_type: str
    category: Optional[str] = None
    entity: Optional[str] = None
    impact: Optional[float] = None
    percentage_change: Optional[float] = None
    description: str
    verified: str = "unverified"
    evidence_ids: list[str] = []


class VerificationModel(BaseModel):
    status: str  # "passed" | "failed" | "partial"
    checks: list[dict[str, Any]] = []
    errors: list[str] = []


class WorkflowStep(BaseModel):
    step: str
    status: str  # "running" | "completed" | "skipped" | "failed"
    details: Optional[str] = None


class InvestigationResponse(BaseModel):
    investigation_id: str
    status: str
    question: str
    current_period: str
    comparison_period: str
    intent: Optional[str] = None
    summary: Optional[str] = None
    metrics: dict[str, Any] = {}
    comparison: dict[str, Any] = {}
    findings: list[FindingModel] = []
    evidence: list[dict[str, Any]] = []
    workflow: list[WorkflowStep] = []
    verification: VerificationModel = VerificationModel(status="pending")
    explanation: Optional[str] = None
    errors: list[str] = []


# ─── Dashboard Models ─────────────────────────────────────────────────────────

class PeriodMetrics(BaseModel):
    period: str
    revenue: float
    expenses: float
    cogs: float
    profit: float
    gross_margin_pct: float
    refund_rate_pct: float
    transaction_count: int


class DashboardResponse(BaseModel):
    current_period: str
    metrics: PeriodMetrics
    prior_metrics: Optional[PeriodMetrics] = None
    revenue_vs_expenses: list[dict[str, Any]] = []
    daily_trend: list[dict[str, Any]] = []
    cumulative_trend: list[dict[str, Any]] = []
    profit_trend: list[dict[str, Any]] = []
    expense_breakdown: list[dict[str, Any]] = []
    category_performance: list[dict[str, Any]] = []
    available_periods: list[str] = []

