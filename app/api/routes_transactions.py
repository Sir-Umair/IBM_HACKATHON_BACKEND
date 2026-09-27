"""Transaction routes — list, filter, and CSV upload."""

from __future__ import annotations

import csv
import io
import logging
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.api_models import TransactionRead, TransactionCreate, BatchDeleteRequest
from app.models.db_models import Transaction
from app.config import get_settings
import uuid

router = APIRouter(prefix="/api/transactions", tags=["transactions"])
logger = logging.getLogger(__name__)
settings = get_settings()

MAX_UPLOAD_BYTES = settings.max_upload_size_mb * 1024 * 1024


@router.post("", response_model=TransactionRead, status_code=201)
def create_transaction(
    payload: TransactionCreate,
    db: Session = Depends(get_db),
):
    """Create a new financial transaction with amount and classification."""
    tx_id = payload.transaction_id
    if not tx_id:
        tx_id = f"TX-{uuid.uuid4().hex[:8].upper()}"

    # Verify uniqueness
    existing = db.query(Transaction).filter(Transaction.transaction_id == tx_id).first()
    if existing:
        raise HTTPException(status_code=400, detail=f"Transaction ID {tx_id} already exists")

    tx_date = payload.date
    period = payload.period or f"{tx_date.year}-{tx_date.month:02d}"

    # Auto-calculate unit_price or cost if not provided
    quantity = payload.quantity or 1.0
    unit_price = payload.unit_price
    if unit_price is None and quantity > 0:
        unit_price = round(payload.amount / quantity, 2)

    cost = payload.cost
    if cost is None and payload.transaction_type == "sale":
        # Estimate standard 65% cost of goods sold if not provided
        cost = round(payload.amount * 0.65, 2)

    new_tx = Transaction(
        transaction_id=tx_id,
        date=tx_date,
        transaction_type=payload.transaction_type.lower(),
        category=payload.category,
        subcategory=payload.subcategory,
        description=payload.description,
        amount=float(payload.amount),
        quantity=float(quantity),
        unit_price=float(unit_price) if unit_price is not None else None,
        cost=float(cost) if cost is not None else None,
        customer=payload.customer,
        supplier=payload.supplier,
        product=payload.product,
        status=payload.status or "completed",
        period=period,
    )

    db.add(new_tx)
    db.commit()
    db.refresh(new_tx)
    logger.info("Created transaction %s: amount=%.2f type=%s", tx_id, new_tx.amount, new_tx.transaction_type)
    return new_tx


@router.delete("/{transaction_id}")
def delete_transaction(transaction_id: str, db: Session = Depends(get_db)):
    """Delete a transaction by ID permanently."""
    tx = db.query(Transaction).filter(Transaction.transaction_id == transaction_id).first()
    if not tx:
        raise HTTPException(status_code=404, detail=f"Transaction {transaction_id} not found")

    amt = tx.amount
    db.delete(tx)
    db.commit()
    logger.info("Permanently deleted transaction %s", transaction_id)
    return {"status": "deleted", "transaction_id": transaction_id, "amount": amt}


@router.post("/batch-delete")
def batch_delete_transactions(
    payload: BatchDeleteRequest,
    db: Session = Depends(get_db),
):
    """Batch delete multiple transactions permanently."""
    if not payload.transaction_ids:
        return {"status": "ok", "deleted_count": 0}

    count = db.query(Transaction).filter(
        Transaction.transaction_id.isin(payload.transaction_ids)
    ).delete(synchronize_session=False)
    db.commit()
    logger.info("Batch deleted %d transactions", count)
    return {"status": "deleted", "deleted_count": count}


@router.post("/purge")
def purge_all_transactions(db: Session = Depends(get_db)):
    """
    PERMANENTLY PURGE ALL DATA from database (transactions, investigations, evidence).
    Leaves the database 100% clean with zero dummy data.
    """
    from app.models.db_models import EvidenceRecord, Investigation, InvestigationFinding
    from sqlalchemy import text

    tx_count = db.query(Transaction).delete()
    ev_count = db.query(EvidenceRecord).delete()
    f_count = db.query(InvestigationFinding).delete()
    inv_count = db.query(Investigation).delete()

    db.commit()

    try:
        db.execute(text("VACUUM"))
        db.commit()
    except Exception:
        pass

    logger.info("Purged database: %d txs, %d investigations, %d evidence records", tx_count, inv_count, ev_count)
    return {
        "status": "purged",
        "deleted_transactions": tx_count,
        "deleted_investigations": inv_count,
        "deleted_evidence": ev_count,
        "message": "Database completely wiped. All dummy data permanently removed.",
    }




