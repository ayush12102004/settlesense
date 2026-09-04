"""Main orchestrator — single entry point for the full pipeline.

Usage:
  python src/main.py              # Generate data + reconcile + evaluate + export
  python src/main.py --serve      # Also start the dashboard server
  python src/main.py --skip-gen   # Skip data generation (use existing data)
"""

from __future__ import annotations

import json
import os
import sys

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")


def run_pipeline(skip_generate: bool = False) -> dict:
    """Run the full reconciliation pipeline and return all results."""

    # Step 1: Generate data
    if not skip_generate:
        print("=" * 60)
        print("STEP 1: Generating synthetic data...")
        print("=" * 60)
        from generate_data import build, write_all
        write_all(build())
    else:
        print("Skipping data generation (using existing data)")

    # Step 2: Reconcile
    print("\n" + "=" * 60)
    print("STEP 2: Running reconciliation engine...")
    print("=" * 60)
    from reconcile import reconcile, summarize
    results = reconcile(use_llm=True)
    summary = summarize(results)
    print(f"  Matched: {summary['total_matched']} / {summary['total_records']}")
    print(f"  Match rate: {summary['match_rate']:.1%}")
    print(f"  By layer: {summary['by_layer']}")

    # Step 3: Evaluate
    print("\n" + "=" * 60)
    print("STEP 3: Running evaluation harness...")
    print("=" * 60)
    from evaluate import main as eval_main
    eval_main()

    # Step 4: Cash position
    print("\n" + "=" * 60)
    print("STEP 4: Computing cash position...")
    print("=" * 60)
    from cash_position import compute_cash_position
    cash = compute_cash_position(results)
    cash_path = os.path.join(DATA_DIR, "cash_position.json")
    with open(cash_path, "w") as f:
        json.dump(cash, f, indent=2)
    print(f"  Reconciled inflow: Rs.{cash['reconciled_inflow']:,.2f}")
    print(f"  Pending:           Rs.{cash['pending_total']:,.2f}")
    print(f"  7-day projection:  Rs.{cash['projected_position_7d']:,.2f}")
    print(f"  14-day projection: Rs.{cash['projected_position_14d']:,.2f}")

    # Step 5: Audit trail
    print("\n" + "=" * 60)
    print("STEP 5: Exporting audit trail...")
    print("=" * 60)
    from audit import build_audit_trail, export_json, export_csv
    audit_trail = build_audit_trail(results)
    json_path = export_json(audit_trail)
    csv_path = export_csv(audit_trail)
    print(f"  {len(audit_trail)} records exported")
    print(f"  JSON: {json_path}")
    print(f"  CSV:  {csv_path}")

    # Step 6: Reconcile Tax Invoices & GSTR-2B ITC
    print("\n" + "=" * 60)
    print("STEP 6: Reconciling Tax Invoices & GSTR-2B ITC...")
    print("=" * 60)
    from tax_matcher import compute_tax_reconciliation
    tax_summary = compute_tax_reconciliation(results)
    print(f"  Tax Status:   {tax_summary['tax_status']}")
    print(f"  Eligible ITC: Rs.{tax_summary['itc_claimable']:,.2f} (SAC {tax_summary['sac_code']})")

    # Step 7: Build dashboard data bundle
    print("\n" + "=" * 60)
    print("STEP 7: Building dashboard data bundle...")
    print("=" * 60)

    # Build results data for the frontend
    matches = []
    exceptions = []
    for r in results:
        record = {
            "trace_id": r.trace_id,
            "layer": r.layer,
            "status": r.status,
            "bank_date": r.bank_date.isoformat() if r.bank_date else None,
            "bank_narration": r.bank_narration,
            "bank_amount": r.bank_amount,
            "bank_utr": r.bank_utr,
            "gateway_order_ids": r.gateway_order_ids,
            "gateway_payment_ids": r.gateway_payment_ids,
            "gateway_utrs": r.gateway_utrs,
            "gateway_net_amounts": r.gateway_net_amounts,
            "gateway_total_net": r.gateway_total_net,
            "ledger_order_ids": r.ledger_order_ids,
            "ledger_expected_amounts": r.ledger_expected_amounts,
            "amount_diff": r.amount_diff,
            "confidence": r.confidence,
            "reason_code": r.reason_code,
            "reason": r.reason,
            "suggested_step": r.suggested_step,
        }
        if r.status == "matched":
            matches.append(record)
        else:
            exceptions.append(record)

    dashboard_data = {
        "summary": summary,
        "cash_position": cash,
        "tax_reconciliation": tax_summary,
        "matches": matches,
        "exceptions": exceptions,
        "audit_trail": audit_trail,
        "metrics": json.load(open(os.path.join(DATA_DIR, "metrics.json"))),
    }

    bundle_path = os.path.join(DATA_DIR, "dashboard_data.json")
    with open(bundle_path, "w", encoding="utf-8") as f:
        json.dump(dashboard_data, f, indent=2, ensure_ascii=False)
    print(f"  Dashboard data bundle: {bundle_path}")

    print("\n" + "=" * 60)
    print("PIPELINE COMPLETE")
    print("=" * 60)

    return dashboard_data


if __name__ == "__main__":
    skip_gen = "--skip-gen" in sys.argv
    serve = "--serve" in sys.argv

    run_pipeline(skip_generate=skip_gen)

    if serve:
        print("\nStarting dashboard server...")
        from api import create_app
        app = create_app()
        app.run(host="0.0.0.0", port=5000, debug=False)
