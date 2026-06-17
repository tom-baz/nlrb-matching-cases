# Step 1 — Coverage Accounting: The Name Data-Flow

*Report for Step 1 of the NLRB evaluation plan (see `../NLRB_evaluation_next_steps.md`). Designed to be quoted in research proposals and conference talks. The full technical trace and per-filter derivations are in `name_data_flow.md` (sections 0–5.4); the reproducible computations are in `explore_case_tables.ipynb` (sections 9–11).*

---

## 1. Why this report exists

The NLRB R↔C linkage project rests on two distinct tasks that need distinct evaluations:

1. **Matching** — linking RC petitions (union-certification elections) to CA charges (unfair labor practice claims) when they refer to the same firm, place, and time window.
2. **Clustering** — resolving the ~334k unique preprocessed company-name strings into firm-level entities.

Before any precision/recall metric is computed, we need to know how many names exist at each pipeline stage and which ones get lost where. Until that figure is transparent, claims like "the cluster method matches well" or "our firm-level panel covers the NLRB universe" cannot be evaluated — readers cannot tell what was inside or outside the scope of the work.

This report closes that question end-to-end.

---

## 2. The pipeline in one diagram

Two distinct downstream pipelines consume the merged parquets — and they don't consume the same ones:

- **Clustering** (`nlrb-blocking/` → `nlrb-clustering-with-LLM/`) reads **only** the two `_ADDRESS` parquets. It needs company names, locations, and the flag/type columns — all of which live in `_ADDRESS`. It never touches the `_final` parquets.
- **Matching** (`nlrb-matching-cases/match_r_to_c_cases.py`) reads **all four** parquets plus the cluster output. The `_final` parquets supply dates (needed for the date-window join) and act as the canonical case-level reference for the inner join.

```
   raw CHIPS / CATS / NxGen
            │
            ▼                          nlrb-creating-files/
   four canonical merged parquets:

     ┌─────────────────────────────────────┐   ┌─────────────────────────────────────┐
     │ merged_R_CASES_final.parquet        │   │ merged_R_CASES_ADDRESS_with_        │
     │   case_number, type,                │   │ union_flag.parquet                  │
     │   date_filed, date_closed           │   │   case_number, company_name,        │
     │   197,253 rows                      │   │   state, city, zip_code, type,      │
     │                                     │   │   is_union_name, is_long_name       │
     │                                     │   │   197,451 rows                      │
     └─────────────────────────────────────┘   └─────────────────────────────────────┘

     ┌─────────────────────────────────────┐   ┌─────────────────────────────────────┐
     │ merged_C_CASES_final.parquet        │   │ merged_C_CASES_ADDRESS_with_        │
     │   case_number, type, date_filed     │   │ union_flag.parquet                  │
     │   1,038,762 rows                    │   │   (same columns as R-side)          │
     │                                     │   │   1,038,762 rows                    │
     └─────────────────────────────────────┘   └─────────────────────────────────────┘
                  │                                          │
                  │                                          │── feeds clustering
                  │                                          │
                  ▼                                          ▼   nlrb-blocking/
                  │                            filter (type ∈ {RC,RD} / CA, drop union /
                  │                            long flag, drop nulls); preprocess names;
                  │                            dedup across R and C
                  │                                          │
                  │                                          ▼
                  │                            334,276 unique preprocessed names
                  │                                          │
                  │                                          ▼   FAISS + char-ngram kNN,
                  │                                          │   threshold-tightening splitter
                  │                            224,767 names in 51,630 blocks
                  │                            109,509 pre-blocking singletons (dropped)
                  │                                          │
                  │                                          ▼   nlrb-clustering-with-LLM/
                  │                            LLM-CER hierarchical clustering
                  │                                          │
                  │                                          ▼
                  │                            cluster_assignments_20260517.csv
                  │                            224,767 rows · 91,120 clusters ·
                  │                            38,892 LLM-singletons
                  │                                          │
                  ▼                                          ▼
                  └────────────────────┬─────────────────────┘
                                       │   nlrb-matching-cases/
                                       │   add_cluster_representatives.py writes a
                                       │   cluster_representative column back to
                                       │   each ADDRESS parquet (cluster mode only)
                                       ▼
                          match_r_to_c_cases.py:
                          inner-join _final ⋈ _ADDRESS on case_number (per side),
                          type filter (RC / CA), flag drop, preprocess, normalize
                          location, equi-join on (company-key, state),
                          city + date-window gates
                                       │
                                       ▼
                          rc_ac_matches.parquet (fuzzy hybrid)         50,472 pairs
                          rc_ac_cluster_matches_20260517.parquet       60,731 pairs
```

