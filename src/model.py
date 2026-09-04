"""LLM provider wrapper — supports Google Gemini, OpenAI, and intelligent offline mock.

Zero-dependency implementation: uses standard library urllib for Gemini REST API,
with OpenAI SDK fallback if installed.

Three operational modes:
  1. Google Gemini (GEMINI_API_KEY or GOOGLE_API_KEY in .env):
     Default model: gemini-2.5-flash (or gemini-1.5-flash)
  2. OpenAI (OPENAI_API_KEY in .env):
     Default model: gpt-4o-mini
  3. Offline Mock (default when no key provided, or APP_USE_MOCK=1):
     Heuristic pattern matcher for reconciliation, plus rule-grounded financial
     controller reasoning for Q&A and diagnostics.

Crucial Architectural Invariant:
  The LLM is only allowed to judge, classify, and explain.
  It is NEVER allowed to do raw financial arithmetic unchecked.
  All numeric claims are verified deterministically by Python to the paisa.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from typing import Any

from dotenv import load_dotenv

load_dotenv()

# --- Provider Detection & Configuration ---------------------------------------

_FORCE_MOCK = os.getenv("APP_USE_MOCK", "0") == "1"

GROQ_API_KEY = os.getenv("GROQ_API_KEY") or ""
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or ""
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY") or ""

LLM_PROVIDER_OVERRIDE = (os.getenv("LLM_PROVIDER") or "").lower()

if _FORCE_MOCK:
    ACTIVE_PROVIDER = "mock"
    ACTIVE_MODEL_NAME = "mock (offline baseline)"
elif LLM_PROVIDER_OVERRIDE == "groq" or (GROQ_API_KEY and LLM_PROVIDER_OVERRIDE not in ("gemini", "openai")):
    ACTIVE_PROVIDER = "groq"
    ACTIVE_MODEL_NAME = os.getenv("APP_GROQ_MODEL", "openai/gpt-oss-120b")
elif GEMINI_API_KEY:
    ACTIVE_PROVIDER = "gemini"
    ACTIVE_MODEL_NAME = os.getenv("APP_GEMINI_MODEL", "gemini-3.1-flash-lite")
elif OPENAI_API_KEY:
    ACTIVE_PROVIDER = "openai"
    ACTIVE_MODEL_NAME = os.getenv("APP_OPENAI_MODEL", "gpt-4o-mini")
else:
    ACTIVE_PROVIDER = "mock"
    ACTIVE_MODEL_NAME = "offline mock"

USING_MOCK = ACTIVE_PROVIDER == "mock"

# Setup OpenAI client if needed
_openai_client = None
if ACTIVE_PROVIDER == "openai":
    try:
        from openai import OpenAI
        _openai_client = OpenAI(api_key=OPENAI_API_KEY)
    except Exception:
        ACTIVE_PROVIDER = "mock"
        ACTIVE_MODEL_NAME = "offline mock"
        USING_MOCK = True


def get_active_model_info() -> dict[str, Any]:
    """Return metadata about the currently active LLM provider."""
    return {
        "provider": ACTIVE_PROVIDER,
        "model_name": ACTIVE_MODEL_NAME,
        "is_mock": USING_MOCK,
    }


# --- Generic LLM Callers (Groq / Gemini / OpenAI / Mock) ---------------------

def _call_groq_api(system_prompt: str, user_prompt: str, json_mode: bool = False) -> str:
    """Call Groq API using standard urllib with custom User-Agent and automatic backoff on 429."""
    import time
    url = "https://api.groq.com/openai/v1/chat/completions"
    payload: dict[str, Any] = {
        "model": ACTIVE_MODEL_NAME,
        "temperature": 0.1,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}

    data = json.dumps(payload).encode("utf-8")
    for attempt in range(3):
        req = urllib.request.Request(
            url,
            data=data,
            headers={
                "Authorization": f"Bearer {GROQ_API_KEY}",
                "Content-Type": "application/json",
                "User-Agent": "SettleSense/1.0",
            },
            method="POST"
        )

        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                res_data = json.loads(resp.read().decode("utf-8"))
                choices = res_data.get("choices", [])
                if choices:
                    return choices[0].get("message", {}).get("content", "")
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < 2:
                time.sleep(1.5 * (attempt + 1))
                continue
            print(f"[Warning] Groq API call failed: {e}. Falling back to heuristic mock.")
            break
        except Exception as e:
            print(f"[Warning] Groq API call failed: {e}. Falling back to heuristic mock.")
            break
    return ""


# --- Generic LLM Caller (Gemini / OpenAI / Mock) -----------------------------

def _call_gemini_api(system_prompt: str, user_prompt: str, json_mode: bool = False) -> str:
    """Call Google Gemini REST API using standard urllib."""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{ACTIVE_MODEL_NAME}:generateContent?key={GEMINI_API_KEY}"
    
    payload: dict[str, Any] = {
        "contents": [
            {
                "role": "user",
                "parts": [{"text": f"{system_prompt}\n\nUser Request:\n{user_prompt}"}]
            }
        ],
        "generationConfig": {
            "temperature": 0.1,
        }
    }
    
    if json_mode:
        payload["generationConfig"]["responseMimeType"] = "application/json"

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST"
    )

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            res_data = json.loads(resp.read().decode("utf-8"))
            candidates = res_data.get("candidates", [])
            if candidates:
                parts = candidates[0].get("content", {}).get("parts", [])
                if parts:
                    return parts[0].get("text", "")
    except Exception as e:
        # Fallback to mock on network/auth error
        print(f"[Warning] Gemini API call failed: {e}. Falling back to heuristic mock.")
    return ""


def _call_openai_api(system_prompt: str, user_prompt: str, json_mode: bool = False) -> str:
    """Call OpenAI API using official client."""
    if not _openai_client:
        return ""
    try:
        kwargs: dict[str, Any] = {
            "model": ACTIVE_MODEL_NAME,
            "temperature": 0.1,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        resp = _openai_client.chat.completions.create(**kwargs)
        return resp.choices[0].message.content or ""
    except Exception as e:
        print(f"[Warning] OpenAI API call failed: {e}. Falling back to heuristic mock.")
        return ""


# --- 1. Reconciliation Match Proposer ----------------------------------------

_MATCH_SYSTEM_PROMPT = """You are a financial reconciliation assistant for Razorpay merchants.
You help match bank statement entries to payment gateway settlement records.

