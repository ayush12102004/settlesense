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
    """Score a reconciliation run against ground truth with ML metrics (Precision, Recall, F1)."""
    gt_by_order = {gt["order_id"]: gt for gt in ground_truth}
    expected_matches = {gt["order_id"] for gt in ground_truth if gt["expected_outcome"].startswith("matched")}
    expected_exceptions = {gt["order_id"] for gt in ground_truth if not gt["expected_outcome"].startswith("matched")}

    # Score each result
    total_evaluated = 0
    correct = 0
    by_layer_correct = {}
    by_layer_total = {}

    matched_orders: set[str] = set()
    exception_orders: set[str] = set()

    for r in results:
        if r.status == "matched":
            for order_id in r.gateway_order_ids:
                matched_orders.add(order_id)
                if order_id in gt_by_order:
                    total_evaluated += 1
                    gt_entry = gt_by_order[order_id]
                    expected_outcome = gt_entry["expected_outcome"]
                    is_correct = expected_outcome.startswith("matched")

                    layer = r.layer
                    by_layer_total[layer] = by_layer_total.get(layer, 0) + 1
                    if is_correct:
                        correct += 1
                        by_layer_correct[layer] = by_layer_correct.get(layer, 0) + 1

        elif r.status == "exception":
            for order_id in r.gateway_order_ids + r.ledger_order_ids:
                exception_orders.add(order_id)
                if order_id in gt_by_order:
                    total_evaluated += 1
                    gt_entry = gt_by_order[order_id]
                    if gt_entry["expected_outcome"] == r.reason_code or not gt_entry["expected_outcome"].startswith("matched"):
                        correct += 1

    # Confusion Matrix calculation
    # True Positives (TP): Expected to match AND matched by engine
    tp = matched_orders.intersection(expected_matches)
    # False Positives (FP): NOT expected to match BUT matched by engine (critical fintech risk!)
    fp = matched_orders.intersection(expected_exceptions)
    # False Negatives (FN): Expected to match BUT engine failed to match (flagged as exception or missing)
    fn = expected_matches.difference(matched_orders)
    # True Negatives (TN): Expected exceptions correctly flagged as exceptions
    tn = exception_orders.intersection(expected_exceptions)

    tp_count = len(tp)
    fp_count = len(fp)
    fn_count = len(fn)
    tn_count = len(tn)

    precision = round(tp_count / (tp_count + fp_count), 4) if (tp_count + fp_count) > 0 else 0.0
    recall = round(tp_count / (tp_count + fn_count), 4) if (tp_count + fn_count) > 0 else 0.0
    f1_score = round(2 * (precision * recall) / (precision + recall), 4) if (precision + recall) > 0 else 0.0
    specificity = round(tn_count / (tn_count + fp_count), 4) if (tn_count + fp_count) > 0 else 0.0

    # Exception reason code validity
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
        "precision": precision,
        "recall": recall,
        "f1_score": f1_score,
        "specificity": specificity,
        "auto_match_precision": precision,
        "auto_matched_count": len(matched_orders),
        "reason_code_coverage": reason_coverage,
        "confusion_matrix": {
            "true_positives": tp_count,
            "false_positives": fp_count,
            "false_negatives": fn_count,
            "true_negatives": tn_count,
        },
        "by_layer": layers,
    }


