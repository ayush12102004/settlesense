"""Synthetic data generator for SettleSense.

Produces 70 orders across three sources that mirror a real Razorpay merchant's
settlement cycle, plus a held-out ground truth the matching engine never sees.

Messiness injected (each documented in PRD §4):
  - UTR buried in noisy bank narration text
  - Gateway fee + GST-on-fee deducted before settlement (gross ≠ net)
  - Settlement lag (payout date ≠ bank credit date, 1–5 days)
  - Split settlement — one bank credit covers 2–3 orders
  - Partial refund / disputed status — net < expected legitimately
  - Duplicate-looking entries (same amount, same day, different orders)
  - Missing counterpart (ledger entry with no settlement yet — pending)
  - Mixed date/amount formats (DD/MM/YYYY, YYYY-MM-DD, ₹ strings, commas)

Deterministic: fixed seed makes every run identical and reviewable.
"""

from __future__ import annotations

import csv
import json
import os
import random
import uuid
from dataclasses import dataclass, field
from datetime import date, timedelta

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
SEED = 42
START = date(2025, 6, 1)
DAYS = 45  # ~6 weeks of settlement data

# Razorpay fee economics
RAZORPAY_FEE_RATE = 0.02       # 2% of gross
GST_ON_FEE_RATE = 0.18         # 18% GST on the fee itself
TDS_RATE = 0.01                # 1% TDS on certain transactions

# Bank narration templates — the real messy strings banks produce
NARRATION_TEMPLATES = [
    "NEFT/{utr}/RAZORPAY SOFTWARE PVT LTD/{ref}",
    "RTGS/{utr}/RAZORPAYSOFTWARE/{ref}",
    "NEFT-{utr}-RAZORPAY-SETTLEMENT-{ref}",
    "IMPS/{utr}/RAZORPAY/{ref}/SETTLEMENT",
    "NEFT {utr} RAZORPAY SOFTWAR PVT LTD {ref}",
    "BY TRANSFER-NEFT-{utr}-RAZORPAY SOFTWARE P-{ref}",
    "NEFT CR-{utr}-RAZORPAY SOFTWARE PVT-{ref}",
    "MMT/NEFT/{utr}/RAZORPAY/SETTLMNT/{ref}",
]

# Obfuscated narration templates — no clean UTR, forces tolerant/LLM matching
OBFUSCATED_TEMPLATES = [
    "BY CLG RAZORPAY STTLMNT {ref}",
    "ONLINE TRF RAZORPAY PVT {ref} SETL",
    "ACH CR RAZRPAY STLMT {ref}",
    "TRF FRM RAZORPAY-{ref_short}",
    "NEFT CR RZPAY SETTLMENT",
    "CLG CREDIT RAZORPAY SOFT {ref_short} PYMT",
]

# Channels merchants sell through
CHANNELS = ["online", "pos", "payment_link", "subscription"]

# Customer name fragments for narration noise
CUSTOMER_NAMES = [
    "ACME CORP", "PRIYA SHARMA", "RAJESH KUMAR", "SUNRISE TRADERS",
    "GLOBAL IMPEX", "TECHMART SOLUTIONS", "FLIPKART INDIA", "ZOMATO LTD",
    "FRESH FOODS CO", "QUANTUM LABS", "METRO RETAIL", "SKYLINE SERVICES",
]


@dataclass
class Order:
    """A single merchant order that flows through all three systems."""
    order_id: str
    payment_id: str
    customer_ref: str
    invoice_amount: float
    order_date: date
    channel: str
    # Gateway settlement fields
    gross_amount: float
    razorpay_fee: float
    gst_on_fee: float
    tax_deducted: float
    net_amount: float
    settlement_utr: str
    settlement_date: date
    gateway_status: str  # captured/refunded/partial_refund/disputed
    # Flags for messiness
    is_split: bool = False
    split_group_id: str | None = None
    is_duplicate_amount: bool = False
    is_pending: bool = False
    is_partial_refund: bool = False
    refund_amount: float = 0.0
    is_amount_mismatch: bool = False
    # Bank side
    bank_credit_date: date | None = None
    bank_amount: float | None = None


def _money(lo: float, hi: float) -> float:
    return round(random.uniform(lo, hi), 2)


