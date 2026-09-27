"""
Seed script: generates 500+ deterministic synthetic transactions.

Intentional financial events embedded in the data:
  - Supplier A costs: Jan $12,000 → Feb $18,100   (+$6,100)
  - Supplier B costs: Jan $9,200  → Feb $12,700   (+$3,500)
  - Refunds:          Jan $2,000  → Feb $6,200     (+$4,200)
  - Electronics margin: Jan 30%  → Feb 20%  (higher COGS)
  - Operating expenses: Jan $8,000 → Feb $10,100  (+$2,100)

Summary:
  January:  Revenue $100,000 | Expenses $60,000 | Profit $40,000
  February: Revenue $105,000 | Expenses $82,000 | Profit $23,000
"""

import sys
import os
import random
from datetime import date, timedelta
from pathlib import Path

# Allow running from backend/ directory
sys.path.insert(0, str(Path(__file__).parent))

from app.database import SessionLocal, init_db
from app.models.db_models import Transaction, Product, Supplier, Category, SystemSetting

random.seed(42)

# ─── Master data ──────────────────────────────────────────────────────────────

CATEGORIES = [
    {"name": "Electronics", "description": "Electronic devices and accessories"},
    {"name": "Office Supplies", "description": "Office consumables and equipment"},
    {"name": "Software", "description": "Software licenses and SaaS subscriptions"},
    {"name": "Marketing", "description": "Marketing and advertising expenses"},
    {"name": "Operations", "description": "General operational expenses"},
    {"name": "Logistics", "description": "Shipping and delivery costs"},
]

SUPPLIERS = [
    {"name": "Supplier A", "category": "Electronics"},
    {"name": "Supplier B", "category": "Electronics"},
    {"name": "Supplier C", "category": "Office Supplies"},
    {"name": "Supplier D", "category": "Logistics"},
    {"name": "Supplier E", "category": "Software"},
]

PRODUCTS = [
    {"name": "Laptop Pro X1",     "category": "Electronics",    "base_price": 1200, "base_cost": 840,  "supplier": "Supplier A"},
    {"name": "Laptop Pro X2",     "category": "Electronics",    "base_price": 950,  "base_cost": 665,  "supplier": "Supplier A"},
    {"name": "Wireless Mouse",    "category": "Electronics",    "base_price": 45,   "base_cost": 18,   "supplier": "Supplier B"},
    {"name": "Mechanical Keyboard","category": "Electronics",   "base_price": 120,  "base_cost": 52,   "supplier": "Supplier B"},
    {"name": "Monitor 27\"",      "category": "Electronics",    "base_price": 380,  "base_cost": 228,  "supplier": "Supplier A"},
    {"name": "USB-C Hub",         "category": "Electronics",    "base_price": 65,   "base_cost": 26,   "supplier": "Supplier B"},
    {"name": "Printer Paper A4",  "category": "Office Supplies","base_price": 28,   "base_cost": 12,   "supplier": "Supplier C"},
    {"name": "Desk Organizer",    "category": "Office Supplies","base_price": 35,   "base_cost": 15,   "supplier": "Supplier C"},
    {"name": "Notebook Pack",     "category": "Office Supplies","base_price": 22,   "base_cost": 9,    "supplier": "Supplier C"},
    {"name": "SaaS License Pro",  "category": "Software",       "base_price": 299,  "base_cost": 0,    "supplier": "Supplier E"},
    {"name": "Cloud Storage Plan","category": "Software",       "base_price": 149,  "base_cost": 0,    "supplier": "Supplier E"},
]

CUSTOMERS = [f"Customer_{i:03d}" for i in range(1, 51)]

EXPENSE_DESCS = {
    "Marketing":   ["Digital ad campaign", "Trade show booth", "Social media ads", "Email marketing", "Content creation"],
    "Operations":  ["Office rent", "Utilities bill", "Insurance premium", "HR service fee", "Accounting fee"],
    "Logistics":   ["Freight charges", "Last-mile delivery", "Warehouse storage", "Returns handling", "Courier service"],
}

tx_counter = [1]


def next_tx_id() -> str:
    tid = f"TX-{tx_counter[0]:04d}"
    tx_counter[0] += 1
    return tid


def random_date(year: int, month: int) -> date:
    if month == 12:
        last_day = 31
    else:
        last_day = (date(year, month + 1, 1) - timedelta(days=1)).day
    return date(year, month, random.randint(1, last_day))


