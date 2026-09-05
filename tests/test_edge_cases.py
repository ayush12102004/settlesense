"""Edge-case and rigor tests for SettleSense Reconciliation & Evaluation Engine.

Tests:
  1. Precision/Recall/F1 calculations against held-out ground truth
  2. Zero False Positive guardrail (no false matches accepted)
  3. Python arithmetic safety guardrail (rejects proposals exceeding tolerance)
  4. Rupee financial volume aggregations (Amount Reconciled & Amount at Risk)
  5. Multi-line 3-Way GSTR-2B Tax Reconciliation with Section 16(2)(aa) deferral
"""

import os
import sys
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "src"))

from reconcile import (
    AMOUNT_TOLERANCE,
    DATE_WINDOW_DAYS,
    ReasonCode,
    BankRecord,
    GatewayRecord,
    LedgerRecord,
    MatchResult,
    _try_exact_match,
    _try_tolerant_match,
    summarize,
)
from evaluate import _eval_run
from tax_matcher import compute_tax_reconciliation, SAC_CODE, RAZORPAY_GSTIN


def test_rupee_amount_aggregations_in_summary():
    """Verify summarize() computes correct rupee values for Reconciled and At-Risk cash."""
    results = [
        MatchResult(
            trace_id="TR-TEST-1", layer="exact", bank_date=date(2025, 6, 1),
            bank_narration="TEST 1", bank_amount=10500.50, bank_utr="UTR1",
            gateway_order_ids=["ord_1"], gateway_payment_ids=["pay_1"], gateway_utrs=["UTR1"],
            gateway_net_amounts=[10500.50], gateway_total_net=10500.50,
            ledger_order_ids=["ord_1"], ledger_expected_amounts=[10500.50],
            amount_diff=0.0, confidence=1.0, status="matched",
            reason_code=None, reason="Matched exact", suggested_step="None",
        ),
        MatchResult(
            trace_id="TR-TEST-2", layer="exception", bank_date=date(2025, 6, 2),
            bank_narration="ORPHAN CREDIT", bank_amount=4500.00, bank_utr=None,
            gateway_order_ids=[], gateway_payment_ids=[], gateway_utrs=[],
            gateway_net_amounts=[], gateway_total_net=None,
            ledger_order_ids=[], ledger_expected_amounts=[],
            amount_diff=None, confidence=None, status="exception",
            reason_code=ReasonCode.NO_CANDIDATE_IN_WINDOW,
            reason="Unidentified bank credit", suggested_step="Review bank statement",
        ),
        MatchResult(
            trace_id="TR-TEST-3", layer="exception", bank_date=None,
            bank_narration="", bank_amount=0.0, bank_utr=None,
            gateway_order_ids=["ord_pend"], gateway_payment_ids=[], gateway_utrs=[],
            gateway_net_amounts=[], gateway_total_net=None,
            ledger_order_ids=["ord_pend"], ledger_expected_amounts=[8200.00],
            amount_diff=None, confidence=None, status="exception",
            reason_code=ReasonCode.PENDING_NOT_YET_SETTLED,
            reason="Pending settlement", suggested_step="Await T+2 settlement",
        ),
    ]

    summary = summarize(results)
    assert summary["total_records"] == 3
    assert summary["total_matched"] == 1
    assert summary["amount_reconciled"] == 10500.50
    assert summary["amount_at_risk"] == 4500.00
    assert summary["pending_amount"] == 8200.00
    assert summary["pending_count"] == 1
    assert summary["match_rate"] == 0.5  # 1 matched / (3 total - 1 pending) = 50%