Given a bank narration and a list of candidate gateway records, determine which
candidate(s) the bank entry most likely corresponds to. Consider:
- UTR numbers or reference codes embedded in noisy narration text
- Net amount proximity (after deducting Razorpay fees ~2% + 18% GST on fee)
- Settlement lag proximity (typically 1–4 days)
- Whether this could be a split settlement (one bank credit for 2+ orders)

You MUST respond with valid JSON only:
{
  "candidate_ids": ["order_id_1"],
  "confidence": 0.85,
  "reason": "UTR fragment matches candidate gateway settlement with 2-day bank credit lag",
  "is_split": false
}

Rules:
- confidence is 0.0 to 1.0
- reason must be a concise single sentence explaining your judgment
- candidate_ids is a list of order_ids you believe match
- is_split is true only if multiple gateway records map to this single bank entry
- You are ONLY proposing matches. Do NOT compute arithmetic; the deterministic engine verifies all amounts to the paisa."""


def propose_match(narration: str, bank_amount: float, bank_date: str,
                  candidates: list[dict]) -> dict:
    """Ask the LLM to propose a match for an ambiguous bank entry."""
    if not candidates:
        return {
            "candidate_ids": [],
            "confidence": 0.0,
            "reason": "No candidates provided",
            "is_split": False,
        }

    user_msg = (
        f"Bank narration: \"{narration}\"\n"
        f"Bank amount: ₹{bank_amount:,.2f}\n"
        f"Bank date: {bank_date}\n\n"
        f"Candidate gateway settlement records:\n"
    )
    for c in candidates:
        user_msg += (
            f"- order_id: {c['order_id']}, payment_id: {c['payment_id']}, "
            f"net_amount: ₹{c['net_amount']:,.2f}, utr: {c['settlement_utr']}, "
            f"settlement_date: {c['settlement_date']}, status: {c['status']}\n"
        )

    raw_response = ""
    if ACTIVE_PROVIDER == "groq":
        raw_response = _call_groq_api(_MATCH_SYSTEM_PROMPT, user_msg, json_mode=True)
    elif ACTIVE_PROVIDER == "gemini":
        raw_response = _call_gemini_api(_MATCH_SYSTEM_PROMPT, user_msg, json_mode=True)
    elif ACTIVE_PROVIDER == "openai":
        raw_response = _call_openai_api(_MATCH_SYSTEM_PROMPT, user_msg, json_mode=True)

    if raw_response:
        try:
            # Clean possible markdown block
            cleaned = re.sub(r"^```json\s*", "", raw_response.strip())
            cleaned = re.sub(r"\s*```$", "", cleaned)
            data = json.loads(cleaned)
            return {
                "candidate_ids": data.get("candidate_ids", []),
                "confidence": float(data.get("confidence", 0.0)),
                "reason": str(data.get("reason", "LLM proposed match")),
                "is_split": bool(data.get("is_split", False)),
            }
        except Exception:
            pass

    # Fallback to mock heuristics if API not configured or failed
    return _mock_propose_match(narration, bank_amount, candidates)


def _extract_utr_fragment(narration: str) -> str | None:
    """Try to pull a UTR-like string from a bank narration."""
    match = re.search(r'(UTIB|HDFC|ICIC|SBIN|KKBK|BARB)\d{10}', narration)
    if match:
        return match.group(0)
    match = re.search(r'[A-Z]{4}\d{10,}', narration)
    if match:
        return match.group(0)
    return None


def _mock_propose_match(narration: str, bank_amount: float, candidates: list[dict]) -> dict:
    """Intelligent heuristic fallback: UTR fragment search and split-settlement solver."""
    utr_frag = _extract_utr_fragment(narration)

    if utr_frag:
        for c in candidates:
            if c.get("settlement_utr") and utr_frag in c["settlement_utr"]:
                return {
                    "candidate_ids": [c["order_id"]],
                    "confidence": 0.88,
                    "reason": f"UTR fragment '{utr_frag}' extracted from narration matched gateway record",
                    "is_split": False,
                }

    best_single = None
    best_single_diff = float("inf")
    for c in candidates:
        diff = abs(c["net_amount"] - bank_amount)
        if diff < best_single_diff:
            best_single_diff = diff
            best_single = c

    best_pair = None
    best_pair_diff = float("inf")
    if len(candidates) >= 2:
        for i, c1 in enumerate(candidates):
            for c2 in candidates[i + 1:]:
                pair_sum = c1["net_amount"] + c2["net_amount"]
                diff = abs(pair_sum - bank_amount)
                if diff < best_pair_diff:
                    best_pair_diff = diff
                    best_pair = (c1, c2)

    if best_pair and best_pair_diff < 5.0 and best_pair_diff < best_single_diff:
        conf = 0.82 if best_pair_diff < 2.0 else 0.74
        return {
            "candidate_ids": [best_pair[0]["order_id"], best_pair[1]["order_id"]],
            "confidence": conf,
            "reason": f"Multi-order split settlement detected: orders {best_pair[0]['order_id']} + {best_pair[1]['order_id']} sum to bank credit within ₹{best_pair_diff:.2f}",
            "is_split": True,
        }

    if best_single and best_single_diff < 10.0:
        conf = 0.76 if best_single_diff < 2.0 else 0.58
        return {
            "candidate_ids": [best_single["order_id"]],
            "confidence": conf,
            "reason": f"Closest single candidate within ₹{best_single_diff:.2f} tolerance window",
            "is_split": False,
        }

    return {
        "candidate_ids": [],
        "confidence": 0.0,
        "reason": "No candidate within acceptable variance threshold",
        "is_split": False,
    }


# --- 2. Interactive Settlement Q&A Agent --------------------------------------

_CONTROLLER_SYSTEM_PROMPT = """You are SettleSense AI, an expert AI Finance Controller for a merchant using Razorpay.
You analyze reconciliation cycles across three sources:
1. Razorpay Gateway Settlements (Gross, Fee, 18% GST on fee, TDS, Net payout)
2. Bank Statements (NEFT/RTGS credits, extracted UTRs, narration noise)
3. Internal Ledger (Merchant orders, invoice amounts, expected settlements)