def make_sale(product: dict, qty: int, year: int, month: int,
              cost_multiplier: float = 1.0, price_multiplier: float = 1.0) -> dict:
    unit_price = round(product["base_price"] * price_multiplier, 2)
    unit_cost = round(product["base_cost"] * cost_multiplier, 2)
    amount = round(unit_price * qty, 2)
    cost = round(unit_cost * qty, 2)
    return {
        "transaction_id": next_tx_id(),
        "date": random_date(year, month),
        "transaction_type": "sale",
        "category": product["category"],
        "subcategory": "product_sale",
        "description": f"Sale: {product['name']} x{qty}",
        "amount": amount,
        "quantity": qty,
        "unit_price": unit_price,
        "cost": cost,
        "customer": random.choice(CUSTOMERS),
        "supplier": None,
        "product": product["name"],
        "status": "completed",
        "period": f"{year}-{month:02d}",
    }


def make_purchase(supplier_name: str, category: str, amount: float, year: int, month: int, desc: str = None) -> dict:
    return {
        "transaction_id": next_tx_id(),
        "date": random_date(year, month),
        "transaction_type": "purchase",
        "category": category,
        "subcategory": "supplier_purchase",
        "description": desc or f"Purchase from {supplier_name}",
        "amount": amount,
        "quantity": 1,
        "unit_price": amount,
        "cost": None,
        "customer": None,
        "supplier": supplier_name,
        "product": None,
        "status": "completed",
        "period": f"{year}-{month:02d}",
    }


def make_expense(category: str, amount: float, year: int, month: int) -> dict:
    desc = random.choice(EXPENSE_DESCS.get(category, ["General expense"]))
    return {
        "transaction_id": next_tx_id(),
        "date": random_date(year, month),
        "transaction_type": "expense",
        "category": category,
        "subcategory": "operating_expense",
        "description": desc,
        "amount": amount,
        "quantity": 1,
        "unit_price": amount,
        "cost": None,
        "customer": None,
        "supplier": None,
        "product": None,
        "status": "completed",
        "period": f"{year}-{month:02d}",
    }


def make_refund(product: dict, amount: float, year: int, month: int) -> dict:
    return {
        "transaction_id": next_tx_id(),
        "date": random_date(year, month),
        "transaction_type": "refund",
        "category": product["category"],
        "subcategory": "customer_refund",
        "description": f"Refund: {product['name']}",
        "amount": amount,
        "quantity": 1,
        "unit_price": amount,
        "cost": None,
        "customer": random.choice(CUSTOMERS),
        "supplier": None,
        "product": product["name"],
        "status": "completed",
        "period": f"{year}-{month:02d}",
    }


def make_fee(desc: str, amount: float, year: int, month: int) -> dict:
    return {
        "transaction_id": next_tx_id(),
        "date": random_date(year, month),
        "transaction_type": "fee",
        "category": "Operations",
        "subcategory": "service_fee",
        "description": desc,
        "amount": amount,
        "quantity": 1,
        "unit_price": amount,
        "cost": None,
        "customer": None,
        "supplier": None,
        "product": None,
        "status": "completed",
        "period": f"{year}-{month:02d}",
    }


# ─── Transaction generators per month ─────────────────────────────────────────

