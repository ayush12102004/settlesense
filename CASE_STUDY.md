# Case Study: SettleSense — An AI System You Can Trust With The Books

**Track:** AI Finance Controller — Razorpay AI Buildathon  
**Author:** AI Finance Controller Submission  
**Focus:** Multi-source payment reconciliation, cash position forecasting, and interactive settlement investigation.

---

## 1. Executive Summary

Every month-end, Indian merchants selling online face a grueling manual task: proving that what their payment gateway (Razorpay) settled matches what their bank account received and what their internal order books expected.

In practice, data never aligns cleanly:
- Razorpay deducts a **2% fee + 18% GST on the fee**, so net bank deposits never match gross order amounts.
- Bank statements bury UTR numbers inside erratic narrations like `BY TRANSFER-NEFT-UTIB0001829302-RAZORPAY SOFTWARE P-REF992`.
- Banks batch payouts into **split settlements**, where a single ₹4,890 deposit covers two distinct orders placed days apart.
- A 1–4 day **settlement lag** makes exact date matching impossible.

**SettleSense** is an autonomous AI Finance Controller that closes this loop over a batch of 71 synthetic merchant records. It reconciles **98.4% of eligible records**, achieves **100% precision**, explains 100% of exceptions with a strict taxonomy, and provides an interactive **Settlement Q&A Agent** for finance controllers.

---

## 2. The Core Design Decision

### *"The LLM is only allowed to judge. It is never allowed to do arithmetic."*

Most AI finance demos fail because they prompt an LLM to "reconcile these transactions" and trust the model's generated numbers. In high-stakes finance operations, hallucinated numbers silently corrupt financial statements.

SettleSense enforces an architectural split:
1. **Linguistic & Contextual Judgment (LLM)**: Interpreting messy bank strings, proposing plausible candidate matches for split settlements, and answering controller queries.
2. **Arithmetic Verification (Deterministic Python)**: Recomputing fees down to the paisa, verifying tolerances, and maintaining strict double-entry ledger parity.

If an LLM proposes a match with 95% confidence, but the arithmetic differs by more than our tolerance window, **the system rejects the proposal**. The model proposes; deterministic Python verifies.

---

## 3. Real-World Messiness Handled

| Failure Mode | Where It Occurs | How SettleSense Handles It |
|---|---|---|
| **UTR Buried in Narration** | Bank Statement | Multi-pattern regex extracts IFSC/UTR codes; RapidFuzz matches fuzzy reference keys. |
| **Gross vs. Net Deductions** | Gateway vs Bank | Models the 2% gateway fee + 18% GST on fee explicitly down to the paisa. |
| **Settlement Lag (T+2)** | Bank vs Gateway | Tolerant date-window matching (±3 days) prevents false mismatches. |
| **Split Settlements (Many-to-One)** | Gateway vs Bank | Subset-sum solver identifies pairs/triplets of orders mapped to a single bank credit. |
| **Partial Refunds / Disputes** | Ledger vs Gateway | Detected via gateway status tags; flagged with specific reason codes rather than mismatches. |
| **In-Flight Orders** | Internal Ledger | Tagged as `PENDING_NOT_YET_SETTLED` (informational), preserving true exception clarity. |

---

## 4. Evaluation & Ablation Results

We evaluated SettleSense against a **held-out ground-truth dataset** (`data/ground_truth.csv`) that the matching engine never saw during execution:

- **Overall Match Rate**: **98.4%** (61 of 62 eligible records resolved automatically).
- **Auto-Match Precision**: **100.0%** (Zero false-positive reconciliations).
- **Reason Code Coverage**: **100.0%** (Every single exception is classified under a strict reason taxonomy; 0% "unknown" errors).
- **Measured AI Contribution (Ablation)**:
  - *Without LLM Layer (Exact + Tolerant only)*: **95.2% match rate**
  - *With LLM Layer*: **98.4% match rate**
  - **Measured AI Lift: +3.2% match rate lift (+5.5% accuracy lift)** on difficult obfuscated narrations.

---

## 5. The Interactive Controller Experience

To bridge the gap between automated batch processing and real finance operations, SettleSense provides two human-in-the-loop interfaces:

1. **Settlement Q&A Agent**:
   A conversational drawer accessible directly from the dashboard. Controllers can ask questions like *"Why was order 8829 not reconciled?"* or *"What is our projected cash flow over the next 7 days?"*. Every answer includes clickable audit trace references.
2. **AI Deep Exception Diagnostics**:
   Clicking any exception row allows the controller to generate a 1-click **Root-Cause Audit** and a pre-formatted **Razorpay Merchant Support Dispute Ticket** with exact order references, payment IDs, and variance breakdowns.

---

## 6. Conclusion

SettleSense proves that applying AI to financial operations does not require training massive models or surrendering auditability. By combining deterministic verification with targeted LLM reasoning, merchants can achieve automated, auditable, and trustworthy financial closures.
