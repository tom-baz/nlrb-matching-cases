# CA allegation types: matched vs. unmatched C Cases — Findings

**Date:** 2026-06-17
**Notebook:** `allegations_matched_vs_unmatched.ipynb`
**Data table:** `allegation_prevalence_matched_vs_unmatched.csv`
**Headline matching method:** **fuzzy** (`rc_ac_matches.parquet`). Cluster results are nearly
identical and are included in the CSV; differences between methods are immaterial to the conclusion.

---

## Question

Among CA charges (C Cases), do the **§8(a) allegation types** differ between charges we *could* link
to an RC organizing petition ("matched") and charges we could not ("unmatched")?

## Why it is substantive

The five 8(a) clauses mean different things:

| clause | §8(a) NLRA — employer unfair labor practice |
|---|---|
| **8(a)(1)** | interfering with / coercing employees (catch-all; rides along with most charges) |
| **8(a)(2)** | dominating or supporting a company union |
| **8(a)(3)** | discrimination (e.g. firing) to discourage union activity |
| **8(a)(4)** | retaliation for filing charges / testifying |
| **8(a)(5)** | **refusing to bargain collectively** — presupposes an *already-recognised* union |

A match means a CA charge fell inside an RC petition's window — i.e. it coincides with a **fresh
organizing drive**, before a union is recognised. So we expected **8(a)(3)/(1)** (during-campaign
ULPs) to be over-represented among matched cases and **8(a)(5)** (refusal to bargain) to be
under-represented.

## Data and parsing

- 771,459 CA cases; **99.9%** have a parseable 8(a) clause (629 cells missing/empty).
- The `allegations` cell is comma-separated tokens, and a single token such as `8(a)(1)(3)(5)`
  bundles clauses 1, 3 and 5. We extract **every `(digit)` inside each `8(a)` token** and ignore the
  138 stray `8(b)` co-charges.
- Overall clause prevalence across all CA cases: 8(a)(1) 71.0%, 8(a)(2) 2.8%, 8(a)(3) 45.0%,
  8(a)(4) 4.3%, 8(a)(5) 45.9%.
- "Matched" = the CA case's `c_case_number` appears in the matcher output (≥1 RC match). Under fuzzy:
  **45,824 matched (5.9%)** vs **725,635 unmatched**.

---

## Main result (fuzzy, all CA)

Prevalence = share of cases in the group containing that clause.
**Risk ratio (RR)** = matched % ÷ unmatched %. RR > 1 = over-represented among matched; RR < 1 = under.

| clause | matched % | unmatched % | diff (pp) | risk ratio |
|---|---|---|---|---|
| 8(a)(1) interference | 84.9 | 70.2 | +14.7 | 1.21 |
| 8(a)(2) company union | 4.3 | 2.7 | +1.7 | 1.62 |
| **8(a)(3) discrimination/firing** | **68.5** | **43.6** | **+25.0** | **1.57** |
| 8(a)(4) retaliation | 7.0 | 4.1 | +2.8 | 1.69 |
| **8(a)(5) refusal to bargain** | **16.1** | **47.8** | **−31.7** | **0.34** |

**Eligible-only cut** (excluding CA cases that can never match for lack of usable company/city, so any
difference is about the nature of the charge, not missing fields): **identical to two decimals** —
8(a)(3) RR 1.58, 8(a)(5) RR 0.34. The pattern is not a data-quality artifact.

### Refusal-to-bargain signal

| | matched (n=45,824) | unmatched (n=725,635) |
|---|---|---|
| involves 8(a)(3) (discrimination) | 68.5% | 43.6% |
| involves 8(a)(5) (refuse to bargain) | 16.1% | 47.8% |
| **pure 8(a)(5) only** | **3.0%** | **18.1%** |

Nearly half of unmatched charges involve refusal-to-bargain, and ~1 in 5 are *pure* 8(a)(5); among
matched charges those drop to 16% and 3%.

---

## Interpretation

The hypothesis holds, strongly and in the expected direction:

- **8(a)(3)** (retaliatory firing) and **8(a)(1)** (coercion) are **over-represented** among matched
  cases — the classic employer ULPs that arise *during* an organizing campaign. 8(a)(3) rises from
  44% (unmatched) to 69% (matched).
- **8(a)(5)** (refusal to bargain) is **strongly under-represented** among matched cases (RR 0.34),
  and pure-8(a)(5) charges are 6× rarer among matched than unmatched.

This corroborates that the **low overall CA match rate is substantive, not a matcher failure.** A
large share of the unmatched charges are **existing-union disputes** (refusal to bargain) that, by
definition, have no concurrent organizing petition to match. The matched set skews toward the
retaliation/coercion charges an RC-window match should capture.

## Caveats

- **8(a)(1) is a near-universal "rider"** (70%+ everywhere), so its modest RR (1.21) is the least
  diagnostic. The meaningful signals are **8(a)(3) ↑** and **8(a)(5) ↓**.
- The pattern is a property of *which cases coincide with an organizing window*, not of the matching
  algorithm: **cluster** produces essentially the same risk ratios (8(a)(3) 1.57, 8(a)(5) 0.35; see
  CSV), despite matching more cases overall (54,697 vs 45,824).
- "Matched" reflects the current pipeline's filters (date window, region/state/city gate, eligibility).
  Cases that never enter matching for data reasons are handled by the eligible-only cut above.

## Files

- `allegations_matched_vs_unmatched.ipynb` — full analysis (parsing, prevalence, charts, robustness).
- `allegation_prevalence_matched_vs_unmatched.csv` — prevalence + risk ratios for **both methods**
  (fuzzy, cluster) × **both populations** (all CA, eligible-only).