def test_ml_metrics_computation_and_zero_false_positives():
    """Verify Precision, Recall, and F1 calculation against held-out ground truth."""
    gt = [
        {"order_id": "ord_1", "expected_outcome": "matched_exact"},
        {"order_id": "ord_2", "expected_outcome": "matched_exact"},
        {"order_id": "ord_3", "expected_outcome": "AMOUNT_MISMATCH_BEYOND_TOLERANCE"},
        {"order_id": "ord_4", "expected_outcome": "PENDING_NOT_YET_SETTLED"},
    ]

    # Engine matched ord_1, but flagged ord_2, ord_3, ord_4 as exceptions
    results = [
        MatchResult(
            trace_id="TR-1", layer="exact", bank_date=date(2025, 6, 1),
            bank_narration="", bank_amount=100.0, bank_utr=None,
            gateway_order_ids=["ord_1"], gateway_payment_ids=[], gateway_utrs=[],
            gateway_net_amounts=[100.0], gateway_total_net=100.0,
            ledger_order_ids=["ord_1"], ledger_expected_amounts=[100.0],
            amount_diff=0.0, confidence=1.0, status="matched",
            reason_code=None, reason="", suggested_step="",
        ),
        MatchResult(
            trace_id="TR-2", layer="exception", bank_date=date(2025, 6, 2),
            bank_narration="", bank_amount=200.0, bank_utr=None,
            gateway_order_ids=["ord_2"], gateway_payment_ids=[], gateway_utrs=[],
            gateway_net_amounts=[], gateway_total_net=None,
            ledger_order_ids=["ord_2"], ledger_expected_amounts=[200.0],
            amount_diff=None, confidence=None, status="exception",
            reason_code=ReasonCode.NO_CANDIDATE_IN_WINDOW, reason="", suggested_step="",
        ),
        MatchResult(
            trace_id="TR-3", layer="exception", bank_date=date(2025, 6, 3),
            bank_narration="", bank_amount=300.0, bank_utr=None,
            gateway_order_ids=["ord_3"], gateway_payment_ids=[], gateway_utrs=[],
            gateway_net_amounts=[], gateway_total_net=None,
            ledger_order_ids=["ord_3"], ledger_expected_amounts=[300.0],
            amount_diff=None, confidence=None, status="exception",
            reason_code=ReasonCode.AMOUNT_MISMATCH_BEYOND_TOLERANCE, reason="", suggested_step="",
        ),
        MatchResult(
            trace_id="TR-4", layer="exception", bank_date=None,
            bank_narration="", bank_amount=0.0, bank_utr=None,
            gateway_order_ids=["ord_4"], gateway_payment_ids=[], gateway_utrs=[],
            gateway_net_amounts=[], gateway_total_net=None,
            ledger_order_ids=["ord_4"], ledger_expected_amounts=[400.0],
            amount_diff=None, confidence=None, status="exception",
            reason_code=ReasonCode.PENDING_NOT_YET_SETTLED, reason="", suggested_step="",
        ),
    ]

    metrics = _eval_run(results, gt)
    cm = metrics["confusion_matrix"]

    assert cm["true_positives"] == 1  # ord_1
    assert cm["false_positives"] == 0  # No non-matches matched!
    assert cm["false_negatives"] == 1  # ord_2 missed
    assert cm["true_negatives"] == 2   # ord_3 and ord_4 correctly flagged as exceptions

    # Precision = 1 / (1 + 0) = 1.0 (100%)
    assert metrics["precision"] == 1.0
    # Recall = 1 / (1 + 1) = 0.5 (50%)
    assert metrics["recall"] == 0.5
    # F1 = 2 * (1.0 * 0.5) / (1.0 + 0.5) = 2/3 = ~0.6667
    assert abs(metrics["f1_score"] - 0.6667) < 0.001


def test_python_arithmetic_guardrail_rejects_large_variance():
    """Verify engine will NOT match when variance exceeds tolerance, regardless of candidate match."""
    bank = BankRecord(
        txn_date=date(2025, 6, 10),
        narration="NEFT/RZP001/RAZORPAY SETTLEMENT",
        amount=5000.00,
        balance=100000.0,
        value_date=date(2025, 6, 10),
        extracted_utr="RZP001",
    )
    # Variance of ₹12 exceeds ₹5 tolerance
    gw = GatewayRecord(
        payment_id="pay_99",
        order_id="ord_99",
        gross_amount=5200.00,
        razorpay_fee=100.00,
        gst_on_fee=18.00,
        tax_deducted=0.0,
        net_amount=5012.00,
        settlement_utr="RZP001",
        settlement_date=date(2025, 6, 9),
        status="captured",
    )

    res = _try_exact_match(bank, {"RZP001": [gw]}, {}, set())
    # Exact match must fail and flag as exception because diff > 0.01
    assert res is not None
    assert res.status == "exception"
    assert res.reason_code == ReasonCode.AMOUNT_MISMATCH_BEYOND_TOLERANCE


def test_tax_reconciliation_multi_line_and_deferral():
    """Verify Section 16(2)(aa) timing lag handling and line item categorization."""
    res = compute_tax_reconciliation()
    assert res["tax_status"] == "MATCHED_ITC_ELIGIBLE"
    assert res["itc_claimable"] > 0
    assert res["total_itc_deferred"] == 36.00
    assert len(res["line_items"]) == 3

    # Check the deferred dispute line
    deferred_line = [l for l in res["line_items"] if l["itc_status"] == "DEFERRED_PENDING_FILING"][0]
    assert deferred_line["variance_gst"] == 36.00
    assert "Section 16(2)(aa)" in deferred_line["compliance_note"]
    assert "methodology_disclosure" in res
