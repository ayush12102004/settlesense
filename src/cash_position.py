"""Cash position rollup and forward projection.

From reconciled data + pending settlements, compute:
  - Total reconciled inflow (confirmed bank credits)
  - Total pending settlement (gateway records not yet banked)
  - 7-day and 14-day forward projection

The forecast is a deterministic rollup of known pending items, NOT a statistical
prediction — labeled as such throughout.
"""

from __future__ import annotations

import json
import os
from datetime import date, timedelta
from collections import defaultdict

from normalize import load_pending_settlements, parse_date
from reconcile import MatchResult

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")


def compute_cash_position(
    results: list[MatchResult],
    reference_date: date | None = None,
    lag_days: int = 0,
) -> dict:
    """Compute cash position from reconciliation results + pending settlements.

    Returns a dict with:
      - reconciled_inflow: total confirmed bank credits
      - pending_total: total pending settlements
      - projection_7d / projection_14d: expected inflow from pending
      - daily_projection: day-by-day breakdown for charting
      - simulated_lag_days: simulated settlement delay in days
    """
    if reference_date is None:
        # Use the latest bank date in results as reference
        bank_dates = [r.bank_date for r in results if r.bank_date]
        reference_date = max(bank_dates) if bank_dates else date.today()

    # Reconciled inflow = sum of all matched bank amounts
    reconciled_inflow = round(sum(
        r.bank_amount for r in results
        if r.status == "matched" and r.bank_amount > 0
    ), 2)

    # Pending settlements
    pending_raw = load_pending_settlements()
    pending_total = 0.0
    pending_by_date: dict[date, float] = defaultdict(float)

    for p in pending_raw:
        amount = float(p["net_amount"])
        pending_total += amount
        try:
            settle_date = parse_date(p["expected_settlement_date"]) + timedelta(days=lag_days)
        except ValueError:
            settle_date = reference_date + timedelta(days=3 + lag_days)
        pending_by_date[settle_date] += amount

    pending_total = round(pending_total, 2)

    # Build 14-day daily projection
    daily_projection = []
    cumulative = reconciled_inflow
    for day_offset in range(15):
        d = reference_date + timedelta(days=day_offset)
        inflow = round(pending_by_date.get(d, 0.0), 2)
        cumulative = round(cumulative + inflow, 2)
        daily_projection.append({
            "date": d.isoformat(),
            "day_label": f"Day {day_offset}" if day_offset > 0 else "Today",
            "expected_inflow": inflow,
            "cumulative_position": cumulative,
            "is_projected": day_offset > 0,
        })

    # 7-day and 14-day projections
    projection_7d = round(sum(
        pending_by_date.get(reference_date + timedelta(days=i), 0.0)
        for i in range(1, 8)
    ), 2)
    projection_14d = round(sum(
        pending_by_date.get(reference_date + timedelta(days=i), 0.0)
        for i in range(1, 15)
    ), 2)

    return {
        "reference_date": reference_date.isoformat(),
        "reconciled_inflow": reconciled_inflow,
        "pending_total": pending_total,
        "projection_7d": projection_7d,
        "projection_14d": projection_14d,
        "projected_position_7d": round(reconciled_inflow + projection_7d, 2),
        "projected_position_14d": round(reconciled_inflow + projection_14d, 2),
        "daily_projection": daily_projection,
        "simulated_lag_days": lag_days,
        "note": "Projection is a deterministic rollup of known pending settlements, not a statistical forecast.",
    }


if __name__ == "__main__":
    from reconcile import reconcile
    results = reconcile()
    position = compute_cash_position(results)
    print(json.dumps(position, indent=2))
