# How SettleSense Works — Comprehensive Technical Guide

> **SettleSense: Autonomous AI Finance Controller**  
> Built for the **Razorpay AI Buildathon — Track 04: "Run the books and the cash position"**  
> *Closes the multi-source settlement loop across gateway, bank statement, and internal ledger with 14-day cash liquidity forecasting, GSTR-2B tax matching, and an interactive Settlement Q&A Agent.*

🚀 **Live Production URL:** [https://settlesense-k8lf.onrender.com](https://settlesense-k8lf.onrender.com)  
🩺 **Production Health Check:** [https://settlesense-k8lf.onrender.com/health](https://settlesense-k8lf.onrender.com/health)

---

## 1. Executive Summary & The Problem

Every merchant operating at scale with payment gateways like Razorpay faces a daily, high-stakes finance operations nightmare: **reconciling three asynchronous, disparate sources of financial truth**:

1. **What the Gateway Settles (Razorpay Settlement Report):**
   - Contains captured orders, deducted gateway fees (typically ~2% MDR), 18% GST on fees, withholding tax (TDS under Section 194O), and net payout amounts.
   - Payouts are often batched or delayed by T+1 or T+2 banking days.
2. **What the Bank Statement Credits (Bank Account Feed):**
   - Credits arrive via NEFT/RTGS/IMPS.
   - The UTR (Unique Transaction Reference) is buried inside arbitrary, noisy bank narrations (e.g. `NEFT-AXISP0029103910-RAZORPAY SOFTWARE PRIVATE LIMITED-BLR`).
   - Sometimes multiple orders are bundled into a single batch deposit, or a single settlement is split.
3. **What the Internal ERP / Ledger Expected (Merchant Order Book):**
   - Contains gross customer invoice amounts, checkout timestamps, and expected fulfillment revenue.

In traditional finance teams, junior controllers spend hours every morning downloading CSVs, running `VLOOKUP` formulas, and trying to decipher messy bank narrations. Any variance or unmatched transaction creates book imbalance, delayed tax filings, unclaimable GST Input Tax Credit (ITC), or untracked cash leakages.

**SettleSense automates this entire loop end-to-end.**

---

## 2. Core Architectural Invariant

```
               ┌─────────────────────────────────────────────────────────┐
               │              CORE ARCHITECTURAL INVARIANT               │
               │                                                         │
               │   "The LLM proposes judgment; deterministic Python     │
               │    strictly verifies the arithmetic to the paisa."     │
               └─────────────────────────────────────────────────────────┘
```

In finance operations, **generative hallucination is catastrophic**. An LLM that invents a ₹500 payout difference or miscalculates fees silently corrupts the general ledger.

SettleSense adheres to a strict division of responsibility:
- **Google Gemini (Live LLM):** Used exclusively for **linguistic and contextual judgment** — parsing cryptic bank narrations, understanding dispute reasons, analyzing settlement timing, and answering controller questions in natural language.
- **Deterministic Python Engine:** Every proposed match, fee deduction, and net payout is **re-calculated and verified mathematically down to the paisa** (tolerance ≤ ₹5.00 for rounding). If the arithmetic does not check out, the match is rejected immediately regardless of what the LLM suggested.

---

## 3. High-Level System Architecture

```
                    ┌──────────────────────────────────────────────────┐
                    │                 Input Data Sources               │
                    │  1. Gateway Settlements  (Razorpay CSV)          │
                    │  2. Bank Statements      (Noisy UTR feed CSV)    │
                    │  3. Internal ERP Ledger  (Orders & amounts CSV)  │
                    └────────────────────────┬─────────────────────────┘
                                             │
                                             ▼
                               ┌───────────────────────────┐
                               │       Normalization       │
                               │     (src/normalize.py)    │
                               │  - Regex UTR extraction   │
                               │  - ISO Date parsing       │
                               │  - Float currency parsing │
                               └─────────────┬─────────────┘
                                             │
                                             ▼
                      ┌─────────────────────────────────────────────┐
                      │    Layered Reconciliation Engine            │
                      │    (src/reconcile.py)                       │
                      │                                             │
                      │   [Layer 1] Exact Match (UTR + Amount)      │
                      │             │ (unmatched)                   │
                      │             ▼                               │
                      │   [Layer 2] Tolerant Match (RapidFuzz)      │
                      │             │ (unmatched)                   │
                      │             ▼                               │
                      │   [Layer 3] AI Residue Match (Gemini 3.1)   │
                      │             │ (unmatched)                   │
                      │             ▼                               │
                      │   [Layer 4] Taxonomical Exception Engine    │
                      └──────────────┬──────────────────────────────┘
                                     │
         ┌───────────────────────────┼───────────────────────────┐
         │                           │                           │
         ▼                           ▼                           ▼
┌───────────────────┐      ┌───────────────────┐      ┌─────────────────────┐
│ Tax-Line Matcher  │      │ Cash Forecaster   │      │ Audit Trail Engine  │
│ (src/tax_matcher) │      │ (src/cash_pos)    │      │ (src/audit.py)      │
│ - SAC 997159      │      │ - 14-day rollup   │      │ - Immutable trace ID│
│ - 18% IGST        │      │ - Dynamic stress  │      │ - JSON & CSV export │
│ - GSTR-2B ITC     │      │   simulation (+2d)│      │ - Full event history│
└────────┬──────────┘      └─────────┬─────────┘      └──────────┬──────────┘
         │                           │                           │
         └───────────────────────────┼───────────────────────────┘
                                     │
                                     ▼
                   ┌───────────────────────────────────┐
                   │        Flask Backend API          │
                   │        (src/api.py)               │
                   │  - /api/dashboard                 │
                   │  - /api/chat (Settlement Q&A)     │
                   │  - /api/agent/diagnose            │
                   │  - /api/tax-reconciliation        │
                   │  - /api/cash-position/simulate    │
                   │  - /api/audit/export (JSON/CSV)   │
                   └─────────────────┬─────────────────┘
                                     │
                                     ▼
                   ┌───────────────────────────────────┐
                   │    Single-Page React Dashboard    │
                   │    (frontend/index.html)          │
                   │  - Tailwind CSS + Recharts        │
                   │  - Zone 1: Hero Match Metrics     │
                   │  - Zone 2: Cash Position & Stress │
                   │  - Zone 3: Needs Review Exceptions│
                   │  - Zone 4: Tax-Line & GSTR-2B     │
                   │  - Zone 5: Evaluation & Ablation  │
                   │  - Slide-out Q&A & Audit Drawers  │
                   └───────────────────────────────────┘
```

---

## 4. Deep Dive: Component Implementation Details

### Component 1: Data Ingestion & Normalization (`src/normalize.py`)
Real-world bank statements and gateway reports use wildly inconsistent formats. `normalize.py` transforms raw CSV inputs into clean, strongly typed dataclasses:
- **`GatewayRecord`:** `payment_id`, `order_id`, `gross_amount`, `razorpay_fee` (2%), `gst_on_fee` (18% of fee), `tax_deducted` (TDS), `net_amount`, `settlement_utr`, `settlement_date`, `status` (`captured`, `refunded`, `disputed`).
- **`BankRecord`:** `txn_date`, `narration`, `amount`, `balance`, `value_date`, `extracted_utr`.
- **`LedgerRecord`:** `order_id`, `expected_amount`, `order_date`, `customer_id`, `status`.

**Regex UTR Extraction:**  
Bank feeds embed UTRs in arbitrary formats (`NEFT/UTIB0001234567/...`, `RTGS-CMS-CMS1234567890-...`, `UPI/512345678901/...`). The normalizer uses robust regex patterns to parse and isolate the 12–22 alphanumeric character reference code.

---

### Component 2: The 4-Layer Reconciliation Engine (`src/reconcile.py`)

Reconciliation runs through a priority cascade where earlier layers resolve obvious items with low computational cost, leaving only ambiguous residues for AI:

#### Layer 1: Exact Match (Deterministic)
- Checks if the bank narration contains a valid extracted UTR that directly indexes into `GatewayRecord.settlement_utr`.
- Checks if `abs(bank.amount - gateway.net_amount) <= 0.01` (exact to the paisa).
- Handles **batch/split settlements**: if multiple orders share the same settlement UTR, it sums `sum(net_amount)` and compares against the bank credit.
- Confidence: `1.0`. Status: `matched`.

#### Layer 2: Tolerant Match (Fuzzy & Date Window)
- For records without an exact UTR match (e.g. truncated bank narrations, partial order IDs in narration).
- Looks within a configurable date window (`DATE_WINDOW_DAYS = 5`).
- Computes string similarity using **RapidFuzz** (`token_sort_ratio >= 0.60`).
- Validates that amounts match within `AMOUNT_TOLERANCE = 5.00` (covering minor bank rounding variances).
- Confidence: `0.85 - 0.95`. Status: `matched`.

#### Layer 3: AI-Assisted Residue Match (`src/model.py`)
- Invoked only for residual unresolved bank transactions that have nearby gateway candidates.
- Bundles candidate metadata into a structured prompt sent to **Google Gemini 3.1 Flash Lite**.
- The LLM assesses whether complex corporate payout narrations (e.g. *"RAZORPAY CMS CORP PAYOUT BATCH 491"*) correspond to specific sets of pending orders.
- **Safety Gate:** The LLM returns a proposed match in structured JSON. Python re-checks:
  ```python
  if abs(bank.amount - sum(matched_gw.net_amounts)) <= AMOUNT_TOLERANCE:
      # Verified arithmetic -> Mark matched
  else:
      # Math failed -> Reject LLM proposal, force into Layer 4 Exception
  ```

#### Layer 4: Taxonomical Exception Engine
Any record that cannot be verified is **never silently dropped**. It is tagged with an immutable `trace_id` and assigned one of 6 standardized finance reason codes:
1. `NO_CANDIDATE_IN_WINDOW`: Bank credit received with no matching order within the date window (orphan credit / manual transfer).
2. `AMOUNT_MISMATCH_BEYOND_TOLERANCE`: UTR matched, but amount variance exceeded tolerance (e.g. unexpected dispute fee or chargeback penalty).
3. `SPLIT_SETTLEMENT_UNRESOLVED`: Multiple partial settlements detected that do not sum to the order total.
4. `DUPLICATE_CANDIDATES_AMBIGUOUS`: Multiple identical amount orders on the same day without distinct UTRs.
5. `PENDING_NOT_YET_SETTLED`: Order captured on gateway but still within normal T+2 banking window (not an error, just in-flight).
6. `LOW_CONFIDENCE_LLM_MATCH`: LLM proposed a link with confidence below 0.70.

Every exception also generates a **human-actionable suggested step** (e.g. *"Raise Razorpay dispute ticket for fee discrepancy"*, *"Allow T+2 clearing cycle to complete"*).

---

### Component 3: Tax-Line & GSTR-2B Input Tax Credit Matcher (`src/tax_matcher.py`)

Under Indian GST law, merchants processing payments via Razorpay pay **18% IGST on payment processing fees (SAC Code: 997159 - Financial and Related Services)**. Merchants are legally entitled to claim this GST back as **Input Tax Credit (ITC)** under Section 16(2)(aa) of the CGST Act, but only if three documents match perfectly:

1. **Daily Gateway Deductions:** The cumulative 18% GST deducted daily across all transactions.
2. **Razorpay Monthly Tax Invoice:** The official B2B invoice issued by Razorpay Software Pvt Ltd at month-end (`INV-2025-06-001`).
3. **GSTR-2B Auto-Drafted Statement:** What Razorpay filed with the GST Portal under the merchant's GSTIN.

`tax_matcher.py` performs an automated 3-way reconciliation:
- Computes `taxable_fee_base = round(sum(fees), 2)` (e.g. ₹24,993.10).
- Computes `gst_charged = round(taxable_fee_base * 0.18, 2)` (₹4,498.80).
- Cross-checks invoice taxable base and IGST against the GSTR-2B return.
- If variance is zero, it confirms **`MATCHED_ITC_ELIGIBLE`**, ensuring the merchant saves money by claiming the full ITC with zero audit risk.

---

### Component 4: Deterministic Cash Forecaster & Lag Stress Simulator (`src/cash_position.py`)

Finance controllers must forecast cash availability for vendor payouts and payroll.
- **Deterministic Rollup:** Takes the verified reconciled bank cash (`reconciled_inflow`) and adds captured but pending settlements (`pending_total`) mapped to their expected T+2 settlement dates.
- **Dynamic Settlement Lag Stress Testing (`POST /api/cash-position/simulate`):**
  - Banking holidays or gateway compliance reviews can delay settlements by +2 to +4 days.
  - Controllers can click the **Stress (+2 Days Lag)** toggle on the dashboard.
  - The simulator re-projects the 14-day cumulative cash curve under delayed settlement assumptions, immediately alerting the merchant to potential liquidity troughs before they cause overdrafts.

---

### Component 5: Settlement Q&A Agent & Root-Cause Diagnosis (`src/api.py`, `src/model.py`)

#### Interactive Settlement Q&A Agent
- An on-dashboard chat interface connected to `POST /api/chat`.
- Supported by high-speed Groq LPUs (`openai/gpt-oss-120b` or `llama-3.3-70b-versatile`) as well as Google Gemini, with automatic graceful fallback.
- The user can ask high-level or granular questions:
  - *"Why is order_0070 pending?"*
  - *"What is our cash forecast for the next 7 days?"*
  - *"Reconcile Tax Invoice under SAC 997159"*
  - *"Draft merchant dispute ticket"*
- **Grounded System Prompt:** The agent injects the live summary, all exception records, cash projections, and tax status into the prompt context.
- **Clickable Citations:** When the agent mentions a record (e.g. `[TR-6F3D9EB001CC]`), the frontend automatically renders it as an interactive button. Clicking it instantly opens that exact record's audit drawer.

#### AI Deep Exception Diagnosis & Ticket Drafting
- In the Audit Drawer for any exception, clicking **"Run Root-Cause Diagnosis"** (`POST /api/agent/diagnose`) triggers the AI controller to generate:
  1. A root-cause breakdown of the variance or delay.
  2. A ready-to-send, professionally formatted **Razorpay Merchant Support Dispute Ticket** with order IDs, payment IDs, bank UTRs, and exact variance math.
  3. A 1-click **"Copy Ticket Draft"** button for immediate submission.

---

### Component 6: Single-Page React Dashboard (`frontend/index.html`)

Built following high-performance, single-file frontend principles:
- **React 18 & ReactDOM** with Babel Standalone.
- **Tailwind CSS** with custom finance color tokens (e.g. `#1F8A5F` matched green, `#C4462B` exception red, `#3A5DFF` brand accent).
- **Recharts:** Interactive SVG line chart showing cumulative liquidity projection with custom hover tooltips.
- **Marked:** Markdown parser rendering AI controller responses with headers, tables, code blocks, and clickable trace badges.
- **Exception Resolution & Filtering:** Multi-state filter tabs (`All`, `Exceptions`, `Pending`, `Resolved`), instant search input across order IDs and UTRs, and 1-click `Mark as Resolved / Adjusted` in the audit drawer.
- **GSTR-2B Tax Report Export:** 1-click download of the complete 3-way tax reconciliation breakdown (`GET /api/tax/report`).
- **Throughput & Latency Display:** Live engine throughput (rec/s) and latency metrics rendered in Zone 5.
- **Dual Audit Export:** Direct browser downloads for `audit_trail.json` and `audit_trail.csv`.
- **Keyboard Accessible & Motion Safe:** Modal drawers support `Escape` key close and maintain focus trapping.

---

## 5. Evaluation Benchmark & Ablation Study

Evaluated against a held-out ground truth benchmark (`data/ground_truth.csv`) with 69 synthetic transactions including realistic financial edge cases:

| Metric | Measured Score | What It Proves |
|---|---|---|
| **Overall Match Rate** | **95.3%** | 61 of 64 eligible records auto-reconciled; preserves realistic exceptions |
| **Auto-Match Precision** | **100.0%** | Zero false-positive matches (no wrong reconciliations) |
| **Reason Code Coverage** | **100.0%** | All exceptions have actionable diagnostic codes; zero unclassified drops |
| **Engine Throughput** | **Benchmarked live** | Measures processing throughput (rec/sec) and engine latency down to the millisecond |
| **Actionable Exceptions** | **3 records** | 1 dispute fee penalty, 1 orphan bank deposit, 1 ambiguous candidate |
| **Pending In-Flight** | **5 records** | Normal T+2 un-settled transactions cleanly segregated |
| **AI Ablation Lift** | **+3.1% Match Lift** | Measured accuracy increase provided by AI over pure deterministic matching |

---

## 6. How to Run the Project Locally

### Prerequisites
- Python 3.10+ (Tested on Python 3.13)
- Internet connection (for Groq / Gemini API and frontend CDNs)

### Step 1: Install Dependencies
```bash
pip install -r requirements.txt
```

### Step 2: Configure Environment
Copy the example environment file:
```bash
cp .env.example .env
```
Open `.env` and add your Groq or Google Gemini API key:
```env
# Groq LPU Engine (Recommended for ultra-low latency)
GROQ_API_KEY=gsk_...

# Or Google Gemini
GEMINI_API_KEY=...
```
*(Note: If no key is provided, the system falls back gracefully to its grounded offline mock engine).*

### Step 3: Run the Automated Test Suite
```bash
python -m pytest tests/ -v
```
All 10 unit and integration tests should pass with code 0.

### Step 4: Run Pipeline & Start Web Server
```bash
python src/main.py --serve
```
This orchestrates the full pipeline:
1. Synthesizes/loads gateway, bank, and ledger data.
2. Normalizes records and extracts UTRs.
3. Executes the 4-layer reconciliation engine.
4. Performs the SAC 997159 tax reconciliation.
5. Computes the 14-day cash forecast.
6. Evaluates against ground truth with live throughput benchmarking.
7. Launches the Flask server on **`http://localhost:5000`**.

Open **`http://localhost:5000`** in your browser to view and interact with the controller.