def main() -> None:
    import time
    ground_truth = load_ground_truth()
    print(f"Ground truth: {len(ground_truth)} records\n")

    # --- Run WITH LLM layer ---
    print("Running reconciliation WITH LLM layer...")
    start_with = time.perf_counter()
    results_with = reconcile(use_llm=True)
    elapsed_with = time.perf_counter() - start_with
    summary_with = summarize(results_with)
    eval_with = _eval_run(results_with, ground_truth)

    throughput_rps = round(summary_with["total_records"] / max(elapsed_with, 0.001), 1)

    # --- Run WITHOUT LLM layer (ablation) ---
    print("Running reconciliation WITHOUT LLM layer (ablation)...")
    start_without = time.perf_counter()
    results_without = reconcile(use_llm=False)
    elapsed_without = time.perf_counter() - start_without
    summary_without = summarize(results_without)
    eval_without = _eval_run(results_without, ground_truth)

    # --- Compute ablation delta ---
    llm_lift = round(eval_with["overall_accuracy"] - eval_without["overall_accuracy"], 4)
    match_rate_lift = round(summary_with["match_rate"] - summary_without["match_rate"], 4)
    precision_lift = round(eval_with["precision"] - eval_without["precision"], 4)
    recall_lift = round(eval_with["recall"] - eval_without["recall"], 4)
    f1_lift = round(eval_with["f1_score"] - eval_without["f1_score"], 4)

    from model import get_active_model_info
    model_info = get_active_model_info()

    # --- Build full report ---
    report = {
        "model": model_info["model_name"],
        "provider": model_info["provider"],
        "is_mock": model_info["is_mock"],
        "total_records_processed": summary_with["total_records"],
        "financial_amounts": {
            "amount_reconciled": summary_with.get("amount_reconciled", 0.0),
            "amount_at_risk": summary_with.get("amount_at_risk", 0.0),
            "pending_amount": summary_with.get("pending_amount", 0.0),
            "total_bank_inflow": summary_with.get("total_bank_inflow", 0.0),
        },
        "throughput": {
            "records_per_second": throughput_rps,
            "elapsed_seconds": round(elapsed_with, 3),
            "latency_per_record_ms": round((elapsed_with / max(summary_with["total_records"], 1)) * 1000, 2),
        },
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
            "precision_lift": precision_lift,
            "recall_lift": recall_lift,
            "f1_lift": f1_lift,
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
    print(f"  Throughput:          {throughput_rps} rec/sec ({elapsed_with:.2f}s total)")
    print(f"  Reconciled Inflow:   Rs.{summary_with.get('amount_reconciled', 0):,.2f}")
    print(f"  Amount at Risk:      Rs.{summary_with.get('amount_at_risk', 0):,.2f}")
    print(f"  (of which {summary_with['pending_count']} are pending — informational, not errors)")
    print(f"\n--- WITH LLM layer (Production) ---")
    print(f"  Match rate:          {summary_with['match_rate']:.1%}")
    print(f"  Precision:           {eval_with['precision']:.1%} (100% target: zero false matches)")
    print(f"  Recall:              {eval_with['recall']:.1%}")
    print(f"  F1 Score:            {eval_with['f1_score']:.1%}")
    print(f"  Matched by layer:    {summary_with['by_layer']}")
    print(f"  Exceptions:          {summary_with['total_exceptions']}")
    print(f"  Reason code coverage:{eval_with['reason_code_coverage']:.0%}")
    cm = eval_with.get("confusion_matrix", {})
    print(f"  Confusion Matrix:    TP={cm.get('true_positives')} | FP={cm.get('false_positives')} | FN={cm.get('false_negatives')} | TN={cm.get('true_negatives')}")

    print(f"\n--- WITHOUT LLM layer (Ablation Baseline) ---")
    print(f"  Match rate:          {summary_without['match_rate']:.1%}")
    print(f"  Precision:           {eval_without['precision']:.1%}")
    print(f"  Recall:              {eval_without['recall']:.1%}")
    print(f"  F1 Score:            {eval_without['f1_score']:.1%}")
    print(f"  Matched by layer:    {summary_without['by_layer']}")

    print(f"\n--- MEASURED AI LIFT (Ablation Proof) ---")
    print(f"  Match rate lift:     {match_rate_lift:+.1%}")
    print(f"  Recall lift:         {recall_lift:+.1%}")
    print(f"  F1 Score lift:       {f1_lift:+.1%}")
    print(f"  Records resolved by LLM: "
          f"{summary_with['total_matched'] - summary_without['total_matched']}")
    print("=" * 60)
    print(f"\nFull report written to {out_path}")


if __name__ == "__main__":
    main()