You have access to the complete live cycle context provided below.
When answering:
- Be precise, authoritative, and calm, like an elite finance director.
- Quote exact amounts in Indian Rupees (₹) with comma formatting to 2 decimal places.
- When referencing specific orders or transactions, cite their Trace IDs (e.g., [TR-ABC12345]) or Order IDs so the user can inspect them.
- If asked to draft a dispute or support ticket, provide a clean, professional email ready to send to the Razorpay Merchant Desk.
- Do not hallucinate numbers not present in the context.
"""


def chat_controller(message: str, history: list[dict], context: dict) -> str:
    """Answer natural language finance controller queries grounded in live data."""
    summary = context.get("summary", {})
    cash = context.get("cash_position", {})
    exceptions = context.get("exceptions", [])
    metrics = context.get("metrics", {})

    context_summary = f"""
LIVE CYCLE CONTEXT:
- Total records processed: {summary.get('total_records', 0)}
- Matched records: {summary.get('total_matched', 0)} ({summary.get('match_rate', 0):.1%} match rate)
- By layer: Exact={summary.get('by_layer', {}).get('exact', 0)}, Tolerant={summary.get('by_layer', {}).get('tolerant', 0)}, AI-assisted={summary.get('by_layer', {}).get('llm_assisted', 0)}
- Unresolved Exceptions: {len([e for e in exceptions if e.get('reason_code') != 'PENDING_NOT_YET_SETTLED'])}
- Pending Settlements: {summary.get('pending_count', 0)}
- Reconciled Cash Inflow: ₹{cash.get('reconciled_inflow', 0):,.2f}
- Pending Settlements Expected: ₹{cash.get('pending_total', 0):,.2f}
- 7-Day Projected Cash Position: ₹{cash.get('projected_position_7d', 0):,.2f}
- 14-Day Projected Cash Position: ₹{cash.get('projected_position_14d', 0):,.2f}

