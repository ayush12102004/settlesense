"""Unit tests for the Tax-Line and GSTR-2B ITC Matcher."""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "src"))

from tax_matcher import compute_tax_reconciliation, RAZORPAY_GSTIN, SAC_CODE


def test_tax_reconciliation_calculation():
    """Verify that tax reconciliation generates ITC eligibility with proper SAC codes."""
    res = compute_tax_reconciliation()
    assert res["tax_status"] == "MATCHED_ITC_ELIGIBLE"
    assert res["itc_claimable"] > 0
    assert res["sac_code"] == SAC_CODE
    assert res["vendor_gstin"] == RAZORPAY_GSTIN
    assert res["reconciliation"]["itc_eligible"] is True
    assert res["reconciliation"]["variance_gst"] == 0.0