def generate_january(year=2026) -> list[dict]:
    """
    January target:
      Revenue  = $100,000
      Expenses = $60,000
      Profit   = $40,000

    Expense breakdown:
      Supplier A purchases:   $12,000
      Supplier B purchases:   $9,200
      Supplier C purchases:   $3,800
      Supplier D (logistics): $5,000
      Marketing expenses:     $9,000
      Operations expenses:    $8,000
      Logistics expenses:     $3,000
      Fees:                   $2,000
      Refunds:                $2,000  (negative revenue)
      COGS embedded in sales: ~$7,000
    """
    transactions = []
    m = 1

    # --- Sales: Electronics (Laptop Pro X1) ---  ~$42,000 revenue
    products = {p["name"]: p for p in PRODUCTS}
    for _ in range(15):
        transactions.append(make_sale(products["Laptop Pro X1"], 1, year, m))        # 15 * 1200 = 18000
    for _ in range(10):
        transactions.append(make_sale(products["Laptop Pro X2"], 1, year, m))        # 10 * 950  = 9500
    for _ in range(30):
        transactions.append(make_sale(products["Wireless Mouse"], random.randint(2,4), year, m))  # ~3600
    for _ in range(15):
        transactions.append(make_sale(products["Mechanical Keyboard"], 1, year, m)) # 15 * 120 = 1800
    for _ in range(5):
        transactions.append(make_sale(products['Monitor 27"'], 1, year, m))         # 5 * 380 = 1900
    for _ in range(20):
        transactions.append(make_sale(products["USB-C Hub"], random.randint(1,3), year, m)) # ~2600

    # --- Sales: Office Supplies ---  ~$12,000 revenue
    for _ in range(40):
        transactions.append(make_sale(products["Printer Paper A4"], random.randint(2,5), year, m))
    for _ in range(20):
        transactions.append(make_sale(products["Desk Organizer"], 1, year, m))
    for _ in range(25):
        transactions.append(make_sale(products["Notebook Pack"], random.randint(1,3), year, m))

    # --- Sales: Software ---  ~$18,000 revenue
    for _ in range(30):
        transactions.append(make_sale(products["SaaS License Pro"], 1, year, m))    # 30 * 299 = 8970
    for _ in range(35):
        transactions.append(make_sale(products["Cloud Storage Plan"], 1, year, m))  # 35 * 149 = 5215

    # --- Supplier Purchases (COGS top-ups / inventory) ---
    # Supplier A: $12,000 across several purchases
    for amount in [3000, 2500, 2800, 2200, 1500]:
        transactions.append(make_purchase("Supplier A", "Electronics", amount, year, m,
                                          "Electronics inventory - Supplier A"))
    # Supplier B: $9,200
    for amount in [2500, 2200, 2000, 1500, 1000]:
        transactions.append(make_purchase("Supplier B", "Electronics", amount, year, m,
                                          "Electronics inventory - Supplier B"))
    # Supplier C: $3,800
    for amount in [1200, 1000, 900, 700]:
        transactions.append(make_purchase("Supplier C", "Office Supplies", amount, year, m,
                                          "Office supplies inventory - Supplier C"))
    # Supplier D: $5,000
    for amount in [1500, 1200, 1000, 800, 500]:
        transactions.append(make_purchase("Supplier D", "Logistics", amount, year, m,
                                          "Logistics services - Supplier D"))

    # --- Operating Expenses ---
    # Marketing: $9,000
    for amount in [2500, 2000, 1800, 1500, 1200]:
        transactions.append(make_expense("Marketing", amount, year, m))
    # Operations: $8,000
    for amount in [2500, 2000, 1500, 1200, 800]:
        transactions.append(make_expense("Operations", amount, year, m))
    # Logistics: $3,000
    for amount in [1200, 1000, 800]:
        transactions.append(make_expense("Logistics", amount, year, m))

    # --- Fees: $2,000 ---
    transactions.append(make_fee("Platform transaction fee", 800, year, m))
    transactions.append(make_fee("Payment processing fee", 700, year, m))
    transactions.append(make_fee("Bank service charge", 500, year, m))

    # --- Refunds: $2,000 ---
    for amount in [400, 350, 300, 280, 250, 200, 220]:
        transactions.append(make_refund(
            random.choice([products["Laptop Pro X1"], products["Laptop Pro X2"], products["Wireless Mouse"]]),
            amount, year, m
        ))

    return transactions