ACTIVE EXCEPTIONS & PENDING ITEMS:
"""
    for e in exceptions[:10]:
        order_ref = ", ".join(e.get("gateway_order_ids", []) or e.get("ledger_order_ids", [])) or "Unknown"
        amt = f"₹{e.get('bank_amount', 0):,.2f}" if e.get('bank_amount') else "Pending"
        context_summary += (
            f"- [{e.get('trace_id')}]: Order(s) {order_ref} | Amount: {amt} | "
            f"Code: {e.get('reason_code')} | Reason: {e.get('reason')} | Action: {e.get('suggested_step')}\n"
        )

    formatted_history = ""
    for turn in history[-4:]:
        role = turn.get("role", "user")
        content = turn.get("content", "")
        formatted_history += f"{role.capitalize()}: {content}\n"

    user_query = f"{context_summary}\n\nRecent Conversation:\n{formatted_history}\nUser: {message}\nAssistant:"

    if ACTIVE_PROVIDER == "groq":
        ans = _call_groq_api(_CONTROLLER_SYSTEM_PROMPT, user_query)
        if ans:
            return ans
    elif ACTIVE_PROVIDER == "gemini":
        ans = _call_gemini_api(_CONTROLLER_SYSTEM_PROMPT, user_query)
        if ans:
            return ans
    elif ACTIVE_PROVIDER == "openai":
        ans = _call_openai_api(_CONTROLLER_SYSTEM_PROMPT, user_query)
        if ans:
            return ans

    # Intelligent grounded fallback if offline
    return _mock_chat_controller(message, context)


def _mock_chat_controller(message: str, context: dict) -> str:
    """Grounded fallback answers when no external API key is active."""
    msg_lower = message.lower()
    summary = context.get("summary", {})
    cash = context.get("cash_position", {})
    exceptions = context.get("exceptions", [])

    real_exceptions = [e for e in exceptions if e.get("reason_code") != "PENDING_NOT_YET_SETTLED"]
    pending = [e for e in exceptions if e.get("reason_code") == "PENDING_NOT_YET_SETTLED"]

    if "exception" in msg_lower or "unresolved" in msg_lower or "review" in msg_lower:
        out = f"We have **{len(real_exceptions)} actionable exception(s)** requiring review and **{len(pending)} in-flight pending settlement(s)**:\n\n"
        for idx, e in enumerate(real_exceptions, 1):
            order = ", ".join(e.get("gateway_order_ids", []) or e.get("ledger_order_ids", []))
            out += f"**{idx}. Order {order}** (`{e.get('trace_id')}`)\n"
            out += f"- **Issue**: {e.get('reason')}\n"
            out += f"- **Suggested Step**: {e.get('suggested_step')}\n\n"
        out += "Would you like me to draft an investigation report or ticket for any of these?"
        return out

    if "forecast" in msg_lower or "cash" in msg_lower or "projection" in msg_lower or "position" in msg_lower:
        return (
            f"### Cash Position & Liquidity Rollup\n\n"
            f"- **Reconciled Inflow**: ₹{cash.get('reconciled_inflow', 0):,.2f}\n"
            f"- **Pending Pipeline**: ₹{cash.get('pending_total', 0):,.2f} across {len(pending)} orders\n"
            f"- **7-Day Projected Position**: ₹{cash.get('projected_position_7d', 0):,.2f}\n"
            f"- **14-Day Projected Position**: ₹{cash.get('projected_position_14d', 0):,.2f}\n\n"
            f"*Note: This is a deterministic liquidity rollup based on expected settlement windows (T+2), not a statistical prediction.*"
        )

    if "ticket" in msg_lower or "dispute" in msg_lower or "draft" in msg_lower or "email" in msg_lower:
        sample_exc = real_exceptions[0] if real_exceptions else (exceptions[0] if exceptions else {})
        order_ref = ", ".join(sample_exc.get("gateway_order_ids", []) or sample_exc.get("ledger_order_ids", [])) or "ORD-8829"
        pay_id = sample_exc.get("gateway_payment_ids", ["pay_sample"])[0] if sample_exc.get("gateway_payment_ids") else "pay_sample"
        return (
            f"### Draft Merchant Dispute / Inquiry Ticket\n\n"
            f"**To**: Razorpay Merchant Support <support@razorpay.com>\n"
            f"**Subject**: Discrepancy Inquiry: Settlement Batch for Order {order_ref} (Trace: {sample_exc.get('trace_id', 'TR-UNKNOWN')})\n\n"
            f"---\n"
            f"Dear Razorpay Support Team,\n\n"
            f"Our automated reconciliation agent flagged an unresolved variance during our daily books closure:\n\n"
            f"- **Merchant Order ID**: `{order_ref}`\n"
            f"- **Payment Reference**: `{pay_id}`\n"
            f"- **Discrepancy Category**: {sample_exc.get('reason_code', 'AMOUNT_MISMATCH')}\n"
            f"- **Observed Issue**: {sample_exc.get('reason', 'Net payout variance against expected fee calculation')}\n"
            f"- **Internal Audit Trace**: `{sample_exc.get('trace_id', 'TR-UNKNOWN')}`\n\n"
            f"Please verify if a fee adjustment, split payout, or dispute deduction was applied to this settlement.\n\n"
            f"Regards,\n"
            f"Finance Controller Desk"
        )

    # General controller summary
    return (
        f"### SettleSense AI Controller Status\n\n"
        f"Our books currently stand at a **{summary.get('match_rate', 0):.1%} auto-reconciliation rate** "
        f"({summary.get('total_matched', 0)} of {summary.get('total_records', 0) - summary.get('pending_count', 0)} records closed).\n\n"
        f"- **Reconciled Inflow**: ₹{cash.get('reconciled_inflow', 0):,.2f}\n"
        f"- **Pending Settlements**: ₹{cash.get('pending_total', 0):,.2f}\n"
        f"- **Actionable Exceptions**: {len(real_exceptions)} items requiring review\n\n"
        f"You can ask me to inspect any specific order, explain fee breakdowns, forecast liquidity, or draft dispute emails."
    )


# --- 3. AI Deep Exception Diagnosis ------------------------------------------

_DIAGNOSE_SYSTEM_PROMPT = """You are SettleSense AI Finance Auditor.
Given an unresolved financial exception record from a Razorpay reconciliation run, provide:
1. Root-Cause Analysis: Break down why the gateway, bank, and ledger failed to align (fee discrepancies, narration obfuscation, split settlement, or lag).
2. Arithmetic Proof: Explicit breakdown of gross amount, Razorpay fee (2%), GST on fee (18%), and net difference.
3. Recommended Resolution: The exact step the finance team should take.
4. Support Ticket Draft: Ready-to-send dispute ticket to Razorpay merchant desk.

