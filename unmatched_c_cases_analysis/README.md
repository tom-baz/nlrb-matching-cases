# Unmatched CA Cases — Coverage, Diagnosis & Next Steps

**Session date:** 2026-06-15
**Author:** Tom Baz (with Claude Code)
**Scope:** Why do most CA-type C Cases not match any RC R Case? Is it substantive or a matching failure? What can we recover, and how?

This folder holds everything produced in that session. The data files (`merged_*.parquet`) and the matching code (`match_r_to_c_cases.py`) stay in the **project root**; this folder contains only the new analysis notebook and its outputs.

---

## 1. The notebook: `unmatched_c_cases_analysis.ipynb`

### What it does

It classifies **every** CA-type C Case into a clean, exhaustive taxonomy, **for both matching methods** (fuzzy/hybrid on `company_name`, and cluster/exact on `cluster_representative`):

| Category | Definition |
|----------|------------|
| **Matched** | ≥1 identity-candidate RC whose active window `[date_filed, date_closed]` covers the CA's filing date |
| **Unmatched — time-window** | An establishment-identity match (company + state + city + NLRB region) exists, but **no** candidate RC's window covers the CA date |
| **Unmatched — no identity** | Entered matching, but **no** identity-candidate RC at all |
| **Excluded — pre-filter** | Never entered matching (no address, union/long name, missing company/city/state, name-is-a-case-number) |

The first three partition the *eligible* CA universe; the fourth accounts for the gap to all CA cases.

### How (method)

The pipeline in `match_r_to_c_cases.py` applies the date-window filter as the **last** step of both passes (`_apply_date_filter`). The notebook **monkeypatches that filter to a pass-through**, re-runs matching to obtain every *identity candidate* (location agrees, dates ignored), then **re-applies the date test in-notebook**. This is what lets us separate "failed on dates" from "failed on identity" — a distinction that **cannot** be recovered from the saved match files, because those only contain pairs that already passed the date gate.

A **cross-check** confirms the derived *Matched* set exactly equals the distinct CA in the committed `rc_ac_matches.parquet` / `rc_ac_cluster_matches_20260517.parquet` (0 discrepancy both methods), so the approach faithfully reproduces the real pipeline.

The notebook then adds two diagnostic layers:
- **Step 7 — Allegation profile** (matched vs unmatched), to test substance vs. failure.
- **Step 8 — Recall bounds**: a relax-the-gates ladder, a name-only ceiling, and a suspected-false-negative pool.

### Running it

Launch the notebook **from inside this folder**. Cell 1 auto-locates the project root (the parent containing `match_r_to_c_cases.py`), reads the parquets from there, and writes all outputs back into this folder. The fuzzy/hybrid pass takes ~10 minutes; the cluster pass is fast.

### Output files in this folder

| File | Contents |
|------|----------|
| `unmatched_ca_{fuzzy,cluster}_summary.csv` | One-row decomposition (counts per category) |
| `unmatched_ca_{fuzzy,cluster}_time_window.csv` | Each time-window-failed CA with its nearest candidate RC and `days_outside_window` |
| `unmatched_ca_{fuzzy,cluster}_no_identity.csv` | Case numbers of CA cases with no identity candidate |
| `suspected_false_negative_ca_{fuzzy,cluster}.csv` | §8(a)(3)-only, no-identity CA whose company name appears in some RC — the priority manual-audit pool |

---

## 2. Findings

### 2.1 Coverage decomposition

Denominators: **771,459** CA total → **754,030** eligible (17,429 = 2.3% excluded pre-filter).

| Category | Fuzzy (hybrid) | Cluster (exact) |
|---|---|---|
| Matched | 45,824 (6.1% of eligible) | 54,697 (7.3%) |
| **Unmatched — total** | **708,206 (93.9%)** | **699,333 (92.7%)** |
| → time-window | 146,964 (19.5%) | 181,546 (24.1%) |
| → no identity | 561,242 (74.4%) | 517,787 (68.7%) |

The more interpretable number is the **RC-side rate**: **18% (fuzzy) / 21% (cluster)** of RC petitions drew a contemporaneous employer ULP charge — this is the quantity the labor literature studies (employer illegality during organizing).

### 2.2 Time-window failures are mostly *far* misses

Median `days_outside_window` ≈ 600 days; p90 ≈ 4,300 days. The majority are CA charges filed **after the RC case closed** (fuzzy: 87k after vs 35k before; cluster: 105k vs 41k). **Conclusion:** modestly widening the date window would recover few — the gap is structural, not a near-miss tolerance issue. (This directly motivates the post-certification idea in §3.3.)

### 2.3 Substance vs. failure — the low match rate is mostly *real*

Allegation profile (share of CA carrying each NLRB §8(a) subsection):

| Allegation | Unmatched | Matched |
|---|---|---|
| §8(a)(5) refuse-to-bargain | **28%** | **7.6%** |
| §8(a)(5)-only (not §8(a)(3)) | 23% | 4.6% |
| §8(a)(1) coercion | 70% | 85% |
| §8(a)(3) discrimination | 21% | 27% |