def generate_february(year=2026) -> list[dict]:
    """
    February target:
      Revenue  = $105,000
      Expenses = $82,000
      Profit   = $23,000

    Key events:
      Supplier A:      $18,100  (+$6,100 vs Jan)
      Supplier B:      $12,700  (+$3,500 vs Jan)
      Refunds:         $6,200   (+$4,200 vs Jan)
      Operations:      $10,100  (+$2,100 vs Jan)
      Electronics COGS: higher unit cost (margin squeeze)
    """
    transactions = []
    m = 2
    products = {p["name"]: p for p in PRODUCTS}

    # --- Sales: Electronics (slightly higher volume, but higher COGS squeezes margin) ---
    # Electronics cost_multiplier = 1.25 to represent margin squeeze
    cm = 1.25  # cost multiplier for electronics in February
    for _ in range(16):
        transactions.append(make_sale(products["Laptop Pro X1"], 1, year, m, cost_multiplier=cm))
    for _ in range(11):
        transactions.append(make_sale(products["Laptop Pro X2"], 1, year, m, cost_multiplier=cm))
    for _ in range(32):
        transactions.append(make_sale(products["Wireless Mouse"], random.randint(2,4), year, m, cost_multiplier=cm))
    for _ in range(17):
        transactions.append(make_sale(products["Mechanical Keyboard"], 1, year, m, cost_multiplier=cm))
    for _ in range(6):
        transactions.append(make_sale(products['Monitor 27"'], 1, year, m, cost_multiplier=cm))
    for _ in range(22):
        transactions.append(make_sale(products["USB-C Hub"], random.randint(1,3), year, m, cost_multiplier=cm))

    # --- Sales: Office Supplies ---
    for _ in range(42):
        transactions.append(make_sale(products["Printer Paper A4"], random.randint(2,5), year, m))
    for _ in range(22):
        transactions.append(make_sale(products["Desk Organizer"], 1, year, m))
    for _ in range(28):
        transactions.append(make_sale(products["Notebook Pack"], random.randint(1,3), year, m))

    # --- Sales: Software ---
    for _ in range(33):
        transactions.append(make_sale(products["SaaS License Pro"], 1, year, m))
    for _ in range(38):
        transactions.append(make_sale(products["Cloud Storage Plan"], 1, year, m))

    # --- Supplier Purchases ---
    # Supplier A: $18,100  (INTENTIONAL INCREASE)
    for amount in [4500, 4000, 3600, 3200, 2800]:
        transactions.append(make_purchase("Supplier A", "Electronics", amount, year, m,
                                          "Electronics inventory - Supplier A"))
    # Supplier B: $12,700  (INTENTIONAL INCREASE)
    for amount in [3200, 2900, 2500, 2100, 1000, 1000]:
        transactions.append(make_purchase("Supplier B", "Electronics", amount, year, m,
                                          "Electronics inventory - Supplier B"))
    # Supplier C: $4,100 (slight increase)
    for amount in [1400, 1100, 900, 700]:
        transactions.append(make_purchase("Supplier C", "Office Supplies", amount, year, m,
                                          "Office supplies inventory - Supplier C"))
    # Supplier D: $5,500
    for amount in [1800, 1400, 1100, 800, 400]:
        transactions.append(make_purchase("Supplier D", "Logistics", amount, year, m,
                                          "Logistics services - Supplier D"))

    # --- Operating Expenses ---
    # Marketing: $9,200 (slight increase)
    for amount in [2600, 2100, 1900, 1600, 1000]:
        transactions.append(make_expense("Marketing", amount, year, m))
    # Operations: $10,100  (INTENTIONAL INCREASE by $2,100 vs Jan $8,000)
    for amount in [3000, 2500, 1900, 1500, 1200]:
        transactions.append(make_expense("Operations", amount, year, m))
    # Logistics: $3,500
    for amount in [1500, 1200, 800]:
        transactions.append(make_expense("Logistics", amount, year, m))

    # --- Fees: $2,400 ---
    transactions.append(make_fee("Platform transaction fee", 900, year, m))
    transactions.append(make_fee("Payment processing fee", 850, year, m))
    transactions.append(make_fee("Bank service charge", 650, year, m))

    # --- Refunds: $6,200  (INTENTIONAL INCREASE - +$4,200 vs Jan $2,000) ---
    for amount in [800, 750, 700, 650, 600, 550, 500, 450, 400, 400, 400]:
        transactions.append(make_refund(
            random.choice([products["Laptop Pro X1"], products["Laptop Pro X2"],
                           products["Wireless Mouse"], products["Mechanical Keyboard"]]),
            amount, year, m
        ))

    return transactions