The R-side `_final ⋈ _ADDRESS` join has a 198-case asymmetry (R_ADDR has 197,451 cases; R_FINAL has 197,253). 169 of those 198 are RC cases that get dropped at the inner join — a small but real source of matching-stage coverage loss. The C-side is exactly 1:1.

---

## 3. The headline coverage numbers

| Stage | Population | Count | Source file |
|---|---|---:|---|
| R-side case rows | dates + type, post-dedup | 197,253 | `merged_R_CASES_final.parquet` |
| R-side address rows | company + location + flags, post-dedup | **197,451** | `merged_R_CASES_ADDRESS_with_union_flag.parquet` |
| C-side case rows | dates + type, post-dedup | 1,038,762 | `merged_C_CASES_final.parquet` |
| C-side address rows | company + location + flags, post-dedup | **1,038,762** | `merged_C_CASES_ADDRESS_with_union_flag.parquet` |
| RC rows reaching matching | after type filter, flag drop, inner join (R_FINAL ⋈ R_ADDR), empty-key drop | 141,732 | both R-side parquets |
| &nbsp;&nbsp; …actually entering the date-window join | further drop missing/invalid `date_closed` | **141,025** | both R-side parquets |
| CA rows reaching matching | after type filter, flag drop, inner join, empty-key drop | **754,030** | both C-side parquets |
| Unique preprocessed names | universe for blocking | **334,276** | both ADDRESS parquets (post-filter, preprocess, dedup) |
| Names that entered blocking | rows in `blocks.csv` | **224,767** | `blocks.csv` |
| Pre-blocking singletons | never reached clustering | **109,509** | derived |
| Names in multi-name clusters | clustering can bridge synonyms here | 185,875 | `cluster_assignments_20260517.csv` |
| LLM-decided singletons | reached the LLM, judged peerless | 38,892 | `cluster_assignments_20260517.csv` |
| Names appearing on **both** R-side and C-side | ceiling on possible R↔C links at the name level | **46,912** | both ADDRESS parquets (per-side dedup + intersection) |
| Final R↔C pairs (hybrid fuzzy / cluster exact) | the two matching methods being compared | 50,472 / 60,731 | `rc_ac_matches.parquet`, `rc_ac_cluster_matches_20260517.parquet` |

**Clustering and matching consume different subsets of these four files.** Clustering reads only the two `_ADDRESS` parquets (it needs names and flags, both of which live there). Matching reads all four: the `_ADDRESS` parquets supply names and locations; the `_final` parquets supply the dates (driving the date-window gate) and act as the canonical case-level reference for the inner join. In cluster-matching mode, the cluster file's representative is added to the `_ADDRESS` parquet as a `cluster_representative` column by `add_cluster_representatives.py` before the matcher runs. Every count is reproducible from these four parquets plus `blocks.csv`, `cluster_assignments_20260517.csv`, and the LLM-CER batch-state database.

---

## 4. Five findings that change how the project should be framed

### 4.1 Two singleton populations exist — they look the same but mean different things

Of the 334,276 unique preprocessed names, **148,401 (44.4%)** behave like fallback when the cluster method runs: the cluster file gives them no synonym to bridge to. They split into two structurally different populations:

| Population | Count | What happened |
|---|---:|---|
| Pre-blocking singletons | 109,509 (32.8%) | Never reached the LLM. The blocker couldn't find a candidate neighbor for them. |
| LLM-decided singletons | 38,892 (11.6%) | Reached the LLM in a block of 11-15 similar names; the LLM judged them peerless. (Verified end-to-end via `batch_state.db` — all are real clustering decisions, none are pipeline fallback.) |

These two populations need different remediation:
- The pre-blocking-singleton gap is a **blocker-recall** problem. Improving the LLM-CER prompts cannot fix it.
- The LLM-singleton population is a **clustering decision** that could be reviewed (e.g., the consensus-stability extension in Step 6).

Operationally, the fuzzy method's `token_sort_ratio ≥ 82` filter is the only mechanism that can currently reach an R↔C link for these 148,401 names. This is exactly why the hybrid policy (clustering backbone + fuzzy typo-recovery layer) is structurally complementary, not redundant.

