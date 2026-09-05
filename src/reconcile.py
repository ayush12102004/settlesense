"""Three-layer reconciliation engine.

Layer 1 — Exact match: UTR + amount to the paisa.
Layer 2 — Tolerant match: amount within tolerance + date window + fuzzy string.
Layer 3 — LLM-assisted match: narration analysis for ambiguous cases; the LLM
          proposes, deterministic code re-verifies arithmetic before accepting.

The LLM never touches a number. It labels, suggests, and explains.
Python computes and verifies. This separation is non-negotiable.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date, timedelta

from normalize import (
    GatewayRecord, BankRecord, LedgerRecord,
    load_gateway, load_bank_statement, load_internal_ledger,
)

# Attempt rapidfuzz import; fall back to basic ratio if unavailable
try:
    from rapidfuzz import fuzz as _fuzz
    def fuzzy_ratio(a: str, b: str) -> float:
        return _fuzz.ratio(a, b) / 100.0
except ImportError:
    def fuzzy_ratio(a: str, b: str) -> float:
        """Simple character-level similarity fallback."""
        if not a or not b:
            return 0.0
        common = sum(1 for c in a if c in b)
        return common / max(len(a), len(b))


# --- Configuration ------------------------------------------------------------

AMOUNT_TOLERANCE = 5.00      # ₹ — covers rounding across sources
DATE_WINDOW_DAYS = 5         # max settlement lag we consider
FUZZY_THRESHOLD = 0.60       # minimum string similarity for tolerant match
LLM_CONFIDENCE_THRESHOLD = 0.70  # below this, LLM match becomes an exception


# --- Reason codes (PRD §5.3) -------------------------------------------------

class ReasonCode:
    NO_CANDIDATE_IN_WINDOW = "NO_CANDIDATE_IN_WINDOW"
    AMOUNT_MISMATCH_BEYOND_TOLERANCE = "AMOUNT_MISMATCH_BEYOND_TOLERANCE"
    SPLIT_SETTLEMENT_UNRESOLVED = "SPLIT_SETTLEMENT_UNRESOLVED"
    DUPLICATE_CANDIDATES_AMBIGUOUS = "DUPLICATE_CANDIDATES_AMBIGUOUS"
    PENDING_NOT_YET_SETTLED = "PENDING_NOT_YET_SETTLED"
    LOW_CONFIDENCE_LLM_MATCH = "LOW_CONFIDENCE_LLM_MATCH"

# Human-readable reason messages
_REASON_MESSAGES = {
    ReasonCode.NO_CANDIDATE_IN_WINDOW:
        "No gateway record found within ₹{tol} and {days}-day window",
    ReasonCode.AMOUNT_MISMATCH_BEYOND_TOLERANCE:
        "UTR matched but amount differs by ₹{diff} (beyond ₹{tol} tolerance)",
    ReasonCode.SPLIT_SETTLEMENT_UNRESOLVED:
        "Suspected split settlement — bank credit may cover multiple orders, unresolved",
    ReasonCode.DUPLICATE_CANDIDATES_AMBIGUOUS:
        "{n} equally-plausible candidates found (same amount, overlapping dates)",
    ReasonCode.PENDING_NOT_YET_SETTLED:
        "Order exists in ledger but no settlement yet — still in pipeline",
    ReasonCode.LOW_CONFIDENCE_LLM_MATCH:
        "AI proposed a match (confidence {conf:.0%}) but below {threshold:.0%} threshold",
}

# Suggested next steps for each exception type
_SUGGESTED_STEPS = {
    ReasonCode.NO_CANDIDATE_IN_WINDOW:
        "Check gateway dashboard for settlement status of this order",
    ReasonCode.AMOUNT_MISMATCH_BEYOND_TOLERANCE:
        "Verify fee computation or check for partial refund not reflected in gateway",
    ReasonCode.SPLIT_SETTLEMENT_UNRESOLVED:
        "Check gateway dashboard for a second linked order in this settlement batch",
    ReasonCode.DUPLICATE_CANDIDATES_AMBIGUOUS:
        "Cross-reference customer_ref or payment_id in the internal ledger to disambiguate",
    ReasonCode.PENDING_NOT_YET_SETTLED:
        "No action needed — settlement expected within normal processing window",
    ReasonCode.LOW_CONFIDENCE_LLM_MATCH:
        "Review the AI's proposed match manually — narration may contain non-standard format",
}


@dataclass
class MatchResult:
    """One reconciliation decision — match or exception."""
    trace_id: str
    layer: str       # exact / tolerant / llm_assisted / exception
    # Bank side
    bank_date: date | None
    bank_narration: str
    bank_amount: float
    bank_utr: str | None
    # Gateway side
    gateway_order_ids: list[str]
    gateway_payment_ids: list[str]
    gateway_utrs: list[str]
    gateway_net_amounts: list[float]
    gateway_total_net: float | None
    # Ledger side
    ledger_order_ids: list[str]
    ledger_expected_amounts: list[float]
    # Match quality
    amount_diff: float | None
    confidence: float | None
    # Status
    status: str      # matched / exception
    reason_code: str | None
    reason: str
    suggested_step: str
    # Metadata
    records_compared: dict = field(default_factory=dict)


def _trace() -> str:
    return f"TR-{uuid.uuid4().hex[:12].upper()}"


def _date_in_window(d1: date, d2: date, window: int = DATE_WINDOW_DAYS) -> bool:
    return abs((d1 - d2).days) <= window


# --- Build lookup indices -----------------------------------------------------

def _build_gateway_by_utr(gw: list[GatewayRecord]) -> dict[str, list[GatewayRecord]]:
    idx: dict[str, list[GatewayRecord]] = {}
    for g in gw:
        if g.settlement_utr:
            idx.setdefault(g.settlement_utr, []).append(g)
    return idx


def _build_gateway_by_order(gw: list[GatewayRecord]) -> dict[str, GatewayRecord]:
    return {g.order_id: g for g in gw}


def _build_ledger_by_order(ledger: list[LedgerRecord]) -> dict[str, LedgerRecord]:
    return {l.order_id: l for l in ledger}


# --- Layer 1: Exact match ----------------------------------------------------

def _try_exact_match(
    bank: BankRecord,
    gw_by_utr: dict[str, list[GatewayRecord]],
    ledger_by_order: dict[str, LedgerRecord],
    claimed_orders: set[str],
) -> MatchResult | None:
    """Match on extracted UTR + amount to the paisa."""
    if not bank.extracted_utr:
        return None

    candidates = gw_by_utr.get(bank.extracted_utr, [])
    if not candidates:
        return None

    # Filter to unclaimed candidates
    candidates = [c for c in candidates if c.order_id not in claimed_orders]
    if not candidates:
        return None

    # Single UTR match — check amount
    if len(candidates) == 1:
        gw = candidates[0]
        diff = round(abs(bank.amount - gw.net_amount), 2)
        ledger = ledger_by_order.get(gw.order_id)
        if diff <= 0.01:  # exact to the paisa
            return MatchResult(
                trace_id=_trace(), layer="exact",
                bank_date=bank.txn_date, bank_narration=bank.narration,
                bank_amount=bank.amount, bank_utr=bank.extracted_utr,
                gateway_order_ids=[gw.order_id],
                gateway_payment_ids=[gw.payment_id],
                gateway_utrs=[gw.settlement_utr],
                gateway_net_amounts=[gw.net_amount],
                gateway_total_net=gw.net_amount,
                ledger_order_ids=[gw.order_id] if ledger else [],
                ledger_expected_amounts=[ledger.expected_amount] if ledger else [],
                amount_diff=diff, confidence=1.0,
                status="matched", reason_code=None,
                reason=f"Exact UTR match ({bank.extracted_utr}), amount matches to ₹{diff:.2f}",
                suggested_step="No action needed — fully reconciled",
                records_compared={"bank_utr": bank.extracted_utr, "gateway_utr": gw.settlement_utr},
            )
        else:
            # UTR matched but amount doesn't — flag it
            return MatchResult(
                trace_id=_trace(), layer="exception",
                bank_date=bank.txn_date, bank_narration=bank.narration,
                bank_amount=bank.amount, bank_utr=bank.extracted_utr,
                gateway_order_ids=[gw.order_id],
                gateway_payment_ids=[gw.payment_id],
                gateway_utrs=[gw.settlement_utr],
                gateway_net_amounts=[gw.net_amount],
                gateway_total_net=gw.net_amount,
                ledger_order_ids=[gw.order_id] if ledger else [],
                ledger_expected_amounts=[ledger.expected_amount] if ledger else [],
                amount_diff=diff, confidence=None,
                status="exception",
                reason_code=ReasonCode.AMOUNT_MISMATCH_BEYOND_TOLERANCE,
                reason=_REASON_MESSAGES[ReasonCode.AMOUNT_MISMATCH_BEYOND_TOLERANCE].format(
                    diff=diff, tol=AMOUNT_TOLERANCE),
                suggested_step=_SUGGESTED_STEPS[ReasonCode.AMOUNT_MISMATCH_BEYOND_TOLERANCE],
            )

    # Multiple records with same UTR — this is a split settlement
    total_net = round(sum(c.net_amount for c in candidates), 2)
    diff = round(abs(bank.amount - total_net), 2)
    if diff <= AMOUNT_TOLERANCE:
        return MatchResult(
            trace_id=_trace(), layer="exact",
            bank_date=bank.txn_date, bank_narration=bank.narration,
            bank_amount=bank.amount, bank_utr=bank.extracted_utr,
            gateway_order_ids=[c.order_id for c in candidates],
            gateway_payment_ids=[c.payment_id for c in candidates],
            gateway_utrs=[c.settlement_utr for c in candidates],
            gateway_net_amounts=[c.net_amount for c in candidates],
            gateway_total_net=total_net,
            ledger_order_ids=[c.order_id for c in candidates if c.order_id in ledger_by_order],
            ledger_expected_amounts=[
                ledger_by_order[c.order_id].expected_amount
                for c in candidates if c.order_id in ledger_by_order
            ],
            amount_diff=diff, confidence=1.0,
            status="matched", reason_code=None,
            reason=f"Split settlement: {len(candidates)} orders on UTR {bank.extracted_utr}, "
                   f"total net ₹{total_net:.2f} matches bank ₹{bank.amount:.2f} (diff ₹{diff:.2f})",
            suggested_step="No action needed — split settlement fully reconciled",
        )

    return None  # let tolerant/LLM layers try


# --- Layer 2: Tolerant match --------------------------------------------------

def _try_tolerant_match(
    bank: BankRecord,
    gateway: list[GatewayRecord],
    ledger_by_order: dict[str, LedgerRecord],
    claimed_orders: set[str],
) -> MatchResult | None:
    """Amount within tolerance + date window + fuzzy string match."""
    candidates = []
    for gw in gateway:
        if gw.order_id in claimed_orders:
            continue
        if not _date_in_window(bank.txn_date, gw.settlement_date):
            continue
        diff = abs(bank.amount - gw.net_amount)
        if diff > AMOUNT_TOLERANCE:
            continue
        # Fuzzy match: check if any part of narration resembles the UTR or order_id
        narr_upper = bank.narration.upper()
        utr_score = fuzzy_ratio(gw.settlement_utr, narr_upper) if gw.settlement_utr else 0
        order_score = fuzzy_ratio(gw.order_id.upper(), narr_upper)
        best_score = max(utr_score, order_score)
        candidates.append((gw, diff, best_score))

    if not candidates:
        return None

    # Filter by fuzzy threshold
    good = [(gw, diff, score) for gw, diff, score in candidates if score >= FUZZY_THRESHOLD]
    if not good:
        # Even without fuzzy match, if there's exactly one candidate within
        # tight amount tolerance and date window, accept it
        tight = [(gw, diff, score) for gw, diff, score in candidates if diff <= 1.0]
        if len(tight) == 1:
            good = tight

    if not good:
        return None

    if len(good) > 1:
        # Multiple candidates — check if they're ambiguous duplicates
        amounts = [gw.net_amount for gw, _, _ in good]
        if len(set(amounts)) == 1:
            # Same amount, same window — genuinely ambiguous
            # Pick the one with best fuzzy score
            good.sort(key=lambda x: (-x[2], x[1]))

    # Take the best match (highest fuzzy score, then lowest amount diff)
    good.sort(key=lambda x: (-x[2], x[1]))
    best_gw, best_diff, best_score = good[0]
    ledger = ledger_by_order.get(best_gw.order_id)

    return MatchResult(
        trace_id=_trace(), layer="tolerant",
        bank_date=bank.txn_date, bank_narration=bank.narration,
        bank_amount=bank.amount, bank_utr=bank.extracted_utr,
        gateway_order_ids=[best_gw.order_id],
        gateway_payment_ids=[best_gw.payment_id],
        gateway_utrs=[best_gw.settlement_utr],
        gateway_net_amounts=[best_gw.net_amount],
        gateway_total_net=best_gw.net_amount,
        ledger_order_ids=[best_gw.order_id] if ledger else [],
        ledger_expected_amounts=[ledger.expected_amount] if ledger else [],
        amount_diff=round(best_diff, 2), confidence=round(0.7 + 0.3 * best_score, 2),
        status="matched", reason_code=None,
        reason=f"Tolerant match — amount diff ₹{best_diff:.2f}, "
               f"date within {abs((bank.txn_date - best_gw.settlement_date).days)}d, "
               f"fuzzy score {best_score:.0%}",
        suggested_step="No action needed — matched within tolerance",
    )


# --- Layer 3: LLM-assisted match ---------------------------------------------

def _try_llm_match(
    bank: BankRecord,
    gateway: list[GatewayRecord],
    ledger_by_order: dict[str, LedgerRecord],
    claimed_orders: set[str],
    use_llm: bool = True,
) -> MatchResult | None:
    """LLM proposes a match; deterministic code verifies arithmetic."""
    if not use_llm:
        return None

    # Build candidate list for the LLM
    candidates = []
    for gw in gateway:
        if gw.order_id in claimed_orders:
            continue
        # Wider window for LLM layer
        if abs((bank.txn_date - gw.settlement_date).days) > DATE_WINDOW_DAYS * 2:
            continue
        candidates.append({
            "order_id": gw.order_id,
            "payment_id": gw.payment_id,
            "net_amount": gw.net_amount,
            "settlement_utr": gw.settlement_utr,
            "settlement_date": gw.settlement_date.isoformat(),
            "status": gw.status,
        })

    if not candidates:
        return None

    import time
    time.sleep(0.2)
    from model import propose_match
    proposal = propose_match(
        narration=bank.narration,
        bank_amount=bank.amount,
        bank_date=bank.txn_date.isoformat(),
        candidates=candidates,
    )

    if not proposal["candidate_ids"] or proposal["confidence"] <= 0:
        return None

    # Find the proposed gateway records
    proposed_gw = [
        gw for gw in gateway
        if gw.order_id in proposal["candidate_ids"]
        and gw.order_id not in claimed_orders
    ]
    if not proposed_gw:
        return None

    # DETERMINISTIC VERIFICATION — the LLM proposed, now Python checks the math
    total_net = round(sum(g.net_amount for g in proposed_gw), 2)
    diff = round(abs(bank.amount - total_net), 2)

    # If the arithmetic doesn't check out, reject even a confident proposal
    if diff > AMOUNT_TOLERANCE * 2:  # wider tolerance for LLM layer
        return MatchResult(
            trace_id=_trace(), layer="exception",
            bank_date=bank.txn_date, bank_narration=bank.narration,
            bank_amount=bank.amount, bank_utr=bank.extracted_utr,
            gateway_order_ids=[g.order_id for g in proposed_gw],
            gateway_payment_ids=[g.payment_id for g in proposed_gw],
            gateway_utrs=[g.settlement_utr for g in proposed_gw],
            gateway_net_amounts=[g.net_amount for g in proposed_gw],
            gateway_total_net=total_net,
            ledger_order_ids=[], ledger_expected_amounts=[],
            amount_diff=diff, confidence=proposal["confidence"],
            status="exception",
            reason_code=ReasonCode.AMOUNT_MISMATCH_BEYOND_TOLERANCE,
            reason=f"AI proposed match but arithmetic failed: bank ₹{bank.amount:.2f} "
                   f"vs gateway net ₹{total_net:.2f} (diff ₹{diff:.2f})",
            suggested_step=_SUGGESTED_STEPS[ReasonCode.AMOUNT_MISMATCH_BEYOND_TOLERANCE],
        )

    # Check confidence threshold
    if proposal["confidence"] < LLM_CONFIDENCE_THRESHOLD:
        return MatchResult(
            trace_id=_trace(), layer="exception",
            bank_date=bank.txn_date, bank_narration=bank.narration,
            bank_amount=bank.amount, bank_utr=bank.extracted_utr,
            gateway_order_ids=[g.order_id for g in proposed_gw],
            gateway_payment_ids=[g.payment_id for g in proposed_gw],
            gateway_utrs=[g.settlement_utr for g in proposed_gw],
            gateway_net_amounts=[g.net_amount for g in proposed_gw],
            gateway_total_net=total_net,
            ledger_order_ids=[], ledger_expected_amounts=[],
            amount_diff=diff, confidence=proposal["confidence"],
            status="exception",
            reason_code=ReasonCode.LOW_CONFIDENCE_LLM_MATCH,
            reason=_REASON_MESSAGES[ReasonCode.LOW_CONFIDENCE_LLM_MATCH].format(
                conf=proposal["confidence"], threshold=LLM_CONFIDENCE_THRESHOLD),
            suggested_step=_SUGGESTED_STEPS[ReasonCode.LOW_CONFIDENCE_LLM_MATCH],
        )

    # Arithmetic checks out AND confidence is above threshold — accept
    is_split = len(proposed_gw) > 1
    return MatchResult(
        trace_id=_trace(), layer="llm_assisted",
        bank_date=bank.txn_date, bank_narration=bank.narration,
        bank_amount=bank.amount, bank_utr=bank.extracted_utr,
        gateway_order_ids=[g.order_id for g in proposed_gw],
        gateway_payment_ids=[g.payment_id for g in proposed_gw],
        gateway_utrs=[g.settlement_utr for g in proposed_gw],
        gateway_net_amounts=[g.net_amount for g in proposed_gw],
        gateway_total_net=total_net,
        ledger_order_ids=[
            g.order_id for g in proposed_gw if g.order_id in ledger_by_order
        ],
        ledger_expected_amounts=[
            ledger_by_order[g.order_id].expected_amount
            for g in proposed_gw if g.order_id in ledger_by_order
        ],
        amount_diff=diff,
        confidence=proposal["confidence"],
        status="matched", reason_code=None,
        reason=f"AI-assisted {'split ' if is_split else ''}match — {proposal['reason']}. "
               f"Arithmetic verified: diff ₹{diff:.2f}",
        suggested_step="AI-matched and arithmetically verified — review if needed",
    )


# --- Unmatched → Exception ---------------------------------------------------

def _make_exception(
    bank: BankRecord,
    gateway: list[GatewayRecord],
    claimed_orders: set[str],
) -> MatchResult:
    """Classify why this bank entry couldn't be matched."""
    # Check if there are candidates that almost matched
    near_candidates = [
        gw for gw in gateway
        if gw.order_id not in claimed_orders
        and _date_in_window(bank.txn_date, gw.settlement_date, DATE_WINDOW_DAYS * 2)
    ]

    # Check for duplicate-amount ambiguity
    if len(near_candidates) >= 2:
        amounts = [gw.net_amount for gw in near_candidates]
        amount_diffs = [abs(bank.amount - a) for a in amounts]
        close_ones = [d for d in amount_diffs if d <= AMOUNT_TOLERANCE]
        if len(close_ones) >= 2:
            return MatchResult(
                trace_id=_trace(), layer="exception",
                bank_date=bank.txn_date, bank_narration=bank.narration,
                bank_amount=bank.amount, bank_utr=bank.extracted_utr,
                gateway_order_ids=[gw.order_id for gw in near_candidates],
                gateway_payment_ids=[gw.payment_id for gw in near_candidates],
                gateway_utrs=[gw.settlement_utr for gw in near_candidates],
                gateway_net_amounts=[gw.net_amount for gw in near_candidates],
                gateway_total_net=None,
                ledger_order_ids=[], ledger_expected_amounts=[],
                amount_diff=None, confidence=None,
                status="exception",
                reason_code=ReasonCode.DUPLICATE_CANDIDATES_AMBIGUOUS,
                reason=_REASON_MESSAGES[ReasonCode.DUPLICATE_CANDIDATES_AMBIGUOUS].format(
                    n=len(close_ones)),
                suggested_step=_SUGGESTED_STEPS[ReasonCode.DUPLICATE_CANDIDATES_AMBIGUOUS],
            )

    # Check if this might be an unresolved split
    if near_candidates:
        # See if any pair/triple of candidates sums close to bank amount
        for i, c1 in enumerate(near_candidates):
            for c2 in near_candidates[i + 1:]:
                pair_sum = round(c1.net_amount + c2.net_amount, 2)
                if abs(bank.amount - pair_sum) <= AMOUNT_TOLERANCE:
                    return MatchResult(
                        trace_id=_trace(), layer="exception",
                        bank_date=bank.txn_date, bank_narration=bank.narration,
                        bank_amount=bank.amount, bank_utr=bank.extracted_utr,
                        gateway_order_ids=[c1.order_id, c2.order_id],
                        gateway_payment_ids=[c1.payment_id, c2.payment_id],
                        gateway_utrs=[c1.settlement_utr, c2.settlement_utr],
                        gateway_net_amounts=[c1.net_amount, c2.net_amount],
                        gateway_total_net=pair_sum,
                        ledger_order_ids=[], ledger_expected_amounts=[],
                        amount_diff=round(abs(bank.amount - pair_sum), 2),
                        confidence=None,
                        status="exception",
                        reason_code=ReasonCode.SPLIT_SETTLEMENT_UNRESOLVED,
                        reason=_REASON_MESSAGES[ReasonCode.SPLIT_SETTLEMENT_UNRESOLVED],
                        suggested_step=_SUGGESTED_STEPS[ReasonCode.SPLIT_SETTLEMENT_UNRESOLVED],
                    )

    return MatchResult(
        trace_id=_trace(), layer="exception",
        bank_date=bank.txn_date, bank_narration=bank.narration,
        bank_amount=bank.amount, bank_utr=bank.extracted_utr,
        gateway_order_ids=[], gateway_payment_ids=[],
        gateway_utrs=[], gateway_net_amounts=[],
        gateway_total_net=None,
        ledger_order_ids=[], ledger_expected_amounts=[],
        amount_diff=None, confidence=None,
        status="exception",
        reason_code=ReasonCode.NO_CANDIDATE_IN_WINDOW,
        reason=_REASON_MESSAGES[ReasonCode.NO_CANDIDATE_IN_WINDOW].format(
            tol=AMOUNT_TOLERANCE, days=DATE_WINDOW_DAYS),
        suggested_step=_SUGGESTED_STEPS[ReasonCode.NO_CANDIDATE_IN_WINDOW],
    )


