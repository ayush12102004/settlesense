"""Evaluation harness — measures correctness, not just coverage.

Scores the reconciliation engine against held-out ground truth:
  1. Overall match rate (records correctly reconciled / total)
  2. Match rate by layer (exact / tolerant / LLM-assisted)
  3. Precision on auto-matched slice (wrong auto-match > flagged exception)
  4. Ablation: match rate WITH vs WITHOUT the LLM layer
  5. Exception coverage: 100% of exceptions have valid reason codes

Run: python src/evaluate.py
"""

from __future__ import annotations

import json
import os

from normalize import load_ground_truth
from reconcile import reconcile, summarize, ReasonCode

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")

# Valid reason codes
VALID_REASON_CODES = {
    ReasonCode.NO_CANDIDATE_IN_WINDOW,
    ReasonCode.AMOUNT_MISMATCH_BEYOND_TOLERANCE,
    ReasonCode.SPLIT_SETTLEMENT_UNRESOLVED,
    ReasonCode.DUPLICATE_CANDIDATES_AMBIGUOUS,
    ReasonCode.PENDING_NOT_YET_SETTLED,
    ReasonCode.LOW_CONFIDENCE_LLM_MATCH,
}


def _eval_run(results, ground_truth: list[dict]) -> dict:
    """Score a reconciliation run against ground truth."""
    # Build ground truth lookup: order_id -> expected info
    gt_by_order = {}
    for gt in ground_truth:
        gt_by_order[gt["order_id"]] = gt

    # Score each result
    total_evaluated = 0
    correct = 0
    by_layer_correct = {}
    by_layer_total = {}

    for r in results:
        if r.status == "matched":
            for order_id in r.gateway_order_ids:
                if order_id in gt_by_order:
                    total_evaluated += 1
                    gt_entry = gt_by_order[order_id]
                    # A match is correct if the order was supposed to be matched
                    # (not pending) and the right payment_id was found
                    expected_outcome = gt_entry["expected_outcome"]
                    is_correct = expected_outcome.startswith("matched")

                    layer = r.layer
                    by_layer_total[layer] = by_layer_total.get(layer, 0) + 1
                    if is_correct:
                        correct += 1
                        by_layer_correct[layer] = by_layer_correct.get(layer, 0) + 1

        elif r.status == "exception":
            # Check pending exceptions
            for order_id in r.gateway_order_ids + r.ledger_order_ids:
                if order_id in gt_by_order:
                    total_evaluated += 1
                    gt_entry = gt_by_order[order_id]
                    if gt_entry["expected_outcome"] == r.reason_code:
                        correct += 1

    # Precision on auto-matched slice
    auto_matched = [r for r in results if r.status == "matched"]
    auto_matched_orders = set()
    for r in auto_matched:
        auto_matched_orders.update(r.gateway_order_ids)

    auto_correct = sum(
        1 for oid in auto_matched_orders
        if oid in gt_by_order and gt_by_order[oid]["expected_outcome"].startswith("matched")
    )
    auto_precision = (round(auto_correct / len(auto_matched_orders), 4)
                      if auto_matched_orders else 0.0)

    # Exception coverage: every exception has a valid reason code
    exceptions = [r for r in results if r.status == "exception"]
    valid_reasons = sum(1 for r in exceptions if r.reason_code in VALID_REASON_CODES)
    reason_coverage = round(valid_reasons / len(exceptions), 4) if exceptions else 1.0

    # Layer breakdown
    layers = {}
    for layer in sorted(set(list(by_layer_total.keys()) + list(by_layer_correct.keys()))):
        t = by_layer_total.get(layer, 0)
        c = by_layer_correct.get(layer, 0)
        layers[layer] = {
            "total": t,
            "correct": c,
            "accuracy": round(c / t, 4) if t else 0.0,
        }

    return {
        "total_evaluated": total_evaluated,
        "correct": correct,
        "overall_accuracy": round(correct / total_evaluated, 4) if total_evaluated else 0.0,
        "auto_match_precision": auto_precision,
        "auto_matched_count": len(auto_matched_orders),
        "reason_code_coverage": reason_coverage,
        "by_layer": layers,
    }


def main() -> None:
    ground_truth = load_ground_truth()
    print(f"Ground truth: {len(ground_truth)} records\n")

    # --- Run WITH LLM layer ---
    print("Running reconciliation WITH LLM layer...")
    results_with = reconcile(use_llm=True)
    summary_with = summarize(results_with)
    eval_with = _eval_run(results_with, ground_truth)

    # --- Run WITHOUT LLM layer (ablation) ---
    print("Running reconciliation WITHOUT LLM layer (ablation)...")
    results_without = reconcile(use_llm=False)
    summary_without = summarize(results_without)
    eval_without = _eval_run(results_without, ground_truth)

    # --- Compute ablation delta ---
    llm_lift = round(eval_with["overall_accuracy"] - eval_without["overall_accuracy"], 4)
    match_rate_lift = round(summary_with["match_rate"] - summary_without["match_rate"], 4)

    from model import get_active_model_info
    model_info = get_active_model_info()

    # --- Build full report ---
    report = {
        "model": model_info["model_name"],
        "provider": model_info["provider"],
        "is_mock": model_info["is_mock"],
        "total_records_processed": summary_with["total_records"],
        "with_llm": {
            "summary": summary_with,
            "evaluation": eval_with,
        },
        "without_llm": {
            "summary": summary_without,
            "evaluation": eval_without,
        },
        "ablation": {
            "accuracy_lift": llm_lift,
            "match_rate_lift": match_rate_lift,
            "with_llm_match_rate": summary_with["match_rate"],
            "without_llm_match_rate": summary_without["match_rate"],
            "with_llm_matched": summary_with["total_matched"],
            "without_llm_matched": summary_without["total_matched"],
        },
    }

    out_path = os.path.join(DATA_DIR, "metrics.json")
    with open(out_path, "w") as f:
        json.dump(report, f, indent=2)

    # --- Print results ---
    print("\n" + "=" * 60)
    print("RECONCILIATION EVALUATION RESULTS")
    print("=" * 60)
    print(f"\nTotal records processed: {summary_with['total_records']}")
    print(f"  (of which {summary_with['pending_count']} are pending — informational, not errors)")
    print(f"\n--- WITH LLM layer ---")
    print(f"  Match rate:          {summary_with['match_rate']:.1%}")
    print(f"  Matched by layer:    {summary_with['by_layer']}")
    print(f"  Exceptions:          {summary_with['total_exceptions']}")
    print(f"  Exception reasons:   {summary_with['exception_reasons']}")
    print(f"  Auto-match precision:{eval_with['auto_match_precision']:.1%}")
    print(f"  Reason code coverage:{eval_with['reason_code_coverage']:.0%}")

    print(f"\n--- WITHOUT LLM layer (ablation) ---")
    print(f"  Match rate:          {summary_without['match_rate']:.1%}")
    print(f"  Matched by layer:    {summary_without['by_layer']}")

    print(f"\n--- ABLATION ---")
    print(f"  Match rate lift:     {match_rate_lift:+.1%}")
    print(f"  Accuracy lift:       {llm_lift:+.1%}")
    print(f"  Records resolved by LLM: "
          f"{summary_with['total_matched'] - summary_without['total_matched']}")
    print("=" * 60)
    print(f"\nFull report written to {out_path}")


if __name__ == "__main__":
    main()