### 4.2 R-side and C-side have unequal cluster coverage — a load-bearing asymmetry

At the address-row level, restricted to the matching universe:

| Side | Rows | Multi-name cluster | Fallback | Cluster coverage |
|---|---:|---:|---:|---:|
| R (RC, unflagged) | 142,053 | 86,959 | 55,094 | **61.2%** |
| C (CA, unflagged) | 754,930 | 550,211 | 204,719 | **72.9%** |
| Combined | 896,983 | 637,170 | 259,813 | **71.0%** |

The **11.7-percentage-point gap** is mechanical. CA cases are 5.3× more numerous than RC, so frequent firms (USPS, GM, Walmart, …) appear many times on the C-side and tend to land in large multi-name clusters. The R-side has more rare or one-off establishments in its long tail.

**Why this matters for the project.** The cluster method's coverage ceiling is fundamentally higher on the C-side than on the R-side. Any per-method matching analysis should report cluster-method coverage by side rather than aggregating. Substantive claims about firms that have *only* an RC record (i.e., union elections at firms that have never been ULP-charged) inherit a lower-coverage operating regime than claims about firms with multiple CA charges.

### 4.3 At the name level, only 14% of the universe can possibly produce an R↔C link

Of the 334,276 unique preprocessed names, only **46,912 (14.0%)** appear on both the R-side and the C-side. The rest cannot contribute to an R↔C link no matter how good clustering and matching get:

| Source partition | Names | Share |
|---|---:|---:|
| R-only (RC/RD petitions for firms with no CA charge in the data) | 66,969 | 20.0% |
| C-only (CA charges for firms with no RC petition) | 220,395 | 65.9% |
| **Both** (the matching-relevant universe) | **46,912** | **14.0%** |
| Union | 334,276 | 100% |

**Within the `both` partition, 42.7% of names are still effectively fallback** (14.1% LLM-singleton + 28.6% pre-blocking-singleton). So:
- The **name-level matching-recall denominator should be 46,912**, not 334,276.
- Even within those 46,912, only 57.3% have a real cluster representative; the rest depend on the fuzzy layer or are unrecoverable.
- The **13,417 pre-blocking singletons within the `both` partition** are the load-bearing recall losses — firms where R↔C linkage is in principle possible but where the cluster method cannot help.

### 4.4 Row-level coverage is much better than name-level coverage

Common firms got clustered; long-tail typos and obscure names did not. Reweighting cluster coverage from one-row-per-unique-name (uniform) to row-frequency-weighted (actual matching workload) shifts the picture by **15.5 percentage points**:

| Bucket | Row-level (matching universe) | Name-level (unique names) |
|---|---:|---:|
| `multi_cluster` | **71.0%** | 55.6% |
| `llm_singleton` | 8.5% | 11.7% |
| `pre_blocking_singleton` | 20.5% | 32.8% |

**Why this matters.** The headline "32.8% of unique preprocessed names never entered blocking" figure is the structural coverage gap; the operational coverage gap that affects matching is only 20.5%. The cluster method covers most of the matching workload, even if it leaves a long tail of rare names unclustered.

### 4.5 Drop attribution is fully reconcilable — no hidden losses

Every row dropped between the merged ADDRESS parquets and the matching universe is attributable to a specific filter (full table in `name_data_flow.md` §5.1). The dominant drops, in order:

1. **Type filter** (52,934 R / 267,303 C) — non-RC R-cases and non-CA C-cases are out of scope. Intentional.
2. **Union or long-name flag** (2,124 RC / 14,741 CA after type filter) — intentional but downstream-sensitive.
3. **Inner-join loss** (handled together with #2 in the cascade): 169 of the 198 case numbers that appear in `R_ADDR` but not `R_FINAL` are RC cases lost at the join.
4. **Empty match keys** (468 R / 2,686 C) — small but real; on the C-side the dominant missing field is `city` (2,653), then `company_name` (1,788).
5. **R-only post-load filters** (702 missing `date_closed` + 5 malformed intervals) — the 707-row gap between the headline 141,732 figure and the actual 141,025 entering the join.

No filter contributes a "black-box" drop; every loss has a verified attribution.

---

## 5. What this means for the matching method comparison

The **severity-asymmetry framing** of the evaluation plan (`../NLRB_evaluation_next_steps.md` §1) says catastrophic over-merges dominate downstream damage, so precision matters more than the last points of typo recall. The coverage accounting confirms three things that operationalize that framing:

1. **The cluster + fuzzy pair is structurally complementary, not redundant.** The pre-blocking-singleton pool (109,509 names) is exactly the population where the cluster method has no signal — and exactly the population a high-threshold fuzzy bolt-on can reach. The existing 250-pair audit's fuzzy-only-at-`≥90` cell already shows 100% precision in that regime.
2. **The defensible operational policy is a tiered hybrid**: clustering as the backbone, high-threshold fuzzy (`token_sort_ratio ≥ 90`) as an additive typo-recovery layer, with provenance flags on every accepted link so substantive results can be re-run on nested "core / core+fuzzy / full" samples.
3. **Three reportable caveats belong in any paper using firm-level R↔C linkage:**
   - Only 14% of the unique preprocessed-name universe can in principle produce an R↔C link.
   - Within that 14%, 57.3% of names have a real cluster representative; 42.7% behave like fallback.
   - The R-side has materially lower cluster coverage than the C-side (61.2% vs 72.9% at the row level), so claims about union-organizing firms inherit a slightly lower-coverage regime than claims about ULP-charged firms.

---

## 6. Next steps the evaluation plan can now execute precisely

Steps 2–6 of the evaluation plan are interpretable in light of these counts; the sampling frames, denominators, and ceilings they need are now defined.

| Step | Now-defined input |
|---|---|
| **2** Re-weight existing matching precision | Audit-cell pool sizes (39,738 / 9,688 / 1,046 / 11,305) confirmed; the `both` partition (46,912) anchors the population that matters. |
| **3** Label-free full-file diagnostics | Blocker pair-completeness has its structural ceiling at 224,767 / 334,276 = 67.2%. The existing 82.4% weak-recall figure on the 2,316 fuzzy-found pairs sits above the structural ceiling because frequent firms are over-represented in the fuzzy-found pairs — the diagnostic still flags the blocker as the *biggest* coverage opportunity. |
| **4** Entity-centric clustering benchmark | Sampling frame defined: 334,276 names for the clustering estimator; 46,912 `both` partition for the matching-relevant subset. A single stratified draw (e.g., 200 from `both`, 100 each from R-only and C-only) supplies both estimates. |
| **5** Matching-recall estimation | Conditional-recall denominator: the 46,912 `both` partition. The 13,417 pre-blocking-singleton-in-both names are the explicitly labeled load-bearing recall losses. |
| **6** Consensus / stability confidence (optional) | The 38,892 LLM-singletons are the population most likely to flip across re-runs; if a confidence score is needed, that's where it pays. |

---

## 7. Method note

All counts are reproducible from a single notebook (`explore_case_tables.ipynb`) against four inputs:

- `merged_R_CASES_ADDRESS_with_union_flag.parquet`, `merged_C_CASES_ADDRESS_with_union_flag.parquet`
- `merged_R_CASES_final.parquet`, `merged_C_CASES_final.parquet`
- `cluster_assignments_20260517.csv`
- `nlrb-blocking/data/output/blocks.csv` and `nlrb-clustering-with-LLM/results/batch_state.db`

Per-filter drop logs (Gap A), row-level cluster classification (Gap B), all-singleton-block provenance (Gap C), and the R/C source attribution (Gap D) are each closed by a dedicated notebook section (§§9-11) and a corresponding sub-section in `name_data_flow.md` (§§5.1-5.4).

The principle that distinguishes this audit from a benchmark: we are evaluating a data-construction process, not an algorithm. The contribution is showing how reliably a messy administrative-data pipeline turns name strings into firm entities, and what that reliability implies for firm-level inference downstream. The numbers above are the load-bearing inputs to every subsequent evaluation step.

---

## See also

- `../NLRB_evaluation_next_steps.md` — six-step evaluation plan that this report enables.
- `name_data_flow.md` — full technical reference, line-by-line trace from raw NLRB filings to matched pairs.
- `explore_case_tables.ipynb` — reproducible computations for every number cited here.
- Stage docs: `nlrb-creating-files/`, `nlrb-blocking/`, `nlrb-clustering-with-LLM/` for upstream pipelines.
- `IC2S2 Abstract.docx` — original project framing for the firm-aggregation claim.
