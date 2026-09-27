"""SQLAlchemy ORM models for the financial investigator database."""
from sqlalchemy import Column, Integer, String, Float, Date, DateTime, Text, ForeignKey, Enum
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base
import enum


class TransactionType(str, enum.Enum):
    sale = "sale"
    purchase = "purchase"
    expense = "expense"
    refund = "refund"
    fee = "fee"


class TransactionStatus(str, enum.Enum):
    completed = "completed"
    pending = "pending"
    cancelled = "cancelled"


class Transaction(Base):
    __tablename__ = "transactions"

    id = Column(Integer, primary_key=True, index=True)
    transaction_id = Column(String(20), unique=True, index=True, nullable=False)
    date = Column(Date, nullable=False, index=True)
    transaction_type = Column(String(20), nullable=False, index=True)
    category = Column(String(100), nullable=False, index=True)
    subcategory = Column(String(100), nullable=True)
    description = Column(String(500), nullable=False)
    amount = Column(Float, nullable=False)
    quantity = Column(Float, nullable=True, default=1.0)
    unit_price = Column(Float, nullable=True)
    cost = Column(Float, nullable=True)  # COGS for sales
    customer = Column(String(200), nullable=True)
    supplier = Column(String(200), nullable=True, index=True)
    product = Column(String(200), nullable=True, index=True)
    status = Column(String(20), nullable=False, default="completed")
    period = Column(String(7), nullable=False, index=True)  # "YYYY-MM"
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class Product(Base):
    __tablename__ = "products"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(200), unique=True, nullable=False, index=True)
    category = Column(String(100), nullable=False)
    base_price = Column(Float, nullable=False)
    base_cost = Column(Float, nullable=False)
    supplier = Column(String(200), nullable=True)


class Supplier(Base):
    __tablename__ = "suppliers"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(200), unique=True, nullable=False, index=True)
    category = Column(String(100), nullable=False)
    contact = Column(String(200), nullable=True)


class Category(Base):
    __tablename__ = "categories"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), unique=True, nullable=False, index=True)
    description = Column(String(500), nullable=True)


class Investigation(Base):
    __tablename__ = "investigations"

    id = Column(Integer, primary_key=True, index=True)
    investigation_id = Column(String(50), unique=True, nullable=False, index=True)
    question = Column(Text, nullable=False)
    current_period = Column(String(7), nullable=False)
    comparison_period = Column(String(7), nullable=False)
    status = Column(String(20), nullable=False, default="running")
    intent = Column(String(100), nullable=True)
    summary = Column(Text, nullable=True)
    result_json = Column(Text, nullable=True)  # full JSON result
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    completed_at = Column(DateTime(timezone=True), nullable=True)

    findings = relationship("InvestigationFinding", back_populates="investigation", cascade="all, delete-orphan")


class InvestigationFinding(Base):
    __tablename__ = "investigation_findings"

    id = Column(Integer, primary_key=True, index=True)
    investigation_id = Column(String(50), ForeignKey("investigations.investigation_id"), nullable=False)
    finding_type = Column(String(100), nullable=False)
    category = Column(String(100), nullable=True)
    entity = Column(String(200), nullable=True)
    impact = Column(Float, nullable=True)
    percentage_change = Column(Float, nullable=True)
    description = Column(Text, nullable=True)
    verified = Column(String(10), nullable=False, default="unverified")
    evidence_ids = Column(Text, nullable=True)  # comma-separated TX IDs

    investigation = relationship("Investigation", back_populates="findings")


class EvidenceRecord(Base):
    __tablename__ = "evidence_records"

    id = Column(Integer, primary_key=True, index=True)
    investigation_id = Column(String(50), nullable=False, index=True)
    finding_ref = Column(String(100), nullable=True)
    transaction_id = Column(String(20), nullable=False, index=True)
    relevance = Column(String(500), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
