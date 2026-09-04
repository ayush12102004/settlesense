"""Audit trail — every reconciliation decision is traceable.

Every match and every exception gets:
  - trace_id (unique identifier)
  - layer (exact / tolerant / llm_assisted / exception)
  - records_compared (specific records from each source)
  - confidence (if LLM-assisted)
  - reason (human-readable explanation)
  - timestamp

Exportable as JSON and CSV. Queryable by trace_id or order_id.
"""

from __future__ import annotations

import csv
import json
import os
from datetime import datetime

from reconcile import MatchResult

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")


def _result_to_audit_record(r: MatchResult) -> dict:
    """Convert a MatchResult to a flat audit trail record."""
    return {
        "trace_id": r.trace_id,
        "timestamp": datetime.now().isoformat(),
        "layer": r.layer,
        "status": r.status,
        # Bank side
        "bank_date": r.bank_date.isoformat() if r.bank_date else None,
        "bank_narration": r.bank_narration,
        "bank_amount": r.bank_amount,
        "bank_utr": r.bank_utr,
        # Gateway side
        "gateway_order_ids": r.gateway_order_ids,
        "gateway_payment_ids": r.gateway_payment_ids,
        "gateway_utrs": r.gateway_utrs,
        "gateway_net_amounts": r.gateway_net_amounts,
        "gateway_total_net": r.gateway_total_net,
        # Ledger side
        "ledger_order_ids": r.ledger_order_ids,
        "ledger_expected_amounts": r.ledger_expected_amounts,
        # Match quality
        "amount_diff": r.amount_diff,
        "confidence": r.confidence,
        # Decision
        "reason_code": r.reason_code,
        "reason": r.reason,
        "suggested_step": r.suggested_step,
    }


def build_audit_trail(results: list[MatchResult]) -> list[dict]:
    """Build a full audit trail from reconciliation results."""
    return [_result_to_audit_record(r) for r in results]


def export_json(audit_trail: list[dict], path: str | None = None) -> str:
    """Export audit trail as JSON."""
    if path is None:
        path = os.path.join(DATA_DIR, "audit_trail.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(audit_trail, f, indent=2, ensure_ascii=False)
    return path


def export_csv(audit_trail: list[dict], path: str | None = None) -> str:
    """Export audit trail as CSV (flattened for spreadsheet use)."""
    if path is None:
        path = os.path.join(DATA_DIR, "audit_trail.csv")

    # Flatten list fields to pipe-separated strings for CSV
    rows = []
    for record in audit_trail:
        flat = dict(record)
        for key in ["gateway_order_ids", "gateway_payment_ids", "gateway_utrs",
                     "gateway_net_amounts", "ledger_order_ids", "ledger_expected_amounts"]:
            val = flat.get(key)
            if isinstance(val, list):
                flat[key] = " | ".join(str(v) for v in val)
        rows.append(flat)

    if rows:
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=rows[0].keys())
            writer.writeheader()
            writer.writerows(rows)
    return path


def query_by_trace_id(audit_trail: list[dict], trace_id: str) -> dict | None:
    """Find a single audit record by trace_id."""
    for record in audit_trail:
        if record["trace_id"] == trace_id:
            return record
    return None


def query_by_order_id(audit_trail: list[dict], order_id: str) -> list[dict]:
    """Find all audit records involving a given order_id."""
    return [
        record for record in audit_trail
        if order_id in record.get("gateway_order_ids", [])
        or order_id in record.get("ledger_order_ids", [])
    ]


if __name__ == "__main__":
    from reconcile import reconcile
    results = reconcile()
    trail = build_audit_trail(results)
    json_path = export_json(trail)
    csv_path = export_csv(trail)
    print(f"Audit trail: {len(trail)} records")
    print(f"  JSON: {json_path}")
    print(f"  CSV:  {csv_path}")
    print(f"\nSample record:")
    print(json.dumps(trail[0], indent=2, ensure_ascii=False))