def _gen_utr() -> str:
    """Generate a realistic UTR number (16 chars, alphanumeric)."""
    prefix = random.choice(["UTIB", "HDFC", "ICIC", "SBIN", "KKBK", "BARB"])
    num = "".join([str(random.randint(0, 9)) for _ in range(10)])
    return f"{prefix}{num}"


def _gen_payment_id() -> str:
    return f"pay_{uuid.uuid4().hex[:14]}"


def _gen_order_id(n: int) -> str:
    return f"order_{n:04d}"


def _gen_customer_ref() -> str:
    return f"CUST-{random.randint(10000, 99999)}"


def build() -> dict:
    random.seed(SEED)
    orders: list[Order] = []

    # --- Generate 70 base orders ------------------------------------------------
    # 55 normal, 6 split (3 pairs), 4 duplicates (2 pairs), 5 pending, 4 partial refund/disputed
    n = 0
    normal_count = 51

    # Normal orders — clean path through all three systems
    for _ in range(normal_count):
        n += 1
        invoice = _money(500, 45000)
        gross = invoice  # gateway gross = invoice amount
        fee = round(gross * RAZORPAY_FEE_RATE, 2)
        gst = round(fee * GST_ON_FEE_RATE, 2)
        # TDS only on higher-value transactions
        tds = round(gross * TDS_RATE, 2) if gross > 10000 else 0.0
        net = round(gross - fee - gst - tds, 2)

        order_date = START + timedelta(days=random.randint(0, DAYS - 10))
        settlement_date = order_date + timedelta(days=random.randint(1, 3))
        bank_credit_date = settlement_date + timedelta(days=random.randint(0, 4))

        utr = _gen_utr()
        orders.append(Order(
            order_id=_gen_order_id(n),
            payment_id=_gen_payment_id(),
            customer_ref=_gen_customer_ref(),
            invoice_amount=invoice,
            order_date=order_date,
            channel=random.choice(CHANNELS),
            gross_amount=gross,
            razorpay_fee=fee,
            gst_on_fee=gst,
            tax_deducted=tds,
            net_amount=net,
            settlement_utr=utr,
            settlement_date=settlement_date,
            gateway_status="captured",
            bank_credit_date=bank_credit_date,
            bank_amount=net,
        ))

    # Split settlements — 3 groups of 2–3 orders sharing one bank credit
    for group_idx in range(3):
        group_id = f"SPLIT_{group_idx + 1:02d}"
        group_size = random.choice([2, 2, 3])
        utr = _gen_utr()
        base_date = START + timedelta(days=random.randint(5, DAYS - 10))
        settlement_date = base_date + timedelta(days=random.randint(1, 3))
        bank_credit_date = settlement_date + timedelta(days=random.randint(1, 3))

        group_orders = []
        total_net = 0.0
        for _ in range(group_size):
            n += 1
            invoice = _money(1000, 15000)
            gross = invoice
            fee = round(gross * RAZORPAY_FEE_RATE, 2)
            gst = round(fee * GST_ON_FEE_RATE, 2)
            tds = 0.0
            net = round(gross - fee - gst - tds, 2)
            total_net += net

            order = Order(
                order_id=_gen_order_id(n),
                payment_id=_gen_payment_id(),
                customer_ref=_gen_customer_ref(),
                invoice_amount=invoice,
                order_date=base_date - timedelta(days=random.randint(0, 2)),
                channel=random.choice(CHANNELS),
                gross_amount=gross,
                razorpay_fee=fee,
                gst_on_fee=gst,
                tax_deducted=tds,
                net_amount=net,
                settlement_utr=utr,
                settlement_date=settlement_date,
                gateway_status="captured",
                is_split=True,
                split_group_id=group_id,
                bank_credit_date=bank_credit_date,
                bank_amount=round(total_net, 2),  # will be overwritten below
            )
            group_orders.append(order)

        # All orders in the split share the same bank credit
        total_net = round(total_net, 2)
        for o in group_orders:
            o.bank_amount = total_net
        orders.extend(group_orders)

    # Duplicate-looking entries — 2 pairs with same amount on same day
    for dup_idx in range(2):
        n += 1
        dup_amount = round(random.choice([2999.00, 4500.00, 7500.00, 1299.00]), 2)
        dup_date = START + timedelta(days=random.randint(10, DAYS - 10))

        for copy_idx in range(2):
            if copy_idx > 0:
                n += 1
            gross = dup_amount
            fee = round(gross * RAZORPAY_FEE_RATE, 2)
            gst = round(fee * GST_ON_FEE_RATE, 2)
            tds = 0.0
            net = round(gross - fee - gst, 2)
            utr = _gen_utr()
            settlement_date = dup_date + timedelta(days=1)
            bank_credit_date = settlement_date + timedelta(days=random.randint(1, 3))

            orders.append(Order(
                order_id=_gen_order_id(n),
                payment_id=_gen_payment_id(),
                customer_ref=_gen_customer_ref(),
                invoice_amount=dup_amount,
                order_date=dup_date,
                channel=random.choice(CHANNELS),
                gross_amount=gross,
                razorpay_fee=fee,
                gst_on_fee=gst,
                tax_deducted=tds,
                net_amount=net,
                settlement_utr=utr,
                settlement_date=settlement_date,
                gateway_status="captured",
                is_duplicate_amount=True,
                bank_credit_date=bank_credit_date,
                bank_amount=net,
            ))

    # Partial refunds / disputed — 4 orders where net < expected
    for _ in range(4):
        n += 1
        invoice = _money(3000, 20000)
        refund_pct = random.uniform(0.2, 0.6)
        refund_amount = round(invoice * refund_pct, 2)
        gross = round(invoice - refund_amount, 2)
        fee = round(gross * RAZORPAY_FEE_RATE, 2)
        gst = round(fee * GST_ON_FEE_RATE, 2)
        tds = 0.0
        net = round(gross - fee - gst, 2)
        utr = _gen_utr()
        order_date = START + timedelta(days=random.randint(0, DAYS - 10))
        settlement_date = order_date + timedelta(days=random.randint(2, 5))
        bank_credit_date = settlement_date + timedelta(days=random.randint(1, 3))
        status = random.choice(["partial_refund", "partial_refund", "disputed"])

        orders.append(Order(
            order_id=_gen_order_id(n),
            payment_id=_gen_payment_id(),
            customer_ref=_gen_customer_ref(),
            invoice_amount=invoice,
            order_date=order_date,
            channel=random.choice(CHANNELS),
            gross_amount=gross,
            razorpay_fee=fee,
            gst_on_fee=gst,
            tax_deducted=tds,
            net_amount=net,
            settlement_utr=utr,
            settlement_date=settlement_date,
            gateway_status=status,
            is_partial_refund=True,
            refund_amount=refund_amount,
            bank_credit_date=bank_credit_date,
            bank_amount=net,
        ))

    # Deliberate fee variance anomaly (chargeback penalty variance)
    n += 1
    mismatch_invoice = 14200.00
    m_fee = round(mismatch_invoice * RAZORPAY_FEE_RATE, 2)
    m_gst = round(m_fee * GST_ON_FEE_RATE, 2)
    m_net = round(mismatch_invoice - m_fee - m_gst, 2)
    m_utr = _gen_utr()
    m_order_date = START + timedelta(days=18)
    m_settlement_date = m_order_date + timedelta(days=2)
    m_bank_credit_date = m_settlement_date + timedelta(days=1)
    m_bank_amt = round(m_net - 250.00, 2)  # Dispute deduction caused 250 fee penalty variance

    orders.append(Order(
        order_id=_gen_order_id(n),
        payment_id=_gen_payment_id(),
        customer_ref=_gen_customer_ref(),
        invoice_amount=mismatch_invoice,
        order_date=m_order_date,
        channel="online",
        gross_amount=mismatch_invoice,
        razorpay_fee=m_fee,
        gst_on_fee=m_gst,
        tax_deducted=0.0,
        net_amount=m_net,
        settlement_utr=m_utr,
        settlement_date=m_settlement_date,
        gateway_status="disputed",
        is_amount_mismatch=True,
        bank_credit_date=m_bank_credit_date,
        bank_amount=m_bank_amt,
    ))

    # Pending orders — 5 orders in ledger with no settlement yet
    for _ in range(5):
        n += 1
        invoice = _money(1000, 25000)
        order_date = START + timedelta(days=random.randint(DAYS - 8, DAYS - 1))

        orders.append(Order(
            order_id=_gen_order_id(n),
            payment_id=_gen_payment_id(),
            customer_ref=_gen_customer_ref(),
            invoice_amount=invoice,
            order_date=order_date,
            channel=random.choice(CHANNELS),
            gross_amount=invoice,
            razorpay_fee=round(invoice * RAZORPAY_FEE_RATE, 2),
            gst_on_fee=round(invoice * RAZORPAY_FEE_RATE * GST_ON_FEE_RATE, 2),
            tax_deducted=0.0,
            net_amount=round(invoice - invoice * RAZORPAY_FEE_RATE
                             - invoice * RAZORPAY_FEE_RATE * GST_ON_FEE_RATE, 2),
            settlement_utr="",
            settlement_date=order_date + timedelta(days=random.randint(2, 5)),
            gateway_status="captured",
            is_pending=True,
            bank_credit_date=None,
            bank_amount=None,
        ))

    orders.sort(key=lambda o: (o.order_date, o.order_id))
    return {"orders": orders}


