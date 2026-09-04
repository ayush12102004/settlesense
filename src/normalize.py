"""Ingestion & normalization layer.

One function per source. Each parses its source's specific quirks into a
unified CanonicalRecord so the matching engine works on one schema.

Handles:
  - UTR extraction from bank narration via regex
  - ₹/INR/comma amount parsing
  - Mixed date format normalization (DD/MM/YYYY, YYYY-MM-DD, DD-Mon-YYYY)
  - Fee/GST unbundling from gateway records
  - Paisa-precision arithmetic (no rounding surprises)
"""

from __future__ import annotations

import csv
import os
import re
from dataclasses import dataclass, field
from datetime import date, datetime

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")


@dataclass
class GatewayRecord:
    """Normalized gateway settlement record."""
    payment_id: str
    order_id: str
    gross_amount: float
    razorpay_fee: float
    gst_on_fee: float
    tax_deducted: float
    net_amount: float
    settlement_utr: str
    settlement_date: date
    status: str  # captured/refunded/partial_refund/disputed

    @property
    def computed_net(self) -> float:
        """Recompute net from components — never trust a pre-computed net."""
        return round(self.gross_amount - self.razorpay_fee
                     - self.gst_on_fee - self.tax_deducted, 2)


@dataclass
class BankRecord:
    """Normalized bank statement record."""
    txn_date: date
    narration: str
    amount: float
    balance: float
    value_date: date
    extracted_utr: str | None  # parsed from narration


@dataclass
class LedgerRecord:
    """Normalized internal ledger record."""
    order_id: str
    customer_ref: str
    invoice_amount: float
    expected_amount: float
    order_date: date
    channel: str
    status: str  # completed/pending/partial_refund/disputed


# --- Date parsing -------------------------------------------------------------

_DATE_FORMATS = [
    "%d/%m/%Y",      # DD/MM/YYYY
    "%Y-%m-%d",      # ISO
    "%d-%b-%Y",      # 15-Jun-2025
    "%m/%d/%Y",      # MM/DD/YYYY (fallback)
    "%d-%m-%Y",      # DD-MM-YYYY
]


def parse_date(s: str) -> date:
    """Parse a date string, trying multiple common formats."""
    s = s.strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"Unparseable date: {s!r}")


# --- Amount parsing -----------------------------------------------------------

def parse_amount(s: str) -> float:
    """Parse '₹1,234.56' / 'INR 1234.56' / '1,234.56' / '1234.56' to float.

    Always returns paisa-precision (2 decimal places).
    """
    s = s.strip()
    # Remove currency symbols and prefixes
    s = s.replace("₹", "").replace("INR", "").replace("Rs.", "").replace("Rs", "")
    # Remove commas
    s = s.replace(",", "")
    s = s.strip()
    return round(float(s), 2) if s else 0.0


# --- UTR extraction from bank narration ---------------------------------------

# Real bank narrations embed UTRs in various formats:
#   NEFT/UTIB0001234567890/RAZORPAY...
#   NEFT-HDFC0009876543210-RAZORPAY...
#   NEFT CR-SBIN0001111222233-RAZORPAY...

_UTR_PATTERN = re.compile(r'(UTIB|HDFC|ICIC|SBIN|KKBK|BARB)\d{10,}')
_GENERIC_UTR = re.compile(r'[A-Z]{4}\d{10,}')


def extract_utr(narration: str) -> str | None:
    """Extract a UTR number from a messy bank narration string."""
    # Try known bank prefixes first
    match = _UTR_PATTERN.search(narration)
    if match:
        return match.group(0)
    # Fall back to any XXXX followed by 10+ digits
    match = _GENERIC_UTR.search(narration)
    if match:
        return match.group(0)
    return None


# --- Loaders ------------------------------------------------------------------

def load_gateway() -> list[GatewayRecord]:
    """Parse gateway_settlement.csv into normalized records."""
    path = os.path.join(DATA_DIR, "gateway_settlement.csv")
    records = []
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            rec = GatewayRecord(
                payment_id=row["payment_id"].strip(),
                order_id=row["order_id"].strip(),
                gross_amount=parse_amount(row["gross_amount"]),
                razorpay_fee=parse_amount(row["razorpay_fee"]),
                gst_on_fee=parse_amount(row["gst_on_fee"]),
                tax_deducted=parse_amount(row["tax_deducted"]),
                net_amount=parse_amount(row["net_amount"]),
                settlement_utr=row["settlement_utr"].strip(),
                settlement_date=parse_date(row["settlement_date"]),
                status=row["status"].strip(),
            )
            # Verify net computation matches
            if abs(rec.net_amount - rec.computed_net) > 0.02:
                rec.net_amount = rec.computed_net  # trust computed over pre-stated
            records.append(rec)
    return records


def load_bank_statement() -> list[BankRecord]:
    """Parse bank_statement.csv into normalized records, extracting UTRs."""
    path = os.path.join(DATA_DIR, "bank_statement.csv")
    records = []
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            narration = row["narration"].strip()
            records.append(BankRecord(
                txn_date=parse_date(row["txn_date"]),
                narration=narration,
                amount=parse_amount(row["amount"]),
                balance=parse_amount(row["balance"]),
                value_date=parse_date(row["value_date"]),
                extracted_utr=extract_utr(narration),
            ))
    return records


def load_internal_ledger() -> list[LedgerRecord]:
    """Parse internal_ledger.csv into normalized records."""
    path = os.path.join(DATA_DIR, "internal_ledger.csv")
    records = []
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            records.append(LedgerRecord(
                order_id=row["order_id"].strip(),
                customer_ref=row["customer_ref"].strip(),
                invoice_amount=parse_amount(row["invoice_amount"]),
                expected_amount=parse_amount(row["expected_amount"]),
                order_date=parse_date(row["order_date"]),
                channel=row["channel"].strip(),
                status=row["status"].strip(),
            ))
    return records


def load_ground_truth() -> list[dict]:
    """Load held-out ground truth (only used by evaluate.py)."""
    path = os.path.join(DATA_DIR, "ground_truth.csv")
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def load_pending_settlements() -> list[dict]:
    """Load pending settlements for cash position forecast."""
    path = os.path.join(DATA_DIR, "pending_settlements.csv")
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


if __name__ == "__main__":
    gw = load_gateway()
    bank = load_bank_statement()
    ledger = load_internal_ledger()
    gt = load_ground_truth()
    print(f"Gateway records:  {len(gw)}")
    print(f"Bank records:     {len(bank)}")
    print(f"Ledger records:   {len(ledger)}")
    print(f"Ground truth:     {len(gt)}")
    print(f"\nSample gateway: {gw[0]}")
    print(f"Sample bank:    narration={bank[0].narration!r}  utr={bank[0].extracted_utr}")
    print(f"Sample ledger:  {ledger[0]}")