@router.get("", response_model=list[TransactionRead])
def list_transactions(
    period: Optional[str] = Query(default=None, pattern=r"^\d{4}-\d{2}$"),
    transaction_type: Optional[str] = Query(default=None),
    category: Optional[str] = Query(default=None),
    supplier: Optional[str] = Query(default=None),
    product: Optional[str] = Query(default=None),
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    """List transactions with optional filters."""
    query = db.query(Transaction)
    if period:
        query = query.filter(Transaction.period == period)
    if transaction_type:
        query = query.filter(Transaction.transaction_type == transaction_type)
    if category:
        query = query.filter(Transaction.category == category)
    if supplier:
        query = query.filter(Transaction.supplier == supplier)
    if product:
        query = query.filter(Transaction.product == product)
    return query.order_by(Transaction.date.desc()).offset(offset).limit(limit).all()


@router.get("/{transaction_id}", response_model=TransactionRead)
def get_transaction(transaction_id: str, db: Session = Depends(get_db)):
    tx = db.query(Transaction).filter(Transaction.transaction_id == transaction_id).first()
    if not tx:
        raise HTTPException(status_code=404, detail=f"Transaction {transaction_id} not found")
    return tx


@router.post("/upload")
async def upload_transactions(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """Upload transactions from a CSV file."""
    if not file.filename or not file.filename.endswith(".csv"):
        raise HTTPException(status_code=400, detail="Only CSV files are accepted")

    contents = await file.read()
    if len(contents) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"File too large. Maximum size: {settings.max_upload_size_mb}MB",
        )

    required_cols = {
        "transaction_id", "date", "transaction_type",
        "category", "description", "amount",
    }

    try:
        text = contents.decode("utf-8")
        reader = csv.DictReader(io.StringIO(text))
        rows = list(reader)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid CSV: {exc}")

    if not rows:
        raise HTTPException(status_code=400, detail="CSV file is empty")

    headers = set(rows[0].keys())
    missing = required_cols - headers
    if missing:
        raise HTTPException(
            status_code=400,
            detail=f"CSV missing required columns: {missing}",
        )

    inserted = 0
    errors: list[str] = []

    for i, row in enumerate(rows):
        try:
            # Validate required fields
            if not row.get("transaction_id") or not row.get("amount"):
                errors.append(f"Row {i+1}: missing required field")
                continue

            amount = float(row["amount"])
            tx_date = date.fromisoformat(row["date"])
            period = row.get("period") or f"{tx_date.year}-{tx_date.month:02d}"

            # Check for duplicate
            existing = db.query(Transaction).filter(
                Transaction.transaction_id == row["transaction_id"]
            ).first()
            if existing:
                errors.append(f"Row {i+1}: duplicate transaction_id {row['transaction_id']}")
                continue

            tx = Transaction(
                transaction_id=row["transaction_id"],
                date=tx_date,
                transaction_type=row["transaction_type"],
                category=row["category"],
                subcategory=row.get("subcategory"),
                description=row["description"],
                amount=amount,
                quantity=float(row["quantity"]) if row.get("quantity") else None,
                unit_price=float(row["unit_price"]) if row.get("unit_price") else None,
                cost=float(row["cost"]) if row.get("cost") else None,
                customer=row.get("customer"),
                supplier=row.get("supplier"),
                product=row.get("product"),
                status=row.get("status", "completed"),
                period=period,
            )
            db.add(tx)
            inserted += 1

        except (ValueError, KeyError) as exc:
            errors.append(f"Row {i+1}: {exc}")

    db.commit()

    return {
        "inserted": inserted,
        "errors": len(errors),
        "error_details": errors[:20],
    }