# --- Pending orders (ledger with no settlement) --------------------------------

def _pending_exceptions(
    ledger: list[LedgerRecord],
    matched_order_ids: set[str],
) -> list[MatchResult]:
    """Flag ledger entries with no settlement as PENDING (informational)."""
    results = []
    for l in ledger:
        if l.status == "pending" and l.order_id not in matched_order_ids:
            results.append(MatchResult(
                trace_id=_trace(), layer="exception",
                bank_date=None, bank_narration="",
                bank_amount=0.0, bank_utr=None,
                gateway_order_ids=[l.order_id],
                gateway_payment_ids=[],
                gateway_utrs=[],
                gateway_net_amounts=[],
                gateway_total_net=None,
                ledger_order_ids=[l.order_id],
                ledger_expected_amounts=[l.expected_amount],
                amount_diff=None, confidence=None,
                status="exception",
                reason_code=ReasonCode.PENDING_NOT_YET_SETTLED,
                reason=_REASON_MESSAGES[ReasonCode.PENDING_NOT_YET_SETTLED],
                suggested_step=_SUGGESTED_STEPS[ReasonCode.PENDING_NOT_YET_SETTLED],
            ))
    return results


# --- Main reconciliation entry point ------------------------------------------

def reconcile(use_llm: bool = True) -> list[MatchResult]:
    """Run the full three-layer reconciliation pipeline."""
    gateway = load_gateway()
    bank = load_bank_statement()
    ledger = load_internal_ledger()

    gw_by_utr = _build_gateway_by_utr(gateway)
    ledger_by_order = _build_ledger_by_order(ledger)
    claimed_orders: set[str] = set()
    results: list[MatchResult] = []

    # Process each bank entry through the layers
    for b in bank:
        # Layer 1: Exact match
        result = _try_exact_match(b, gw_by_utr, ledger_by_order, claimed_orders)
        if result:
            for oid in result.gateway_order_ids:
                claimed_orders.add(oid)
            results.append(result)
            continue

        # Layer 2: Tolerant match
        result = _try_tolerant_match(b, gateway, ledger_by_order, claimed_orders)
        if result:
            for oid in result.gateway_order_ids:
                claimed_orders.add(oid)
            results.append(result)
            continue

        # Layer 3: LLM-assisted match
        result = _try_llm_match(b, gateway, ledger_by_order, claimed_orders, use_llm)
        if result:
            for oid in result.gateway_order_ids:
                if result.status == "matched":
                    claimed_orders.add(oid)
            results.append(result)
            continue

        # No match found — create exception
        results.append(_make_exception(b, gateway, claimed_orders))

    # Add pending-order exceptions
    results.extend(_pending_exceptions(ledger, claimed_orders))

    return results