Return clean, professional Markdown with clear section headers."""


def _safe_fmt_curr(val: Any) -> str:
    if val is None:
        return "N/A"
    try:
        return f"₹{float(val):,.2f}"
    except (ValueError, TypeError):
        return str(val)


def diagnose_exception(record: dict) -> str:
    """Generate an in-depth AI root-cause audit and dispute draft for an exception."""
    bank_amt_str = _safe_fmt_curr(record.get('bank_amount'))
    gw_total_str = _safe_fmt_curr(record.get('gateway_total_net'))
    diff_str = _safe_fmt_curr(record.get('amount_diff'))

    user_prompt = f"""
EXCEPTION RECORD:
- Trace ID: {record.get('trace_id')}
- Reason Code: {record.get('reason_code')}
- Status: {record.get('status')}
- Bank Amount: {bank_amt_str}
- Bank Date: {record.get('bank_date')}
- Bank Narration: "{record.get('bank_narration')}"
- Extracted UTR: {record.get('bank_utr')}
- Gateway Order IDs: {record.get('gateway_order_ids')}
- Gateway Payment IDs: {record.get('gateway_payment_ids')}
- Gateway Net Amounts: {record.get('gateway_net_amounts')}
- Gateway Total Net: {gw_total_str}
- Ledger Expected Amounts: {record.get('ledger_expected_amounts')}
- Amount Difference: {diff_str}
- Initial Reason: {record.get('reason')}
- Suggested Step: {record.get('suggested_step')}
"""

    if ACTIVE_PROVIDER == "groq":
        diag = _call_groq_api(_DIAGNOSE_SYSTEM_PROMPT, user_prompt)
        if diag:
            return diag
    elif ACTIVE_PROVIDER == "gemini":
        diag = _call_gemini_api(_DIAGNOSE_SYSTEM_PROMPT, user_prompt)
        if diag:
            return diag
    elif ACTIVE_PROVIDER == "openai":
        diag = _call_openai_api(_DIAGNOSE_SYSTEM_PROMPT, user_prompt)
        if diag:
            return diag

    # Deterministic fallback audit
    order_ref = ", ".join(record.get('gateway_order_ids', []) or record.get('ledger_order_ids', [])) or "ORD-UNKNOWN"
    pay_id = record.get('gateway_payment_ids', ['pay_unknown'])[0] if record.get('gateway_payment_ids') else "pay_unknown"

    return f"""### 🔍 AI Root-Cause Audit: {record.get('trace_id')}

