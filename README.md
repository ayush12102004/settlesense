# SettleSense — AI Finance Controller

**Razorpay AI Buildathon — Track 04: AI Finance Controller**  
*Closes the multi-source settlement loop across gateway, bank feed, and internal ledger, with cash position rollup and an interactive Settlement Q&A Agent.*

---

## The Problem

Merchants using Razorpay reconcile three sources every settlement cycle:
1. **What the gateway says it settled**: Net payouts after deducting 2% fee + 18% GST on fee, TDS, and refund adjustments.
2. **What the bank statement actually credits**: NEFT/RTGS credits with UTRs buried in noisy narrations, split across multiple orders, and arriving with a 1–4 day lag.
3. **What the internal ledger expected**: Gross invoice amounts and order dates.

Today, finance controllers do this by hand in spreadsheets under month-end time pressure. Discrepancies get discovered late or written off.

---

## Core Architectural Invariant

> **The LLM proposes judgment; deterministic Python verifies the arithmetic.**
>
> In finance operations, hallucinated numbers silently corrupt the books. SettleSense uses Google Gemini / OpenAI exclusively for **linguistic and contextual judgment** (parsing noisy narrations, detecting split settlements, and answering controller inquiries). Every amount is re-verified down to the paisa by deterministic code before any record is marked as reconciled.

---

## Key Features

### 1. Layered Multi-Source Matching Engine
- **Layer 1: Exact Match**: UTR and amounts align to the paisa.
- **Layer 2: Tolerant Match**: High string similarity via RapidFuzz, configurable date window, and fee-aware tolerance.
- **Layer 3: AI-Assisted Residue Match**: Google Gemini or OpenAI analyzes cryptic bank narrations and split payout structures.
- **Layer 4: Taxonomical Exceptions**: Every unresolved record receives an actionable reason code (e.g. `SPLIT_SETTLEMENT_UNRESOLVED`, `AMOUNT_MISMATCH_BEYOND_TOLERANCE`, `PENDING_NOT_YET_SETTLED`).

### 2. Interactive Settlement Q&A Agent
- An on-dashboard AI assistant grounded in the live reconciliation run.
- Answers complex controller queries: *"Why was order 8829 not reconciled?"*, *"What is our 7-day projected cash inflow?"*.
- Automatically provides clickable citations to audit records.

### 3. AI Deep Exception Diagnostics & Dispute Drafting
- 1-click root-cause investigation for any unresolved exception.
- Formulates a ready-to-send dispute ticket for the Razorpay Merchant Support desk with exact order IDs, payment IDs, and variance calculations.

### 4. Deterministic Cash Position & Lag Stress Forecaster
- Aggregates settled cash inflow vs. in-flight pipeline settlements.
- Generates a 14-day forward liquidity projection rendered with Recharts.
- Features dynamic **Cash Stress Testing** (+2 Days clearing lag simulation) to forecast merchant liquidity risks.

### 5. Tax-Line & GSTR-2B Input Tax Credit (ITC) Matcher
- Reconciles Razorpay monthly tax invoices under SAC `997159` (Payment processing and settlement services at 18% IGST).
- Cross-references daily settlement fee deductions against monthly supplier tax invoices and the government's GSTR-2B portal filing.
- Ensures 100% compliance under Section 16(2)(aa) of the CGST Act for seamless ITC claim processing with zero leakage.

---

## Benchmark & Evaluation Results

Evaluated against a **held-out ground-truth test set** (`data/ground_truth.csv`):

| Metric | Measured Score | Evaluation Meaning |
|---|---|---|
| **Overall Match Rate** | **95.3%** | 61 of 64 eligible records auto-reconciled; realistic exceptions preserved |
| **Auto-Match Precision** | **100.0%** | Zero false-positive matches produced by the engine |
| **Reason Code Coverage** | **100.0%** | 0% generic errors; all exceptions classified into actionable categories |
| **Actionable Exceptions** | **3 records** | 1 dispute fee penalty variance, 1 orphan bank deposit, 1 ambiguous candidate |
| **Pending In-Flight** | **5 records** | Valid T+2 un-settled transactions cleanly segregated |
| **AI Ablation Lift** | **+3.1% Match Lift** | Measured contribution of Gemini over pure deterministic matching |

---

## Project Structure

```
razorpay/
├── data/                       # Synthetic sources + generated artifacts
│   ├── gateway_settlement.csv  # Razorpay payout reports (fees, GST, TDS)
│   ├── bank_statement.csv      # Bank feed with noisy UTR narrations
│   ├── internal_ledger.csv     # Merchant order book & expected amounts
│   ├── ground_truth.csv        # Held-out evaluation benchmark
│   ├── dashboard_data.json     # Consolidated frontend bundle
│   ├── tax_reconciliation.json # Tax invoice vs GSTR-2B ITC 3-way match
│   └── audit_trail.json / .csv # Full exportable audit trail
├── frontend/
│   └── index.html              # Single-file React dashboard (Tailwind + Recharts)
├── src/
│   ├── generate_data.py        # Realistic financial data synthesizer (seed: 42)
│   ├── normalize.py            # Normalization and date/currency parsing
│   ├── reconcile.py            # Deterministic + AI layered reconciliation engine
│   ├── tax_matcher.py          # SAC 997159 Monthly Tax & GSTR-2B ITC matcher
│   ├── model.py                # Native Google Gemini (3.1 Flash Lite) & OpenAI
│   ├── evaluate.py             # Ground-truth evaluation & ablation harness
│   ├── cash_position.py        # 14-day liquidity rollup & lag simulation
│   ├── audit.py                # Trace logging and export engine
│   ├── api.py                  # Flask backend with Q&A, diagnosis, tax & simulation
│   └── main.py                 # Single-command pipeline orchestrator
├── tests/
│   ├── test_reconcile.py       # Engine accuracy, tolerance & exception tests
│   ├── test_tax_matcher.py     # Tax invoice arithmetic and GSTR-2B match tests
│   └── test_api.py             # REST API endpoint tests
├── PRD.md                      # Product Requirements Document
├── DESIGN.md                   # Visual system & token specification
├── CASE_STUDY.md               # Finance Ops Case Study
└── requirements.txt
```

---

## Quickstart

### 1. Installation
```bash
pip install -r requirements.txt
```

### 2. Configure Model (Optional)
To use a live LLM, copy `.env.example` to `.env`:
```bash
cp .env.example .env
```
Add your Google Gemini API key:
```env
GEMINI_API_KEY=your_gemini_api_key_here
```
*(If no API key is provided, SettleSense runs seamlessly on its grounded offline mock).*

### 3. Run Automated Tests
```bash
python -m pytest tests/ -v
```

### 4. Run Pipeline & Launch Dashboard
```bash
python src/main.py --serve
```
Open **`http://localhost:5000`** in your browser.
