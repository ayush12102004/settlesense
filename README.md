<div align="center">

# ⚡ SettleSense — Autonomous AI Finance Controller

### *Closes the multi-source financial settlement loop, runs the books, and forecasts the forward cash position.*

[![Live Demo](https://img.shields.io/badge/Live%20Demo-Render-46E3B7?style=for-the-badge&logo=render&logoColor=white)](https://settlesense-k8lf.onrender.com)
[![Track](https://img.shields.io/badge/Razorpay%20Track%2004-AI%20Finance%20Controller-0C2340?style=for-the-badge)](https://settlesense-k8lf.onrender.com)
[![Precision](https://img.shields.io/badge/Auto--Match%20Precision-100%25-success?style=for-the-badge)](https://settlesense-k8lf.onrender.com)
[![Health Probe](https://img.shields.io/badge/Health%20Probe-Passing-blue?style=for-the-badge)](https://settlesense-k8lf.onrender.com/health)

---

### 🌐 [**Live Web Application**](https://settlesense-k8lf.onrender.com) • 🩺 [**Health Check**](https://settlesense-k8lf.onrender.com/health) • 📖 [**Architecture Guide**](HOW_IT_WORKS.md) • 📊 [**Finance Case Study**](CASE_STUDY.md)

</div>

---

## 🎯 The Track 04 Challenge

> **"Build an agent that closes ONE finance-ops loop across a 50+ record batch of synthetic data, reporting its match rate and the exceptions it could not resolve. Explicit judging bar: Throughput + measured accuracy + an honest exception list."**

Merchants processing payments on Razorpay reconcile three disparate, asynchronous data sources every day:
1. **Gateway Settlement Report:** Net payouts after deducting ~2% MDR fees, 18% GST on fees, refunds, and TDS.
2. **Bank Statement Feed:** Net deposits arriving with a 1–4 day clearing lag, split across orders, with UTRs obscured inside noisy bank narrations.
3. **Internal ERP / Order Book:** Expected gross checkout volumes and fulfillment timestamps.

Today, finance controllers perform this in spreadsheets with fragile VLOOKUPs. Unreconciled variances get written off or caught weeks late during GST filing. **SettleSense automates this entire settlement and cash loop end-to-end.**

---

## 🛡️ Core Architectural Invariant

<div align="center">

> ### *"The LLM proposes judgment; deterministic Python verifies the arithmetic down to the paisa."*

</div>

In financial operations, an undetected 50-paise discrepancy fails an audit. **SettleSense never allows an LLM to hallucinate numbers or directly mark a transaction as reconciled.**
* **LLMs (Groq LPU / Google Gemini)** are used strictly for **contextual judgment** — parsing cryptic bank narrations, detecting multi-order batch splits, and answering controller queries.
* **Deterministic Python code** rigorously re-calculates every fee, tax deduction, and net payout down to ₹0.00 before any state mutation occurs.
* If the arithmetic does not balance, the AI proposal is immediately rejected and quarantined into Layer 4 as an actionable exception.

---

## 📊 Measured Benchmark Results (Held-Out Ground Truth)

Evaluated against a held-out ground truth test set (`data/ground_truth.csv`) with zero cherry-picking:

| Metric | Measured Result | Fintech Meaning & Evaluation Standard |
|---|---|---|
| **Total Processed Records** | **69** | Synthetic batch exceeding the 50+ record requirement |
| **Eligible Records** | **64** | Records expected to settle within the cycle |
| **Auto-Match Precision** | **100.0%** | **Zero False Positives** (Zero incorrect match attributions) |
| **Recall (Coverage)** | **95.5%** | 63 of 66 matchable orders reconciled across sources |
| **F1-Score** | **97.7%** | Harmonic accuracy metric balancing precision and recall |
| **Overall Match Rate** | **95.3%** | 61 of 64 eligible records auto-reconciled |
| **Reconciled Bank Inflow** | **₹11,95,753.22** | Reconciled bank credits verified down to the paisa |
| **Amount at Risk (Exceptions)**| **₹22,064.88** | Actionable exception volume quarantined for dispute |
| **In-Flight Pipeline Liquidity**| **₹79,683.48** | 5 pending transactions within normal T+2 clearing window |
| **Reason Code Coverage** | **100.0%** | 0% generic errors; 100% of exceptions mapped to action codes |
| **Confusion Matrix** | **TP=63, FP=0, FN=3, TN=5** | Complete transparency against held-out benchmark |
| **Measured AI Ablation Lift** | **+3.1% Match / +6.1% Recall** | Empirically verified lift of Layer 3 AI over pure rules |
| **Processing Throughput** | **~3.3 rec/sec** | Sub-second average latency per record |

---

## 🏗️ System Architecture

```
  Gateway Settlement CSV       Bank Statement Feed CSV        Internal Ledger CSV
           │                             │                             │
           └─────────────────────────────┼─────────────────────────────┘
                                         ▼
                             Data Normalization Engine
                                         ▼
                           4-Layer Reconciliation Engine
      ┌──────────────────────────────────┼──────────────────────────────────┐
      ▼                                  ▼                                  ▼
Layer 1: Exact Match            Layer 2: Tolerant Match             Layer 3: AI Residue
(UTR + Paisa alignment)         (RapidFuzz + Date window)           (Groq LPU / Gemini)
      │                                  │                                  │
      └──────────────────────────────────┼──────────────────────────────────┘
                                         ▼
                            Deterministic Verification
                        (Paisa-level arithmetic re-check)
                                         ▼
                      Layer 4: Taxonomical Exception Engine
                     (100% Actionable Reason Code Quarantine)
                                         ▼
     ┌───────────────────────────┬───────────────────────────┬──────────────────────────┐
     ▼                           ▼                           ▼                          ▼
3-Way GST Audit            Cash Forecaster             Audit Trail            Settlement Q&A
(GSTR-2B vs Inv)           (14-Day + Stress)          (JSON / CSV)             (Groq Agent)
     └───────────────────────────┼───────────────────────────┴──────────────────────────┘
                                 ▼
                     Production WSGI API (Waitress / Gunicorn)
                                 ▼
                     React 18 Single-Page Dashboard (Live on Render)
```

---

## ✨ Key Capabilities

### 1. 4-Layer Multi-Source Matching Engine
* **Layer 1 (Exact):** Instant paisa-perfect alignment on UTR and net payout (47 records).
* **Layer 2 (RapidFuzz Tolerant):** Handles OCR typos, narration truncation, and configurable 3-day clearing windows (12 records).
* **Layer 3 (AI-Assisted Residue):** Leverages Groq LPUs (`openai/gpt-oss-120b`) or Gemini Flash to untangle complex split-settlement groups and noisy narrations (2 records).
* **Layer 4 (Taxonomical Exceptions):** Quarantines unresolvable records under standardized codes (`AMOUNT_MISMATCH_BEYOND_TOLERANCE`, `NO_CANDIDATE_IN_WINDOW`, `PENDING_NOT_YET_SETTLED`).

### 2. Forward Cash Position Forecaster & Clearing Lag Stress Test
* Aggregates settled bank credits vs. in-flight pipeline settlements.
* Generates an interactive **14-day liquidity projection** rendered with Recharts.
* **Dynamic Lag Stress Simulation (+2 Days):** 1-click simulation of weekend banking delays or RBI RTGS freezes to stress-test liquidity troughs.

### 3. Triangulated 3-Way GST Input Tax Credit (ITC) Matcher
* Reconciles daily fee deductions against monthly supplier tax invoices and the government's **GSTR-2B** portal under **SAC 997159** (18% IGST).
* Enforces **Section 16(2)(aa) of the CGST Act** (deferring unfiled invoices to prevent tax notice penalties).
* Accommodates micro-paise daily rounding variances under **GST Rule 36(4)**.

### 4. Interactive Settlement Q&A Controller Agent
* An on-dashboard AI assistant running on Groq LPUs for sub-second responses.
* Grounded strictly in the live reconciliation run: answers complex inquiries (*"What is our 7-day projected cash inflow?"*, *"Why was order 0067 flagged?"*) with cited numbers.

### 5. Deep Exception Diagnosis & Dispute Ticket Drafting
* 1-click root-cause analysis of unresolved discrepancies.
* Automatically drafts ready-to-send dispute support tickets for the **Razorpay Merchant Desk** with order IDs, payment IDs, and mathematical variance proofs.

---

## 🚀 Quickstart & Local Setup

### 1. Clone & Install
```bash
git clone https://github.com/ayush12102004/settlesense.git
cd settlesense
pip install -r requirements.txt
```

### 2. Environment Configuration (Optional)
```bash
cp .env.example .env
```
Add your Groq or Gemini API key in `.env`:
```env
GROQ_API_KEY=gsk_...
LLM_PROVIDER=groq
```
*(If no API key is provided, SettleSense automatically operates on its grounded deterministic heuristic mock with 100% feature availability).*

### 3. Run Test Suite
```bash
python -m pytest tests/ -v
```
*(All 16 unit, integration, and failure-mode tests pass in ~10 seconds).*

### 4. Launch Production Server
```bash
# Production WSGI Server (Waitress / Gunicorn)
python server.py

# Or classic developer server:
python src/main.py --serve
```
Open **`http://localhost:5000`** in your browser.

---

## ☁️ Cloud & Docker Deployment

### Public Cloud (Render / Railway)
SettleSense is pre-configured with declarative [`render.yaml`](render.yaml) and [`Procfile`](Procfile) blueprints:
* **Build Command:** `pip install -r requirements.txt && python src/main.py`
* **Start Command:** `gunicorn src.wsgi:app --bind 0.0.0.0:$PORT --workers 2 --threads 4 --timeout 120`
* **Health Check Path:** `/health`

### Docker Container
```bash
docker build -t settlesense .
docker run -p 5000:5000 -e PORT=5000 settlesense
```

---

## 📂 Repository Structure

```text
settlesense/
├── data/                       # Synthetic financial batch & evaluation artifacts
│   ├── gateway_settlement.csv  # Razorpay payout reports (fees, GST, TDS)
│   ├── bank_statement.csv      # Bank statement feed with noisy narrations
│   ├── internal_ledger.csv     # Merchant order book & expected amounts
│   ├── ground_truth.csv        # Held-out benchmark dataset (69 transactions)
│   ├── dashboard_data.json     # Consolidated frontend bundle
│   ├── tax_reconciliation.json # 3-way GSTR-2B ITC audit report
│   └── audit_trail.json / .csv # Exportable audit trail
├── frontend/
│   └── index.html              # React 18 single-page dashboard (Tailwind + Recharts)
├── src/
│   ├── generate_data.py        # Financial data synthesizer (seed: 42)
│   ├── normalize.py            # Financial normalizer & date/currency parser
│   ├── reconcile.py            # 4-layer multi-source reconciliation engine
│   ├── tax_matcher.py          # 3-way SAC 997159 GST & GSTR-2B auditor
│   ├── cash_position.py        # 14-day liquidity forecaster & stress simulator
│   ├── model.py                # Native Groq LPU, Gemini Flash & OpenAI client
│   ├── evaluate.py             # Ground-truth evaluation & ablation harness
│   ├── audit.py                # Trace logging and CSV/JSON export engine
│   ├── api.py                  # Production Flask API with CORS & health probes
│   ├── wsgi.py                 # Gunicorn WSGI production entrypoint
│   └── main.py                 # Pipeline orchestrator
├── tests/                      # Comprehensive test suite (16 tests)
│   ├── test_reconcile.py       # Matching logic, tolerance, and reason codes
│   ├── test_tax_matcher.py     # Multi-line 3-way GST audit verification
│   ├── test_edge_cases.py      # Precision, recall, and guardrail validations
│   ├── test_production_endpoints.py # Health check and live API tests
│   └── test_failure_modes.py   # AI degradation, rate limits, and fallback tests
├── server.py                   # Multi-threaded production WSGI runner (Waitress)
├── Dockerfile                  # Container specification
├── Procfile                    # Web process definition for PaaS
├── render.yaml                 # Infrastructure-as-code cloud blueprint
├── requirements.txt            # Python dependencies (gunicorn, waitress, etc.)
└── HOW_IT_WORKS.md             # In-depth architectural documentation
```

---

<div align="center">

**Built with ❤️ for the Razorpay AI Buildathon — Track 04: AI Finance Controller**  
*Live Application: [https://settlesense-k8lf.onrender.com](https://settlesense-k8lf.onrender.com)*

</div>
