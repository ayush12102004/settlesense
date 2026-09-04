"""Unit tests for the SettleSense reconciliation engine."""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "src"))

from datetime import date
from reconcile import (
    AMOUNT_TOLERANCE,
    ReasonCode,
    _try_exact_match,
    reconcile,
    summarize,
    BankRecord,
    GatewayRecord,
    LedgerRecord,
)


def test_amount_tolerance_boundary():
    """Verify exact tolerance boundary rule."""
    assert AMOUNT_TOLERANCE == 5.00


def test_reconciliation_runs_cleanly():
    """Verify that reconcile() processes records and produces valid output."""
    results = reconcile(use_llm=False)
    assert len(results) >= 50, "Must process at least 50 records per hackathon bar"
    summary = summarize(results)
    assert summary["match_rate"] > 0.85, "Baseline match rate should be high"
    assert summary["total_records"] == len(results)


def test_exact_match_to_the_paisa():
    """Verify exact matching strictly respects the paisa."""
    bank = BankRecord(
        txn_date=date(2025, 6, 15),
        narration="NEFT/UTIB0001234567/RAZORPAY SOFTWARE PVT LTD",
        amount=4890.50,
        balance=150000.0,
        value_date=date(2025, 6, 15),
        extracted_utr="UTIB0001234567",
    )
    gw = GatewayRecord(
        payment_id="pay_test_001",
        order_id="order_test_001",
        gross_amount=5000.00,
        razorpay_fee=100.00,
        gst_on_fee=18.00,
        tax_deducted=0.0,
        net_amount=4890.50,
        settlement_utr="UTIB0001234567",
        settlement_date=date(2025, 6, 14),
        status="captured",
    )
    gw_by_utr = {"UTIB0001234567": [gw]}
    ledger_by_order = {}
    claimed = set()

    res = _try_exact_match(bank, gw_by_utr, ledger_by_order, claimed)
    assert res is not None
    assert res.status == "matched"
    assert res.layer == "exact"
    assert res.amount_diff == 0.0


def test_amount_mismatch_beyond_tolerance_rejected():
    """Verify that arithmetic variance beyond tolerance is rejected even with matching UTR."""
    bank = BankRecord(
        txn_date=date(2025, 6, 15),
        narration="NEFT/UTIB0001234567/RAZORPAY SOFTWARE PVT LTD",
        amount=4640.50,  # 250 variance from gateway net
        balance=150000.0,
        value_date=date(2025, 6, 15),
        extracted_utr="UTIB0001234567",
    )
    gw = GatewayRecord(
        payment_id="pay_test_001",
        order_id="order_test_001",
        gross_amount=5000.00,
        razorpay_fee=100.00,
        gst_on_fee=18.00,
        tax_deducted=0.0,
        net_amount=4890.50,
        settlement_utr="UTIB0001234567",
        settlement_date=date(2025, 6, 14),
        status="disputed",
    )
    gw_by_utr = {"UTIB0001234567": [gw]}
    ledger_by_order = {}
    claimed = set()

    res = _try_exact_match(bank, gw_by_utr, ledger_by_order, claimed)
    assert res is not None
    assert res.status == "exception"
    assert res.reason_code == ReasonCode.AMOUNT_MISMATCH_BEYOND_TOLERANCE