def generate_march(year=2026) -> list[dict]:
    """March: partial recovery, used for trend context."""
    transactions = []
    m = 3
    products = {p["name"]: p for p in PRODUCTS}

    # Sales recover
    for _ in range(18):
        transactions.append(make_sale(products["Laptop Pro X1"], 1, year, m))
    for _ in range(12):
        transactions.append(make_sale(products["Laptop Pro X2"], 1, year, m))
    for _ in range(35):
        transactions.append(make_sale(products["Wireless Mouse"], random.randint(2,4), year, m))
    for _ in range(18):
        transactions.append(make_sale(products["Mechanical Keyboard"], 1, year, m))
    for _ in range(7):
        transactions.append(make_sale(products['Monitor 27"'], 1, year, m))
    for _ in range(25):
        transactions.append(make_sale(products["USB-C Hub"], random.randint(1,3), year, m))
    for _ in range(45):
        transactions.append(make_sale(products["Printer Paper A4"], random.randint(2,5), year, m))
    for _ in range(25):
        transactions.append(make_sale(products["Desk Organizer"], 1, year, m))
    for _ in range(30):
        transactions.append(make_sale(products["Notebook Pack"], random.randint(1,3), year, m))
    for _ in range(35):
        transactions.append(make_sale(products["SaaS License Pro"], 1, year, m))
    for _ in range(40):
        transactions.append(make_sale(products["Cloud Storage Plan"], 1, year, m))

    # Supplier costs (back to normal)
    for amount in [3200, 2800, 2500, 2000, 1500]:
        transactions.append(make_purchase("Supplier A", "Electronics", amount, year, m))
    for amount in [2500, 2200, 2000, 1500, 1000]:
        transactions.append(make_purchase("Supplier B", "Electronics", amount, year, m))
    for amount in [1300, 1000, 900, 700]:
        transactions.append(make_purchase("Supplier C", "Office Supplies", amount, year, m))
    for amount in [1600, 1300, 1000, 800, 500]:
        transactions.append(make_purchase("Supplier D", "Logistics", amount, year, m))

    # Expenses normalize
    for amount in [2400, 2000, 1800, 1500, 1100]:
        transactions.append(make_expense("Marketing", amount, year, m))
    for amount in [2600, 2100, 1600, 1200, 800]:
        transactions.append(make_expense("Operations", amount, year, m))
    for amount in [1200, 1000, 800]:
        transactions.append(make_expense("Logistics", amount, year, m))

    transactions.append(make_fee("Platform transaction fee", 850, year, m))
    transactions.append(make_fee("Payment processing fee", 750, year, m))
    transactions.append(make_fee("Bank service charge", 550, year, m))

    # Refunds recovering
    for amount in [400, 380, 350, 320, 300]:
        transactions.append(make_refund(
            random.choice([products["Laptop Pro X1"], products["Wireless Mouse"]]),
            amount, year, m
        ))

    return transactions


# ─── Main seeder ──────────────────────────────────────────────────────────────

def seed_all():
    print("Initializing database...")
    init_db()

    db = SessionLocal()
    try:
        # Clear existing data (idempotent re-run)
        for model in [Transaction, Product, Supplier, Category]:
            db.query(model).delete()
        db.commit()

        # Insert categories
        for c in CATEGORIES:
            db.add(Category(name=c["name"], description=c["description"]))

        # Insert suppliers
        for s in SUPPLIERS:
            db.add(Supplier(name=s["name"], category=s["category"]))

        # Insert products
        for p in PRODUCTS:
            db.add(Product(
                name=p["name"],
                category=p["category"],
                base_price=p["base_price"],
                base_cost=p["base_cost"],
                supplier=p.get("supplier"),
            ))

        db.commit()

        # Generate transactions
        all_transactions = []
        all_transactions.extend(generate_january())
        all_transactions.extend(generate_february())
        all_transactions.extend(generate_march())

        # Convert date objects if needed and insert
        for tx_data in all_transactions:
            tx = Transaction(**tx_data)
            db.add(tx)

        # Mark system settings so auto-reseed logic respects deliberate user state
        db.merge(SystemSetting(key="system_initialized", value="true"))
        db.merge(SystemSetting(key="user_purged", value="false"))
        db.commit()


        total = len(all_transactions)
        print(f"[OK] Seeded {len(CATEGORIES)} categories")
        print(f"[OK] Seeded {len(SUPPLIERS)} suppliers")
        print(f"[OK] Seeded {len(PRODUCTS)} products")
        print(f"[OK] Seeded {total} transactions across 3 months")

        # Print summary per period
        from collections import defaultdict
        summary = defaultdict(lambda: defaultdict(float))
        for tx in all_transactions:
            p = tx["period"]
            t = tx["transaction_type"]
            summary[p][t] += tx["amount"]

        print("\n-- Transaction Summary ------------------------------------------")
        for period in sorted(summary.keys()):
            s = summary[period]
            revenue = s.get("sale", 0)
            refunds = s.get("refund", 0)
            purchases = s.get("purchase", 0)
            expenses = s.get("expense", 0)
            fees = s.get("fee", 0)
            net_revenue = revenue - refunds
            total_costs = purchases + expenses + fees
            print(f"  {period}:")
            print(f"    Sales:     ${revenue:>10,.2f}  |  Refunds: ${refunds:,.2f}")
            print(f"    Purchases: ${purchases:>10,.2f}  |  Expenses: ${expenses:,.2f}  |  Fees: ${fees:,.2f}")
            print(f"    Net Revenue: ${net_revenue:,.2f}  |  Total Costs: ${total_costs:,.2f}")

    finally:
        db.close()


if __name__ == "__main__":
    # Ensure data directory exists
    data_dir = Path(__file__).parent / "data"
    data_dir.mkdir(exist_ok=True)
    seed_all()
    print("\nSeed complete.")