# ---------------------------------------------------------------------------
# Writers — each emits the format (and mess) of its real-world source
# ---------------------------------------------------------------------------

def _format_bank_narration(order: Order, obfuscate: bool = False) -> str:
    """Generate a messy bank narration with UTR buried in free text."""
    ref = random.choice(CUSTOMER_NAMES) if random.random() < 0.3 else order.order_id
    ref_short = order.order_id[-4:]
    if obfuscate:
        template = random.choice(OBFUSCATED_TEMPLATES)
        return template.format(ref=ref, ref_short=ref_short)
    template = random.choice(NARRATION_TEMPLATES)
    return template.format(utr=order.settlement_utr, ref=ref)


def _format_date_messy(d: date, idx: int) -> str:
    """Mix date formats to force real date parsing."""
    if idx % 3 == 0:
        return d.strftime("%d/%m/%Y")      # DD/MM/YYYY
    elif idx % 3 == 1:
        return d.strftime("%Y-%m-%d")       # ISO
    else:
        return d.strftime("%d-%b-%Y")       # 15-Jun-2025


def _format_amount_messy(amount: float, idx: int) -> str:
    """Mix amount formats: ₹ prefix, commas, plain."""
    if idx % 4 == 0:
        return f"₹{amount:,.2f}"
    elif idx % 4 == 1:
        return f"{amount:,.2f}"
    elif idx % 4 == 2:
        return f"INR {amount:.2f}"
    else:
        return f"{amount:.2f}"


