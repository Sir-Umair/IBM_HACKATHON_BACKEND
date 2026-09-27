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
from app.models.api_models import (
    TransactionRead,
    TransactionCreate,
    BatchDeleteRequest,
    ScenarioGenerateRequest,
    ScenarioGenerateResponse,
)
from app.models.db_models import Transaction, SystemSetting
from app.config import get_settings
import uuid
import random
from datetime import date, timedelta

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
    # Mark database as active (not purged) so it retains data seamlessly
    db.merge(SystemSetting(key="user_purged", value="false"))
    db.merge(SystemSetting(key="system_initialized", value="true"))
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
    Leaves the database 100% clean and records persistent purge flag to prevent auto-reseed on refresh.
    """
    from app.models.db_models import EvidenceRecord, Investigation, InvestigationFinding
    from sqlalchemy import text

    tx_count = db.query(Transaction).delete()
    ev_count = db.query(EvidenceRecord).delete()
    f_count = db.query(InvestigationFinding).delete()
    inv_count = db.query(Investigation).delete()

    # Record persistent purge state in system_settings
    db.merge(SystemSetting(key="user_purged", value="true"))
    db.merge(SystemSetting(key="system_initialized", value="true"))
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
        "message": "Database completely wiped. All dummy data permanently removed and purge state saved.",
    }


@router.post("/generate-scenario", response_model=ScenarioGenerateResponse)
def generate_scenario_transactions(
    payload: ScenarioGenerateRequest,
    db: Session = Depends(get_db),
):
    """
    Dynamically generates realistic enterprise financial transaction batches.
    Tailored for live hackathon presentations and custom scenario testing.
    """
    try:
        parts = payload.period.split("-")
        year = int(parts[0])
        month = int(parts[1])
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid period format (expected YYYY-MM)")

    company = payload.company_name or "TechNova Corp"
    scenario = payload.scenario_type.lower()
    count = payload.record_count or 20

    tx_list: list[Transaction] = []
    total_sales = 0.0
    total_costs = 0.0

    # Products & Categories
    sample_products = [
        ("AI Cloud Workstation", "Electronics", 2800.0, 1680.0, "Supplier A"),
        ("Quantum Edge Router", "Electronics", 1250.0, 720.0, "Supplier B"),
        ("Enterprise SaaS Platform", "Software", 3500.0, 450.0, "Supplier E"),
        ("Secure Key Hardware", "Electronics", 95.0, 38.0, "Supplier B"),
        ("Smart Office Display 4K", "Electronics", 680.0, 410.0, "Supplier A"),
        ("High-Speed Fiber Switch", "Electronics", 890.0, 490.0, "Supplier B"),
    ]

    rnd = random.Random(f"{payload.period}-{scenario}-{count}")

    # Generate custom transactions according to requested scenario archetype
    for i in range(1, count + 1):
        day = min(28, (i * 28 // count) + rnd.randint(0, 1))
        tx_date = date(year, month, max(1, day))
        tx_id = f"TX-DYN-{year}{month:02d}-{uuid.uuid4().hex[:6].upper()}"

        if scenario == "cost_spike":
            # 45% sales, 40% heavy supplier purchase surge, 15% expenses
            if i % 3 == 0:
                # Normal sale
                prod_name, cat, price, cost_unit, supp = rnd.choice(sample_products)
                qty = rnd.randint(1, 4)
                amt = price * qty
                total_sales += amt
                tx = Transaction(
                    transaction_id=tx_id, date=tx_date, transaction_type="sale",
                    category=cat, description=f"Client order fulfilled: {prod_name}",
                    amount=amt, quantity=float(qty), unit_price=price, cost=cost_unit * qty,
                    customer=f"Client_{rnd.randint(10, 99)}", product=prod_name, supplier=supp,
                    status="completed", period=payload.period
                )
            elif i % 3 == 1:
                # Severe supplier cost surge on Supplier A
                amt = rnd.randint(3500, 9800)
                total_costs += amt
                tx = Transaction(
                    transaction_id=tx_id, date=tx_date, transaction_type="purchase",
                    category="Electronics", description=f"Urgent component restock — Supplier A surcharge",
                    amount=amt, quantity=float(rnd.randint(5, 20)), cost=amt,
                    supplier="Supplier A", product="AI Cloud Workstation",
                    status="completed", period=payload.period
                )
            else:
                amt = rnd.randint(800, 2400)
                total_costs += amt
                tx = Transaction(
                    transaction_id=tx_id, date=tx_date, transaction_type="expense",
                    category="Logistics", description="Emergency freight & international tariff fee",
                    amount=amt, supplier="Supplier D", status="completed", period=payload.period
                )

        elif scenario == "refund_wave":
            # 50% sales, 35% large refunds due to quality crisis, 15% expenses
            if i % 3 == 0:
                amt = rnd.randint(2200, 6800)
                total_costs += amt  # refunds reduce net inflow / counted as outflow in summary
                tx = Transaction(
                    transaction_id=tx_id, date=tx_date, transaction_type="refund",
                    category="Electronics", description="RMA Batch Defect Refund — Power unit failure",
                    amount=amt, product="AI Cloud Workstation", customer=f"Enterprise_{rnd.randint(1, 30)}",
                    status="completed", period=payload.period
                )
            elif i % 3 == 1:
                prod_name, cat, price, cost_unit, supp = rnd.choice(sample_products)
                qty = rnd.randint(1, 3)
                amt = price * qty
                total_sales += amt
                tx = Transaction(
                    transaction_id=tx_id, date=tx_date, transaction_type="sale",
                    category=cat, description=f"Standard sale: {prod_name}",
                    amount=amt, quantity=float(qty), unit_price=price, cost=cost_unit * qty,
                    customer=f"Customer_{rnd.randint(100, 150)}", product=prod_name, supplier=supp,
                    status="completed", period=payload.period
                )
            else:
                amt = rnd.randint(500, 1500)
                total_costs += amt
                tx = Transaction(
                    transaction_id=tx_id, date=tx_date, transaction_type="expense",
                    category="Operations", description="Product return inspection and handling fee",
                    amount=amt, status="completed", period=payload.period
                )

        elif scenario == "profitable_growth":
            # 70% high-margin sales, 20% lean purchases, 10% operating costs
            if i % 4 != 0:
                prod_name, cat, price, cost_unit, supp = sample_products[2] if i % 2 == 0 else rnd.choice(sample_products)
                qty = rnd.randint(2, 6)
                amt = price * qty
                total_sales += amt
                tx = Transaction(
                    transaction_id=tx_id, date=tx_date, transaction_type="sale",
                    category=cat, description=f"High-growth client expansion: {prod_name}",
                    amount=amt, quantity=float(qty), unit_price=price, cost=cost_unit * qty * 0.8,
                    customer=f"Enterprise_{company}_{rnd.randint(1, 20)}", product=prod_name, supplier=supp,
                    status="completed", period=payload.period
                )
            else:
                amt = rnd.randint(600, 1800)
                total_costs += amt
                tx = Transaction(
                    transaction_id=tx_id, date=tx_date, transaction_type="expense",
                    category="Marketing", description="Targeted enterprise account acquisition ads",
                    amount=amt, status="completed", period=payload.period
                )

        else:  # "balanced" or "margin_drop"
            is_sale = (i % 2 == 0)
            if is_sale:
                prod_name, cat, price, cost_unit, supp = rnd.choice(sample_products)
                qty = rnd.randint(1, 5)
                amt = price * qty
                total_sales += amt
                margin_factor = 0.90 if scenario == "margin_drop" else 0.60
                tx = Transaction(
                    transaction_id=tx_id, date=tx_date, transaction_type="sale",
                    category=cat, description=f"Commercial order: {prod_name}",
                    amount=amt, quantity=float(qty), unit_price=price, cost=amt * margin_factor,
                    customer=f"Buyer_{rnd.randint(200, 250)}", product=prod_name, supplier=supp,
                    status="completed", period=payload.period
                )
            else:
                amt = rnd.randint(900, 3200)
                total_costs += amt
                tx = Transaction(
                    transaction_id=tx_id, date=tx_date, transaction_type="purchase",
                    category="Electronics", description="Procurement batch components",
                    amount=amt, supplier="Supplier B", status="completed", period=payload.period
                )

        tx_list.append(tx)

    db.add_all(tx_list)
    db.merge(SystemSetting(key="user_purged", value="false"))
    db.merge(SystemSetting(key="system_initialized", value="true"))
    db.commit()

    net_profit = total_sales - total_costs
    logger.info("Generated %d dynamic transactions for %s scenario (%s)", len(tx_list), scenario, payload.period)
    return ScenarioGenerateResponse(
        status="success",
        scenario_type=scenario,
        period=payload.period,
        company_name=company,
        inserted_count=len(tx_list),
        total_revenue=round(total_sales, 2),
        total_expenses=round(total_costs, 2),
        net_profit=round(net_profit, 2),
        message=f"Successfully injected {len(tx_list)} dynamic transactions into ledger for period {payload.period}.",
    )





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

    if inserted > 0:
        db.merge(SystemSetting(key="user_purged", value="false"))
        db.merge(SystemSetting(key="system_initialized", value="true"))

    db.commit()

    return {
        "inserted": inserted,
        "errors": len(errors),
        "error_details": errors[:20],
    }