§8(a)(5) refusal-to-bargain **requires a pre-existing certified union**, so it cannot co-occur with a concurrent RC petition — and it is ~4× concentrated in the unmatched set. The matched set carries the **organizing-campaign signature** (§8(a)(1)/§8(a)(3)). The low CA match rate is therefore largely **substantive**: most ULP charges genuinely have no contemporaneous RC drive at the same establishment.

### 2.4 Recall bounds — where matching *is* leaving cases on the table

Relax-the-gates ladder — currently *no-identity* CA recovered by dropping a gate (exact name):

| Gate dropped | Fuzzy recovered | Cluster recovered |
|---|---|---|
| **city** (keep name+state+region) | **39,406** | **66,788** |
| **region** (keep name+state+city) | 6,398 | 10,586 |
| name+state (drop both) | 57,932 | 94,271 |
| **name-only ceiling** | 191,020 | 256,842 |

**Key findings:**
- **City is the dominant recall blocker — ~6× more than region.** The strict NLRB-region equi-key is fine; the city gate is too strict (multi-site employers in one region, suburb-vs-metro naming, OCR variants).
- **Name-only ceiling** splits the no-identity bucket: ~34% (fuzzy) / ~50% (cluster) have a company name appearing in *some* RC (loose, overstated by common names); the remaining ~66% / ~50% appear in **no** RC → substantively unmatchable.
- **Priority audit pool:** §8(a)(3)-only (discrimination → implies an active campaign) no-identity CA whose name appears in RC = **33,319 (fuzzy) / 43,715 (cluster)** likely true misses (saved to CSV).

### 2.5 Important correction — ZIP is for *precision*, not recall

ZIP code is *finer* than city, so adding it as another required key **cannot recover** the city-blocked cases and would only drop some. The city-blocked cases are recovered by **loosening** location (fuzzy city, metro/county normalization, geocoding/proximity), or by using ZIP as an **alternative** OR-key ("city OR zip agrees"). ZIP's proper role is the **relax-then-disambiguate** pattern: drop city to add candidates, then use ZIP as a *soft* filter to remove different-establishment false positives — soft because the HQ-vs-establishment reliability issue means a true same-workplace pair can have mismatched ZIPs.

---

## 3. Recommendations / next steps

### 3.1 Fix city/establishment resolution (the recall lever)
Don't chase region. Test, in order:
1. Lower the fuzzy-city threshold and/or add metro/county normalization.
2. Geocode city (or ZIP) and match on geographic proximity.
3. Use ZIP as an **OR-key** and as a soft precision filter after relaxing city.
Re-run the relax-the-gates ladder after each change to see how much of the ~39k/67k city-gap converts to real matches.

### 3.2 Manual recall audit
Hand-review a sample of `suspected_false_negative_ca_{fuzzy,cluster}.csv` to estimate the true false-negative rate. This pairs with the existing precision work (`analyze_evaluation_results.ipynb`) to give both precision **and** recall on a defensible footing. It also tells us how many of the city-blocked candidates are true same-workplace matches vs. different stores.

### 3.3 New match channel — post-certification §8(a)(5) (structural, validated)
The §8(a)(5) concentration in the unmatched set points to a missing, *legitimate* match channel: refusal-to-bargain charges occur **after** a union wins, outside the current `[date_filed, date_closed]` window.

**Design:**
- For each RC with `union_won = true` (from the **`ELECTIONS`** table), add a forward window **anchored on `ELECTIONS.election_date`** — `[election_date, election_date + ~12 months]` (the certification-year bargaining duty; test 12/18/24-month sensitivity).
- Match only **§8(a)(5)** charges (co-listed §8(a)(1) fine) at the same establishment in that window.
- Handle the 1:many RC→ELECTIONS relationship: an RC qualifies if ≥1 unit won; anchor on the won unit's `election_date`. Establishment-level match, not unit-level (note as a simplification).
- Tag as a **distinct match type** (`post_certification_8a5`) — "resistance after winning" is analytically separate from "resistance during organizing"; keep them separate. Make it additive and dedup against in-window matches.

**Built-in validation:** run the same forward window over `union_won = false` RCs as a control. Expect §8(a)(5) yield strongly enriched for won RCs and near-zero for lost RCs (no certification → no bargaining duty). If lost RCs also yield §8(a)(5), that flags false positives / pre-existing unions — tighten before trusting the channel. `pct_votes_for` / `union_representation` enable a dose-response check.

**Dependency:** the `ELECTIONS` parquet is not yet in the project folder — needs to be located/added before implementation.

---

## 4. Cross-references
- Project memory: `unmatched-ca-diagnosis.md`, `zip-provenance-and-merge.md`, `multi-r-per-c-investigation.md`, `cluster-coverage-and-preprocessing.md`.
- Pipeline: `../match_r_to_c_cases.py`; schema: `../schema/nlrb_schema_diagram.md`; method comparison: `../compare_matching_methods.ipynb`.