def write_all(world: dict) -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    orders: list[Order] = world["orders"]

    # --- gateway_settlement.csv -----------------------------------------------
    settled_orders = [o for o in orders if not o.is_pending]
    with open(os.path.join(DATA_DIR, "gateway_settlement.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["payment_id", "order_id", "gross_amount", "razorpay_fee",
                     "gst_on_fee", "tax_deducted", "net_amount", "settlement_utr",
                     "settlement_date", "status"])
        for o in settled_orders:
            w.writerow([
                o.payment_id, o.order_id, o.gross_amount, o.razorpay_fee,
                o.gst_on_fee, o.tax_deducted, o.net_amount, o.settlement_utr,
                o.settlement_date.isoformat(), o.gateway_status,
            ])

    # --- bank_statement.csv ---------------------------------------------------
    # Build bank entries from orders with bank_credit_date
    # Split settlements produce ONE bank entry for the group
    bank_entries = []
    seen_splits = set()
    running_balance = 150000.00  # opening balance

    for idx, o in enumerate(orders):
        if o.is_pending or o.bank_credit_date is None:
            continue

        if o.is_split:
            if o.split_group_id in seen_splits:
                continue  # already wrote the combined entry
            seen_splits.add(o.split_group_id)

        amount = o.bank_amount
        running_balance = round(running_balance + amount, 2)
        # ~20% of normal entries get obfuscated narrations (no clean UTR),
        # plus all split settlements — forces tolerant/LLM layers to work
        should_obfuscate = o.is_split or (idx % 5 == 0 and not o.is_duplicate_amount)
        narration = _format_bank_narration(o, obfuscate=should_obfuscate)

        bank_entries.append({
            "txn_date": _format_date_messy(o.bank_credit_date, idx),
            "narration": narration,
            "amount": _format_amount_messy(amount, idx),
            "balance": _format_amount_messy(running_balance, idx),
            "value_date": _format_date_messy(
                o.bank_credit_date + timedelta(days=random.randint(0, 1)), idx + 1),
        })

    # Deliberate orphan bank credit (unidentified adhoc credit with no counterpart)
    bank_entries.append({
        "txn_date": _format_date_messy(START + timedelta(days=21), 99),
        "narration": "NEFT/UTIB9998887776/RAZORPAY ADHOC CREDIT/UNIDENTIFIED",
        "amount": _format_amount_messy(8450.00, 99),
        "balance": _format_amount_messy(running_balance + 8450.00, 99),
        "value_date": _format_date_messy(START + timedelta(days=21), 100),
    })

    # Sort bank entries by date (parse back to sort properly)
    bank_entries.sort(key=lambda e: e["txn_date"])

    with open(os.path.join(DATA_DIR, "bank_statement.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["txn_date", "narration", "amount", "balance", "value_date"])
        for entry in bank_entries:
            w.writerow([entry["txn_date"], entry["narration"],
                        entry["amount"], entry["balance"], entry["value_date"]])

    # --- internal_ledger.csv --------------------------------------------------
    with open(os.path.join(DATA_DIR, "internal_ledger.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["order_id", "customer_ref", "invoice_amount", "expected_amount",
                     "order_date", "channel", "status"])
        for o in orders:
            # Expected amount = invoice minus refund if partial
            expected = o.invoice_amount
            if o.is_partial_refund:
                expected = round(o.invoice_amount - o.refund_amount, 2)

            ledger_status = "completed"
            if o.is_pending:
                ledger_status = "pending"
            elif o.is_partial_refund:
                ledger_status = "partial_refund"
            elif o.gateway_status == "disputed":
                ledger_status = "disputed"

            w.writerow([
                o.order_id, o.customer_ref, o.invoice_amount, expected,
                o.order_date.isoformat(), o.channel, ledger_status,
            ])

    # --- ground_truth.csv (held out, never seen by matching engine) -----------
    with open(os.path.join(DATA_DIR, "ground_truth.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["order_id", "payment_id", "settlement_utr",
                     "expected_match_type", "expected_outcome"])
        for o in orders:
            if o.is_amount_mismatch:
                match_type = "mismatch"
                outcome = "AMOUNT_MISMATCH_BEYOND_TOLERANCE"
            elif o.is_pending:
                match_type = "pending"
                outcome = "PENDING_NOT_YET_SETTLED"
            elif o.is_split:
                match_type = "split"
                outcome = "matched_split"
            elif o.is_duplicate_amount:
                match_type = "duplicate"
                outcome = "matched_exact"
            elif o.is_partial_refund or o.gateway_status == "disputed":
                match_type = "partial_refund"
                outcome = "matched_tolerant"
            else:
                match_type = "exact"
                outcome = "matched_exact"
            w.writerow([o.order_id, o.payment_id, o.settlement_utr,
                        match_type, outcome])

    # --- pending_settlements.csv (for cash forecast) --------------------------
    pending = [o for o in orders if o.is_pending]
    with open(os.path.join(DATA_DIR, "pending_settlements.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["order_id", "payment_id", "net_amount",
                     "expected_settlement_date", "status"])
        for o in pending:
            w.writerow([o.order_id, o.payment_id, o.net_amount,
                        o.settlement_date.isoformat(), "pending"])

    # --- Summary --------------------------------------------------------------
    summary = {
        "total_orders": len(orders),
        "settled_orders": len(settled_orders),
        "pending_orders": len(pending),
        "split_groups": len(seen_splits),
        "partial_refunds": sum(1 for o in orders if o.is_partial_refund),
        "duplicate_amount_pairs": sum(1 for o in orders if o.is_duplicate_amount),
        "bank_entries": len(bank_entries),
        "date_range": f"{START.isoformat()} to {(START + timedelta(days=DAYS)).isoformat()}",
    }
    with open(os.path.join(DATA_DIR, "_summary.json"), "w") as f:
        json.dump(summary, f, indent=2)
    print("Generated data:\n" + json.dumps(summary, indent=2))


if __name__ == "__main__":
    write_all(build())