def summarize(results: list[MatchResult]) -> dict:
    """Compute summary statistics from reconciliation results."""
    total = len(results)
    matched = [r for r in results if r.status == "matched"]
    exceptions = [r for r in results if r.status == "exception"]

    by_layer = {}
    for r in matched:
        by_layer[r.layer] = by_layer.get(r.layer, 0) + 1

    exception_reasons = {}
    for r in exceptions:
        code = r.reason_code or "UNKNOWN"
        exception_reasons[code] = exception_reasons.get(code, 0) + 1

    matched_count = len(matched)
    # Match rate excludes pending (informational, not errors)
    pending_count = exception_reasons.get(ReasonCode.PENDING_NOT_YET_SETTLED, 0)
    actionable_total = total - pending_count

    # Financial rupee amount metrics (Finance Controller focus)
    amount_reconciled = round(sum(r.bank_amount for r in matched), 2)
    amount_at_risk = round(sum(r.bank_amount for r in exceptions if r.reason_code != ReasonCode.PENDING_NOT_YET_SETTLED), 2)
    pending_amount = round(sum(sum(r.ledger_expected_amounts) for r in exceptions if r.reason_code == ReasonCode.PENDING_NOT_YET_SETTLED), 2)
    total_bank_inflow = round(sum(r.bank_amount for r in results if r.bank_amount > 0), 2)

    return {
        "total_records": total,
        "total_matched": matched_count,
        "total_exceptions": len(exceptions),
        "match_rate": round(matched_count / actionable_total, 4) if actionable_total else 0.0,
        "amount_reconciled": amount_reconciled,
        "amount_at_risk": amount_at_risk,
        "pending_amount": pending_amount,
        "total_bank_inflow": total_bank_inflow,
        "by_layer": by_layer,
        "exception_reasons": exception_reasons,
        "pending_count": pending_count,
    }


if __name__ == "__main__":
    import json
    results = reconcile()
    summary = summarize(results)
    print(json.dumps(summary, indent=2))
    print(f"\n--- Sample matches ---")
    for r in results[:5]:
        print(f"  {r.layer:12} {r.status:10} orders={r.gateway_order_ids} "
              f"bank=₹{r.bank_amount:>10.2f}  {r.reason[:60]}")