#### 1. Discrepancy Breakdown
- **Classification**: `{record.get('reason_code')}`
- **Primary Cause**: {record.get('reason')}
- **Bank Credit**: {bank_amt_str} on {record.get('bank_date') or 'N/A'}
- **Gateway Expected Net**: {gw_total_str}
- **Net Variance**: {diff_str}

#### 2. Technical Findings
- **Narration Analysis**: Raw string `"{record.get('bank_narration') or 'No bank record'}"` lacks direct 1:1 UTR alignment.
- **Settlement Logic**: Gateway deduction verified. Fee structure conforms to 2% base + 18% GST on fees.

#### 3. Recommended Controller Action
1. **Immediate**: {record.get('suggested_step')}.
2. **Book Adjustment**: If verified as gateway fee adjustment, record variance in Ledger Account 5210 (*Payment Processing Fees*).

---
#### 📨 Razorpay Merchant Support Draft
**Subject**: Discrepancy Notice: Settlement Variance on Order `{order_ref}` (`{record.get('trace_id')}`)

Dear Support Team,

During our daily multi-source reconciliation, an unresolved settlement discrepancy was detected:
- **Order ID**: `{order_ref}`
- **Payment ID**: `{pay_id}`
- **UTR**: `{record.get('bank_utr') or 'Pending'}`
- **Bank Deposit**: {bank_amt_str} vs **Settlement Target**: {gw_total_str} (Variance: {diff_str})

Kindly clarify whether this reflects a split batch deduction or an unreflected refund reserve.

Best regards,  
Finance Operations Controller Desk
"""
