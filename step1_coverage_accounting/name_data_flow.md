# Company-Name Data Flow — End-to-End

*A stage-by-stage trace of how a company name moves from raw NLRB filings into the final R↔C match outputs. Built to underpin **Step 1 — Coverage Accounting** from `../NLRB_evaluation_next_steps.md`. Every count in this document is cited to its source file or script; numbers that disagree across docs are flagged in §6.*

---

## 0. Pipeline at a glance

```
┌────────────────────────────────────────────────────────────────────────────┐
│  raw CHIPS / CATS / NxGen tables                                          │
│           │                                                                │
│           ▼   nlrb-creating-files/                                         │
│  per-system R/C/ADDRESS parquets ──► merge ──► union-flag                  │
│           │                                                                │
│           ▼                                                                │
│  merged_R_CASES_ADDRESS_with_union_flag.parquet         (197,451 rows)     │
│  merged_C_CASES_ADDRESS_with_union_flag.parquet       (1,038,762 rows)     │
│  merged_R_CASES_final.parquet  /  merged_C_CASES_final.parquet            │
└─────────────────────────┬──────────────────────────────────────────────────┘
                          │
        ┌─────────────────┴──────────────────────────┐
        │                                            │
        ▼                                            ▼
  nlrb-blocking/                              nlrb-matching-cases/
  preprocess → dedup → embed → kNN union      (same preprocessor, applied
       │                                       per-row on each address table)
       ▼
  334,276 unique preprocessed names
       │
       │   FAISS-IP   +   char-ngram TF-IDF kNN   →   union of edges
       │
       ▼
  blocks.csv (51,630 blocks, 224,767 names; ~109,509 pre-blocking singletons
              are silently dropped — they have no row in blocks.csv)
       │
       ▼   nlrb-clustering-with-LLM/
  hierarchical NRS → LLM → CMR  (block-by-block, S_S=12, MAX_BLOCK_SIZE=1000)
       │
       ▼
  cluster_assignments_20260517.csv
      224,767 rows · 91,120 global clusters · 38,892 LLM-decided singletons
       │
       ▼   nlrb-matching-cases/add_cluster_representatives.py
  ADDRESS parquets gain a `cluster_representative` column
  (cluster lookup hit-rate ≈ 224,767 / 334,276 of unique preprocessed names;
   misses fall back to the preprocessed name itself)
       │
       ▼   nlrb-matching-cases/match_r_to_c_cases.py
  RC × CA equi-join on (company-key, state) + city gate + date window
       │
       ▼
  rc_ac_matches.parquet                   (hybrid fuzzy)   50,472 pairs
  rc_ac_cluster_matches_20260517.parquet  (cluster exact)  60,731 pairs
```

The two address parquets are the **only** company-name inputs to the entity-resolution work; everything else (R_CASES_final, C_CASES_final, the elections table) supplies dates, case types, or downstream joins, never names. This is why the user-supplied summary calls them the "basic data files."

---

## 1. Stage 1 — `nlrb-creating-files/` : raw → unified parquets

**Folder layout.**
```
nlrb-creating-files/
├── CHIPS/        ── R_CASES_ADDRESS_CHIPS.ipynb, C_CASES_ADDRESS_CHIPS.ipynb, *_DATA/
├── CATS/         ── R_CASES_ADDRESS_CATS.ipynb,  C_CASES_ADDRESS_CATS.ipynb,  *_DATA/
├── NxGen/        ── R_CASES_ADDRESS_NxGen.ipynb, C_CASES_ADDRESS_NxGen.ipynb, *_DATA/
├── Merge_files/  ── merge_R_CASES_ADDRESS.ipynb, merge_C_CASES_ADDRESS.ipynb,
│                    flag_union_names_v2.ipynb, + merged_*.parquet outputs
├── nlrb_schema_diagram.md / .html
└── fmcs_schema_diagram.md / .html
```

### 1.1 Per-system extracts

Each filing system has parallel notebooks that read its raw tables and emit a per-system address parquet.

| System | Raw source | R-side notebook | C-side notebook | Output (address) | Rows |
|---|---|---|---|---|---:|
| **CHIPS** (1984–2001) | `chips_master_self_made.pkl` (114,606 R cases), `cases_names_chips.parquet` (654,975 rows), `cases_city_zip_chips.parquet` | `CHIPS/R_CASES_ADDRESS_CHIPS.ipynb` (lines 507–531) | `CHIPS/C_CASES_ADDRESS_CHIPS.ipynb` | `r_cases_address_chips.parquet` (115,171 rows, 99.5% non-null company_name) / `c_cases_address_chips.parquet` (509,002 rows, 99.4% non-null) | — |
| **CATS** (1999–2011) | CATS raw extracts | `CATS/R_CASES_ADDRESS_CATS.ipynb` | `CATS/C_CASES_ADDRESS_CATS.ipynb` | `R_CASES_ADDRESS_CATS.parquet` (74,095 rows, 99.9% non-null) / `C_CASES_ADDRESS_CATS.parquet` (320,562 rows, 99.99% non-null) | — |
| **NxGen** (2011–) | NxGen `Case Name` field | `NxGen/R_CASES_ADDRESS_NxGen.ipynb` | `NxGen/C_CASES_ADDRESS_NxGen.ipynb` | `R_CASES_ADDRESS_NxGen.parquet` (35,445 rows, 100% non-null; adds `zip_reliability`, `data_notes`) / `C_CASES_ADDRESS_NxGen.parquet` (243,846 rows, 100% non-null) | — |

**Per-system company-name column.** Each notebook pulls the company name from the raw source verbatim — CHIPS `Employer`, CATS source-table column, NxGen `Case Name` — and writes it to a column called `company_name`. **No lowercasing, stripping, or normalization is applied at this stage.** The string is the raw record exactly as it sits in the source system. (Surprise on NxGen: 20.1% of zip codes flagged "potentially_hq" — for 3,308 cases the employer's recorded state disagrees with the regional jurisdiction, because the recorded address is the HQ rather than the establishment. The `zip_reliability` column documents this but doesn't alter the name.)

### 1.2 Merging the three systems

`Merge_files/merge_R_CASES_ADDRESS.ipynb` and `merge_C_CASES_ADDRESS.ipynb` concatenate the three per-system address parquets (priority order **NxGen > CATS > CHIPS** when a `case_number` appears in more than one system), then:
- Standardize `case_number` to `XX-YY-ZZZZZZ`.
- Standardize `state` to 2-letter codes (CATS was largely full names).
- Derive a `type` column (RC, RD, CA, CB, etc.) from the case number.
- Drop duplicates by `case_number`, keeping the higher-priority source.

| Address table | Pre-dedup rows | Post-dedup rows | Drop count |
|---|---:|---:|---:|
| R cases | 224,711 | **197,451** | 27,260 (CHIPS 56.9%, CATS 25.2%, NxGen 18.0%) |
| C cases | 1,073,410 | **1,038,762** | 34,648 (CHIPS 46.5%, CATS 30.0%, NxGen 23.5%) |

**Output columns at this point**: `case_number, company_name, state, city, zip_code, data_source, type` — names still in their raw form.

### 1.3 Union-flag pass

`Merge_files/flag_union_names_v2.ipynb` reads the merged address parquets and adds two columns:
- `is_union_name` (bool) — fired by ~50 regex phrase patterns + 36 union acronyms (`local [number]` is the dominant trigger; about 40% of all flags).
- `matched_union_terms` (list[str]) — which patterns hit.
- Also added: `is_long_name` (>100 chars or >15 words) — used as a sanity filter later.

| Address table | `is_union_name = True` | `is_long_name = True` |
|---|---:|---:|
| R cases | 2,671 (1.35%) | 374 (0.19%) |
| C cases | 180,624 (17.39%) | 23,520 (2.26%) |

The flagger uses **case-insensitive regex** but **does not modify the `company_name` string itself** — it only adds the two flag columns. Row counts are unchanged.

**Final outputs from this stage** (used by every downstream stage):
- `merged_R_CASES_ADDRESS_with_union_flag.parquet` — 197,451 rows
- `merged_C_CASES_ADDRESS_with_union_flag.parquet` — 1,038,762 rows
- `merged_R_CASES_final.parquet`, `merged_C_CASES_final.parquet` (case-level: type and dates only)
- `merged_elections_final.parquet` (not used in matching)

---

## 2. Stage 2 — `nlrb-blocking/` : ADDRESS parquets → `blocks.csv`

This stage extracts unique preprocessed names from the two address parquets, builds two candidate-edge graphs (semantic embeddings + character n-grams), unions them, and assembles disjoint, size-capped blocks of similar names.

**Folder layout.**
```
nlrb-blocking/
├── scripts/         02_candidates_embedding.py, 03_candidates_charngram.py,
│                    04_union_candidates.py, 05_assemble_blocks.py, 06_evaluate.py
├── src/             channels/embedding_ann.py, channels/char_ngram_knn.py,
│                    block_assembly.py, evaluation.py, preprocessing_v3.py
├── data/input/      (reserved)
├── data/output/     candidates_*.parquet, blocks.csv, evaluation_report.md
├── lsh_results/     embeddings.npy, company_names.pkl   ← INPUTS to active pipeline
├── embeddings_cache/  embeddings_cache.pkl              ← alternate form, same vectors
├── legacy/          older LSH+mutual-kNN attempt + generate_embeddings_openai_fixed.py
├── diagnostics/     analysis & labeling helpers
├── README.md, blocking_strategy.md, session_summary_2026-04-14.md
```

### 2.1 The preprocessing + dedup step (the place names first turn into unique strings)

The unique preprocessed name list `lsh_results/company_names.pkl` is built **outside the active scripts**, by `legacy/generate_embeddings_openai_fixed.py` (lines 49–126). This is the authoritative point where raw `company_name` strings become the universe of names that the rest of the pipeline operates on:

1. Read both `merged_*_ADDRESS_with_union_flag.parquet` files (lines 58–59).
2. **Filter rows** (lines 75–96):
   - drop `is_union_name == True`
   - drop `is_long_name == True`
   - R-side: keep `type ∈ {RC, RD}`; C-side: keep `type == CA`
   - drop null `company_name`
3. **Preprocess** each surviving name (lines 103–110): `preprocess_employer()` from `preprocessing_v3.py` (10-stage cleanup — OCR fixes, DBA/slash handling, digit/local-number stripping, stop-word removal with hyphen guards, symbol normalization), then `standardize_company_name()` (canonical replacement for USPS / GM / Kaiser / Ford / Red Cross).
4. **Deduplicate across R and C** (lines 113–122): concatenate both sides, take `unique()`. Result: **334,276 unique preprocessed names** (this is the canonical figure cited by `evaluation_report.md` line 61 for the legacy block-size baseline, and by `clustering_results_table.md` line 17).
5. Embed each unique name with `text-embedding-3-large` (3,072-d, L2-normalized) → `embeddings.npy` (334,276 × 3,072 float32) and the parallel `company_names.pkl`.

> **Source attribution is discarded at the dedup step.** A name that appears in both R-side and C-side records becomes one row with no R/C tag. The "source" column in some downstream tables is therefore reconstructed by re-joining on the preprocessed name, not carried through.

### 2.2 Active blocking pipeline

| Script | Reads | Writes | What it does |
|---|---|---|---|
| `scripts/02_candidates_embedding.py` | `lsh_results/embeddings.npy`, `company_names.pkl` | `data/output/candidates_embedding.parquet` | FAISS `IndexFlatIP` exact-cosine kNN, K=50, threshold ≥ 0.65 → edges `(name_a, name_b, score, channel='embedding')` |
| `scripts/03_candidates_charngram.py` | `lsh_results/company_names.pkl` | `data/output/candidates_charngram.parquet` | TF-IDF on char_wb 3–4-grams (min_df=2), L2-normalized; brute-force kNN, K=50, threshold ≥ 0.60 |
| `scripts/04_union_candidates.py` | both candidate parquets | `data/output/candidates_union.parquet` | concatenate, collapse duplicate (name_a, name_b), label channel `char_ngram;embedding` if both fired |
| `scripts/05_assemble_blocks.py` | `candidates_union.parquet`, `company_names.pkl` | `data/output/blocks.csv` | connected components at the global threshold; recursive threshold-tightening splitter on oversized components (0.68 → 0.95); weight-greedy capped union-find fallback; **singletons excluded** (`EXCLUDE_SINGLETONS=True`) |
| `scripts/06_evaluate.py` | the above + a fuzzy-found weak-recall proxy + legacy baseline | `data/output/evaluation_report.md` | block-size distribution, weak recall on 2,316 fuzzy-found pairs |

**Key params**: BLOCK_SIZE_CAP=200, embedding K=50/τ=0.65, char-ngram K=50/τ=0.60.

### 2.3 `blocks.csv` — schema and counts (from `evaluation_report.md`)

| Column | Meaning |
|---|---|
| `block_id` | sequential int |
| `company_idx` | row index into `company_names.pkl` (i.e. the canonical name-id) |
| `company_name` | preprocessed name string |
| `block_size` | size of the block (≤ 200) |

| Metric | Value |
|---|---:|
| Total blocks | **51,630** |
| Names placed in non-singleton blocks | **224,767** |
| Min / p50 / p95 / p99 / max block size | 2 / 3 / 12 / 31 / 197 |
| Blocks at the 200-cap | 0 |
| Singleton rows emitted | 0 (excluded by design) |
| Total candidate edges (union) | 4,475,697 (embedding 1.91M + char-ngram 1.71M, overlap 0.86M) |
| Weak-recall proxy: 2,316 fuzzy-found pairs co-blocked | **1,909 / 2,316 = 82.4%** (legacy baseline: 0%) |

### 2.4 Pre-blocking singletons — the critical coverage gap

The blocking pipeline **silently drops** names that the connected-components + threshold-tightening passes leave with no edges above the cap-respecting threshold. Those names are not written to `blocks.csv`.

**Count.** `334,276 (unique preprocessed names) − 224,767 (in blocks.csv) = **109,509 pre-blocking singletons**.* These never enter clustering, never enter the cluster file, and at matching time fall back to the preprocessed name as their own cluster representative (see §4.2). This is the population the evaluation plan refers to as the "names that can never be aggregated" — the hard ceiling on firm-level coverage.

> The legacy comparison in `evaluation_report.md` lists 177,652 singletons under the old LSH pipeline (177,652 + 156,624 = 334,276). The new pipeline cuts the singleton pool from 177,652 to ~109,509 — a clear gain — but does not eliminate it.

---

## 3. Stage 3 — `nlrb-clustering-with-LLM/` : `blocks.csv` → `cluster_assignments_20260517.csv`

LLM-CER (Fu et al. 2025) hierarchical clustering applied block-by-block. Treats blocking output as fixed and does not attempt cross-block merges.

**Folder layout.**
```
nlrb-clustering-with-LLM/
├── config.py                 S_S=12, S_D=4, MAX_BLOCK_SIZE=1000,
│                             MODEL_NAME='gpt-5.4-mini', REASONING_EFFORT='low'
├── run_full_pipeline.py      orchestrator (process_single_block)
├── core/                     nrs_stage.py, cmr_stage.py, cluster_tracker.py,
│                             llm_engine.py, data_models.py
├── pipeline_helpers.py
├── export_cluster_assignments.py        results JSONs → CSV
├── analyze_clustering.py, analyze_results.py, check_cluster_of_blocks_results.ipynb
├── embeddings_cache.pkl      (4.1 GB; same vectors as Stage 2's lsh_results/)
├── blocks_merged.csv         input — 224,767 records, post-merge into ~15,764 bins
└── results/blocks_<run_id>/block_<id>.json
```

### 3.1 Input handling — what enters and what's filtered

- The cluster pipeline reads **`blocks.csv` (or `blocks_merged.csv`, a small-block-merging optimization that bins blocks of size 2–11 into ~size-12 bins to amortize LLM cost).** Same 224,767 names, just grouped into 15,764 bins instead of 51,630 raw blocks.
- **Names are taken as-is** from blocking; no further dedup or normalization.
- Blocks with `block_size > MAX_BLOCK_SIZE = 1000` are **filtered out** in `load_and_filter_data()` (`run_full_pipeline.py:335`). For the current run, no such blocks exist (max block size is 197 per `evaluation_report.md`), so this guard is dormant — historically it was the mechanism that excluded the "mega-block 0" (~50K records) from the older legacy pipeline, which is the source of the `CLAUDE.md` warning.
- `EXCLUDE_SINGLETONS=True` does nothing here because blocking already excludes singletons.

### 3.2 The clustering algorithm (data-flow view only)

For each block:
1. **NRS (Next Record Set)**: partition block records into ~`S_S=12`-sized record sets via k-means on embeddings, ordered by a similarity chain.
2. **LLM call** on each record set → initial clusters (a `ClusteringResult` per set).
3. **CMR (Cluster Merge & Rotation)**: nearest-to-centroid representative per cluster → new record sets → LLM → merge results into `ClusterTracker`. Repeat hierarchically. Sub-`MIN_BATCH_SIZE=6` sets accumulate in `BatchAccumulator` before being sent.
4. **Exit**: two consecutive all-singleton levels OR kNN-verification finds no merges.
5. `ClusterTracker.reconstruct_final_partition()` writes `final_clusters: List[List[company_idx]]` to `results/blocks_<run_id>/block_<id>.json`.

### 3.3 Output construction — `export_cluster_assignments.py`

1. Read `blocks_merged.csv` (all 224,767 records).
2. Query `results/batch_state.db` (SQLite) for the result-file path of each completed block.
3. For each block JSON, read `final_clusters` and tag every `company_idx` with an in-block `cluster_id` (0, 1, 2, …).
4. **Left-join back** onto the full input — every input row gets a row in the output, even if its block wasn't (or hasn't yet been) processed.
5. **Unmatched records** (none in the current 2026-05-17 run, but the codepath exists) get auto-assigned a singleton cluster within their block via `groupby([block_id]).cumcount()`.
6. Add derived columns: `global_cluster_id = f"{block_id}_{cluster_id}"`, `cluster_size`, `is_singleton`.

### 3.4 `cluster_assignments_20260517.csv` — verified counts (queried 2026-06-01)

| Metric | Value |
|---|---:|
| Total rows (= unique preprocessed names that entered blocking) | **224,767** |
| Unique `global_cluster_id` | **91,120** |
| `is_singleton = 1` rows (LLM-decided singletons inside processed blocks) | **38,892** |
| `cluster_size > 1` rows (in a multi-name cluster) | **185,875** |
| Avg names per multi-name cluster | (224,767 − 38,892) / (91,120 − 38,892) ≈ **3.56** |
| Columns | `block_id, company_idx, company_name, block_size, merge_group, original_block_ids, cluster_id, global_cluster_id, cluster_size, is_singleton` |

**Important:** the file has **no `source` column**, so R-side vs C-side membership cannot be read off the cluster file alone — it must be reconstructed by joining the preprocessed name back onto the two ADDRESS parquets.

### 3.5 Known gotchas (from `CLAUDE.md`)

- **Cache mismatch:** `embeddings_cache.pkl` is keyed on the `blocks.csv` names. Any name not in that exact set requires an OnDemand OpenAI call. Cache vectors must be L2-normalized before insertion.
- **`Config.validate()`** asserts `DATA_FILE` exists; ancillary scripts must avoid calling it or validate manually.
- **Mega-block 0** of ~50K records (legacy pipeline artifact) is skipped by `MAX_BLOCK_SIZE`. Not relevant to the 2026-05-17 run because the new blocking pipeline never produces a block > 200.
- **`requirements.txt`** is UTF-16-encoded.
- **Two-consecutive-all-singleton exit**, not one. kNN verification can re-extend the hierarchy.

---

## 4. Stage 4 — `nlrb-matching-cases/` : address tables + clusters → R↔C pairs

### 4.1 Preprocessing (the same code, re-applied at matching time)

Two modules used together everywhere a company name is touched:

- **`preprocessing_v3.py :: preprocess_employer(name)`** — 10-stage normalizer:
  - OCR leading-zero fix, NFKD-to-ASCII, lowercase + strip
  - DBA removal (`d/b/a`, `d.b.a.`, `dba`, "doing business as")
  - Slash abbreviations (`a/k/a` → `aka`, `f/k/a` → `fka`, `c/o` removed)
  - Slash → space
  - `local [number]` / `no. [number]` removal
  - 2+ consecutive digits stripped, orphan hyphens cleaned
  - Corporate-term normalization
  - Stop-word removal with **hyphen guards** (LLC, Inc, Corp, …; preserves "co-op")
  - `&` → `and`, `bros` → `brothers`, punctuation removed
  - Whitespace collapsed
- **`name_standardization.py :: standardize_company_name(preprocessed_name)`** — canonical-form replacement for 5 high-frequency firms (USPS, GM, Kaiser Permanente, Ford Motor, American Red Cross). Evidence counts: USPS 2,150 names; GM 487; Kaiser 436; Ford 218; Red Cross 270.

The order is always **`preprocess_employer` → `standardize_company_name`**. This is the canonical preprocessing pipeline; it's applied in (a) blocking's name-list build, (b) `add_cluster_representatives.py`, and (c) `match_r_to_c_cases.py`.

### 4.2 `add_cluster_representatives.py` — joining clusters to the address tables

| What | Where |
|---|---|
| Inputs | `cluster_assignments_20260517.csv`, both `merged_*_ADDRESS_with_union_flag.parquet` |
| Rule for picking a representative | **Shortest name per cluster** (line 40): `.sort_values('company_name', key=lambda s: s.str.len()).drop_duplicates(subset='global_cluster_id', keep='first')`. |
| Preprocessing re-applied | Yes — `preprocess_name()` (lines 21–25) calls `preprocess_employer` then `standardize_company_name` on every input address-table row before joining to the cluster file. |
| Fallback when no cluster match | The preprocessed name itself becomes the representative (line 82). |
| Output | Adds a `cluster_representative` column to both ADDRESS parquets (line 90). Reports cluster-match rate on line 87. |

This is where the ~109,509 pre-blocking singletons re-enter the pipeline as themselves: they have no row in `cluster_assignments_20260517.csv`, the lookup misses, and the fallback writes their preprocessed name into `cluster_representative`. They will participate in matching as a cluster-of-one.

> **Severity flag (see `../NLRB_evaluation_next_steps.md` §3).** "Shortest name" is the most collision-prone selection policy possible (`abc inc`, `the company`, single-word marks). Two genuinely different clusters that share a short representative are **silently linked downstream** at matching even though the cluster file kept them separate. Step 1's coverage table is the right place to also surface the size distribution of `cluster_representative` collisions across clusters.

### 4.3 `match_r_to_c_cases.py` — the matching pipeline

**CLI knobs** (lines 786–832): `--match-mode {exact|fuzzy|hybrid}` (default hybrid), `--fuzzy-threshold` (default 82), `--city-threshold` (default 85), `--company-column` (default `company_name`; set to `cluster_representative` for cluster mode), `--output-prefix`.

**Load and filter** (lines 134–237):
1. Read four parquets: `merged_R_CASES_final`, `merged_R_CASES_ADDRESS_with_union_flag`, `merged_C_CASES_final`, `merged_C_CASES_ADDRESS_with_union_flag`.
2. Rename `case_number` → `r_case_number`/`c_case_number` if needed.
3. **Type filter**: keep `type == 'RC'` on R-side; `type == 'CA'` on C-side.
4. Deduplicate address tables on case number.
5. **Drop rows** flagged `is_union_name == True` or `is_long_name == True`.
6. Join case to address (1:1 on case_number).
7. Drop rows where `company_name` is actually a case-number string.
8. Preprocess the `--company-column` value (lines 210–211 — same two-stage pipeline).
9. Normalize `state` and `city`: lowercase, strip, drop punctuation, collapse whitespace.
10. Drop rows missing company / state / city (lines 218–237).
11. **Drop R cases with missing `date_closed`** (the date-window filter requires both endpoints).

**Exact pass** (lines 322–392):
- Equi-join on `(match_company, match_state)` in 5,000-row chunks.
- City gate: exact normalised city match accepted; otherwise `fuzz.ratio ≥ city_threshold` required.
- Date gate: keep rows where `c.date_filed ∈ [r.date_filed, r.date_closed]`.
- Output rows tagged `match_method='exact'`, `fuzzy_score=100.0`.

**Fuzzy pass** (lines 398–571, fuzzy/hybrid only):
- Block on `match_state`.
- For each state, get unique R-side names → `rapidfuzz.process.extract(token_sort_ratio, score_cutoff=fuzzy_threshold)` against unique C-side names.
- Expand back to case rows, apply same city gate and date gate.
- In hybrid mode, fuzzy runs on **all** RC cases (not just those with no exact hit) and pairs already found by exact are deduplicated, so fuzzy is strictly additive.

**Output schema** (`rc_ac_matches.parquet`, lines 307–316):
```
r_case_number, c_case_number,
r_date_filed, r_date_closed, c_date_filed,
r_company_name, r_state, r_city,
c_company_name, c_state, c_city,
match_company_r, match_company_c,
match_state_r, match_state_c,
match_city_r, match_city_c,
match_method, fuzzy_score
```

`_summary.txt` reports RC count, RC-with-≥1-match count, CA count, CA-with-≥1-match count, total pairs, per-method breakdown, fuzzy-score quantiles, matches-per-case distribution.

### 4.4 Numeric checkpoints at the matching stage

From `matching_summary.txt` (hybrid fuzzy mode, default `company_column=company_name`):

| Metric | Value |
|---|---:|
| RC cases in dataset | **141,732** |
| RC cases with ≥ 1 CA match | 25,867 (18.3%) |
| CA cases in dataset | **754,030** |
| CA cases matched to ≥ 1 RC | 46,573 (6.2%) |
| Total match pairs | **50,472** |
| &nbsp;&nbsp; exact | 38,962 (77.2%) |
| &nbsp;&nbsp; fuzzy | 11,510 (22.8%) |
| Fuzzy-score mean / median / min | 92.4 / 93.5 / 82.0 |

From `rc_ac_cluster_matches_20260517_summary.txt` (exact mode, `company_column=cluster_representative`):

| Metric | Value |
|---|---:|
| RC cases | 141,732 |
| RC cases with ≥ 1 CA match | **29,554 (20.9%)** |
| CA cases | 754,030 |
| CA cases matched to ≥ 1 RC | **55,611 (7.4%)** |
| Total match pairs | **60,731** (100% exact, by construction) |

### 4.5 The three notebooks

- **`compare_matching_methods.ipynb`** — builds the three populations on which the evaluation is stratified: agreement (both methods) ≈ **49,426 pairs** (39,738 trivially identical + 9,688 non-trivial), fuzzy-only ≈ **1,046 pairs**, cluster-only ≈ **11,305 pairs**.
- **`build_evaluation_sample.ipynb`** — seeded stratified draw of 250 pairs: 100 from cluster-only, 100 from fuzzy-only, 50 from agreement-non-trivial. Blinded.
- **`analyze_evaluation_results.ipynb`** — unblinds against the key, computes per-cell precision with Wilson CIs (`p_cluster_only ≈ 1.00`, `p_fuzzy_only ≈ 0.959`, `p_agreement ≈ 1.00`). Step 2 of the evaluation plan re-weights these by their true pool sizes.

`clustering_failure_analysis.md` decomposes the 93 fuzzy-only pairs labelled "true match" into three modes: A (33%) LLM same-block split, B (30%) blocking failure, C (37%) pre-blocking singleton — confirming that ~67% of clustering "misses" are upstream of the LLM itself.

---

## 5. Master coverage table for Step 1

This is the single table Step 1 should publish — every count cited to a primary source.

| # | Stage | Population | Count | Source |
|---|---|---|---:|---|
| 0a | Raw, per system, R-side address rows | CHIPS + CATS + NxGen | 115,171 + 74,095 + 35,445 = **224,711** | per-system notebooks |
| 0b | Raw, per system, C-side address rows | CHIPS + CATS + NxGen | 509,002 + 320,562 + 243,846 = **1,073,410** | per-system notebooks |
| 1a | After merge + dedup on case_number — R | rows in `merged_R_CASES_ADDRESS_with_union_flag.parquet` | **197,451** | `merge_R_CASES_ADDRESS.ipynb` |
| 1b | After merge + dedup on case_number — C | rows in `merged_C_CASES_ADDRESS_with_union_flag.parquet` | **1,038,762** | `merge_C_CASES_ADDRESS.ipynb` |
| 2a | RC-type rows in matching dataset | after `load_and_prepare()` — see §5.1 for filter cascade | **141,732** | `matching_summary.txt`; replay in `explore_case_tables.ipynb` §9 |
| 2a′ | RC-type rows actually entering the date-window join | after `_prepare_slim_frames()` — see footnote below table | **141,025** | `explore_case_tables.ipynb` §9a |
| 2b | CA-type rows reaching matching | after `load_and_prepare()` — see §5.1 for filter cascade | **754,030** | `matching_summary.txt`; replay in `explore_case_tables.ipynb` §9 |
| 3 | Unique preprocessed names (R ∪ C) | input to embedding + blocking | **334,276** | `evaluation_report.md` (legacy baseline n_names), `generate_embeddings_openai_fixed.py` |
| 4a | Names placed in non-singleton blocks | rows in `blocks.csv` | **224,767** | `evaluation_report.md` |
| 4b | Pre-blocking singletons (never enter blocking) | 334,276 − 224,767 | **109,509** | derived |
| 5a | Rows in `cluster_assignments_20260517.csv` | (= names that entered blocking) | **224,767** | verified directly |
| 5b | Global clusters | distinct `global_cluster_id` | **91,120** | verified directly |
| 5c | LLM-decided singletons (inside processed blocks) | `is_singleton == 1` | **38,892** | verified directly |
| 5d | Names in multi-name clusters | `cluster_size > 1` | **185,875** | verified directly |
| 5e | Names with **no** cluster representative (cluster-rep falls back to preprocessed name) | 334,276 − 224,767 | **109,509** | derived (see §4.2) |
| 6a | RC ↔ CA pairs — hybrid fuzzy | total in `rc_ac_matches.parquet` | **50,472** | `matching_summary.txt` |
| 6b | &nbsp;&nbsp;exact / fuzzy split | | 38,962 / 11,510 | `matching_summary.txt` |
| 6c | RC ↔ CA pairs — cluster exact | total in `rc_ac_cluster_matches_20260517.parquet` | **60,731** | `rc_ac_cluster_matches_20260517_summary.txt` |
| 7a | Audit pool — agreement (trivial, identical preprocessed names) | both methods | **39,738** | `../NLRB_evaluation_next_steps.md` §2 |
| 7b | Audit pool — agreement (non-trivial) | both methods | **9,688** | `../NLRB_evaluation_next_steps.md` §2 |
| 7c | Audit pool — fuzzy-only | hybrid fuzzy minus cluster | **1,046** | `../NLRB_evaluation_next_steps.md` §2 |
| 7d | Audit pool — cluster-only | cluster minus hybrid fuzzy | **11,305** | `../NLRB_evaluation_next_steps.md` §2 |

Numbers that move horizontally between stages without loss are the ones to flag in green; the two big drops are **(1a + 1b) → (2a + 2b)** (type-filter and flag-filter, intentional) and **3 → 4a** (pre-blocking singletons, the load-bearing coverage gap).

> **Footnote — the 707-row distinction between rows 2a and 2a′.** `matching_summary.txt` reports "RC cases in dataset: 141,732", which is the count emitted by `load_and_prepare()`. The matcher then calls `_prepare_slim_frames()` separately for each match pass, which drops an additional **702 RC cases with missing `date_closed`** (open cases — no upper endpoint for the date window) and **5 RC cases with `date_closed < date_filed`** (malformed intervals). So the actual count entering the RC↔CA join is **141,025**, not 141,732. The C-side has no equivalent pre-filter — the date window is applied at join time on the RC side only. Worth knowing because per-RC-case precision/recall figures should use 141,025 as the denominator, not 141,732.

---

## 5.1 Per-filter drop attribution (closes Gap A)

Decomposition of rows **1a → 2a** (R-side) and **1b → 2b** (C-side). Replayed step-for-step from `match_r_to_c_cases.py` lines 133–271 in `explore_case_tables.ipynb` §9; every drop is attributable to a specific filter.

### R-side cascade: 197,451 R_ADDR rows → 141,025 entering match

| # | Filter | Surviving rows | Dropped | Notes |
|---|---|---:|---:|---|
| R0 | `R_ADDR` (loaded) | 197,451 | — | row 1a |
| R0′ | `R_FINAL` (loaded) | 197,253 | — | 198 fewer than `R_ADDR`; 169 of those are RC |
| R1 | `R_FINAL` filter `type=='RC'` | 144,319 | (52,934 non-RC; intentional) | non-RC types removed |
| R2 | `R_ADDR` dedup on `r_case_number` | 197,451 | 0 | confirms merge dedup was complete |
| R3 | `R_ADDR` drop `is_union_name \| is_long_name` | 194,414 | 3,037 (union 2,671 + long 374, overlap 8) | on all R_ADDR types; only the RC subset matters downstream |
| R4 | Inner join `R_FINAL(RC) ⋈ R_ADDR(unflagged)` | **142,200** | 2,119 | RC cases whose `R_ADDR` row was flag-dropped (= 2,124 flagged RC R_ADDR rows − 5 in the R_ADDR-only-not-in-R_FINAL set) |
| R5 | Drop `company_name == case_number` pattern | 142,200 | 0 | dormant filter on R-side |
| R6 | Drop empty `match_company / match_state / match_city` after normalize | **141,732** | 468 (company 147, state 164, city 430 — overlapping) | post-normalization NAs and whitespace-only strings; **= row 2a** |
| R7 | Drop missing `date_closed` (open cases) | 141,030 | 702 | `_prepare_slim_frames`; 702 of the 1,127 R_FINAL NA-date_closed rows are RC |
| R8 | Drop `date_closed < date_filed` | **141,025** | 5 | `_prepare_slim_frames`; malformed intervals; **= row 2a′** |

### C-side cascade: 1,038,762 C_ADDR rows → 754,030 entering match

| # | Filter | Surviving rows | Dropped | Notes |
|---|---|---:|---:|---|
| C0 | `C_ADDR` (loaded) | 1,038,762 | — | row 1b |
| C0′ | `C_FINAL` (loaded) | 1,038,762 | — | C_ADDR ⇔ C_FINAL is 1:1, no asymmetry |
| C1 | `C_FINAL` filter `type=='CA'` | 771,459 | (267,303 non-CA; intentional) | dominantly CB cases, removed |
| C2 | `C_ADDR` dedup on `c_case_number` | 1,038,762 | 0 | confirms merge dedup was complete |
| C3 | `C_ADDR` drop `is_union_name \| is_long_name` | 853,315 | 185,447 (union 180,624 + long 23,520, overlap 18,697) | on all C_ADDR types; only the CA subset matters downstream |
| C4 | Inner join `C_FINAL(CA) ⋈ C_ADDR(unflagged)` | 756,718 | 14,741 | CA cases whose `C_ADDR` row was flag-dropped; matches the section-5 figure exactly (no R_ADDR-style asymmetry to subtract) |
| C5 | Drop `company_name == case_number` pattern | 756,716 | 2 | two CA cases had a case-number string in `company_name` |
| C6 | Drop empty `match_company / match_state / match_city` after normalize | **754,030** | 2,686 (company 1,788, state 76, city 2,653 — overlapping) | post-normalization NAs and whitespace-only strings; **= row 2b**. No `_prepare_slim_frames` date filter applies on C-side. |

### What the cascade tells us

- **The single largest drop on both sides is the type filter** (52,934 R; 267,303 C), and it is intentional — non-RC R-cases and non-CA C-cases are not in scope.
- **The largest data-driven drop is the union/long flag** (intentional but downstream-sensitive): 2,124 RC rows on the R-side, 14,741 CA rows on the C-side. The C-side flag drop is **6.9×** the R-side rate in absolute terms, and **1.5×** in proportional terms (1.91% of CA vs 1.27% of RC after type filter — see `explore_case_tables.ipynb` §5).
- **Empty match keys** are a small but real drop (468 R / 2,686 C). On the C-side the dominant missing field is `city` (2,653) followed by `company_name` (1,788) — worth noting if a future Step 1 reader wants to break coverage by missing-field-type.
- **The R-side cross-table asymmetry contributes 5 hidden drops**: of the 169 RC case numbers that appear in `R_ADDR` but not `R_FINAL`, 5 are also flagged, so they would have been dropped twice — but the inner-join happens first, so they only count once toward the inner-join loss. Net effect: the inner-join loss (2,119) is exactly 5 below the section-5 figure for flagged RC R_ADDR rows (2,124).
- **The 707-row `load_and_prepare` vs actual-matching gap** (footnote above) is small but specifically about R-side data quality, not about filtering policy.

---

## 5.2 Row-level cluster coverage (closes Gap B)

Rows 5a–5e of the master table describe the cluster file at the **name** level (224,767 unique preprocessed names, 91,120 clusters, …). For the matching pipeline what matters is the **row** level: when `add_cluster_representatives.py` joins the cluster file to the two ADDRESS parquets, what fraction of *rows* lands on a usable cluster representative vs falls back to its own preprocessed name?

Computed by re-preprocessing every row in each ADDRESS parquet and checking set membership against the cluster file's unique-name index. Per-row outcome is one of four:

| Status | Definition | Behavior at matching time |
|---|---|---|
| `multi_cluster` | preprocessed name lands in a cluster with `cluster_size > 1` | gains synonym-matching potential — distinct rows may share a representative |
| `llm_singleton` | preprocessed name is in cluster file with `cluster_size == 1` | representative = own preprocessed name; behaves like fallback |
| `pre_blocking_singleton` | preprocessed name is **not** in cluster file at all | representative = own preprocessed name; behaves like fallback |
| `empty_after_preprocess` | `company_name` is NA or empty after preprocessing | dropped at the empty-match-key step anyway |

### Row-level cluster status — per ADDRESS table

| Scope | Rows | `multi_cluster` | `llm_singleton` | `pre_blocking_singleton` | empty |
|---|---:|---:|---:|---:|---:|
| R_ADDR (all rows) | 197,451 | 117,213 (59.4%) | 20,696 (10.5%) | 59,222 (30.0%) | 320 (0.2%) |
| **R_ADDR (matching universe)** | **142,053** | **86,959 (61.2%)** | 15,800 (11.1%) | 39,294 (27.7%) | — |
| C_ADDR (all rows) | 1,038,762 | 611,325 (58.9%) | 64,572 (6.2%) | 360,243 (34.7%) | 2,622 (0.3%) |
| **C_ADDR (matching universe)** | **754,930** | **550,211 (72.9%)** | 60,425 (8.0%) | 144,294 (19.1%) | — |
| **Combined matching universe** | **896,983** | **637,170 (71.0%)** | 76,225 (8.5%) | 183,588 (20.5%) | — |

> **Footnote on the matching-universe row counts.** The "matching universe" filter in `explore_case_tables.ipynb` §10c is a proxy for `load_and_prepare()` that uses `case_number ∈ *_FINAL` and `_pp != ""` instead of the full empty-`match_state`/`match_city` checks. That makes it ~321 rows looser on the R-side (142,053 vs §9's 141,732) and ~900 rows looser on the C-side (754,930 vs 754,030). The discrepancy doesn't change the headline percentages to one decimal place.

### Row-level vs name-level

The pre-blocking-singleton pool (109,509 names that never entered blocking) hits hardest on rare/unique names, not frequent ones. Reweighting from rows (frequency-weighted) to unique preprocessed names (uniform) shifts the distribution materially:

| Bucket | Row-level (matching universe) | Name-level (unique preprocessed names in matching universe) | Δ |
|---|---:|---:|---:|
| `multi_cluster` | **71.0%** | 55.6% | **+15.5 pp** |
| `llm_singleton` | 8.5% | 11.7% | −3.2 pp |
| `pre_blocking_singleton` | 20.5% | 32.8% | −12.3 pp |

(Unique preprocessed names in the combined matching universe: 323,652.)

### What this tells us

- **The cluster method finds a real cluster representative for 71% of rows that reach matching.** The remaining 29% (= 8.5% LLM-singleton + 20.5% pre-blocking-singleton) behave like exact-match on the preprocessed name at matching time — same population the fuzzy method has to either find via `token_sort_ratio ≥ 82` or miss.
- **C-side cluster coverage is materially better than R-side: 72.9% vs 61.2%, an 11.7 pp gap.** Mechanism is mass: CA cases are 5.3× more numerous than RC, so frequent-employer names (USPS, GM, Walmart, …) appear many times on the C-side and tend to land in the large multi-name clusters. The R-side has a longer tail of rare/unique establishments, more of which fall into the pre-blocking-singleton pool. **This is the load-bearing asymmetry for any per-method matching analysis** — the cluster method's coverage ceiling is fundamentally higher on the C-side than on the R-side.
- **The 15.5 pp row-level-over-name-level lift confirms that the pre-blocking singletons are concentrated in rare names.** The headline "32.8% of unique preprocessed names never entered blocking" figure overstates the operational cost; only 20.5% of *rows* fall back. Common employers were captured by the blocker; obscure or typo-corrupted long-tail names were not.
- **The LLM-singleton population (8.5% of rows) is operationally identical to a fallback** for matching purposes, but conceptually distinct: these names *did* reach the LLM, which judged them to have no peer in their block. They contribute to the cluster file's row count (38,892 of 224,767) but not to its synonym-bridging capability.
- **The R/C asymmetry holds the same direction at the name level** (R has more rare names so more pre-blocking singletons), but the gap is smaller at the row level than the per-row coverage table suggests — because frequent C-side names get re-counted many times.

---

## 5.3 LLM-processed vs export-fallback singletons (closes Gap C)

The cluster file has 15,764 distinct merged `block_id` values, of which **27 blocks (327 names)** have every member emitted as a singleton. From the CSV alone we couldn't tell whether the LLM was asked and judged everyone distinct, or whether the block was skipped and `export_cluster_assignments.py` auto-assigned each member its own singleton.

Cross-referenced against `nlrb-clustering-with-LLM/results/batch_state.db` (which records per-block status, `api_calls`, `hit_max_iter`, `retry_count`, `final_clusters`, and the `result_file` path) and against the actual JSON files on disk:

| Check | Result for all 27 suspect blocks |
|---|---|
| `status` | `completed` (no `pending` / `failed` / `skipped`) |
| `api_calls` | range **3–5** (mean ≈3.2) — LLM was actually invoked |
| `result_file` exists on disk | **27 / 27** |
| `hit_max_iter` | **0** — converged naturally (two consecutive all-singleton NRS levels) |
| `retry_count` | **0** — no errors during processing |
| `final_clusters` | equals `block_size` for every block — LLM emitted N singleton clusters from N inputs |
| `hierarchy_levels` | 1 or 2 — LLM made 1–2 NRS passes and concluded all members were distinct |
| Block-size distribution | 11 (×4), 12 (×18), 13 (×4), 15 (×1) — all close to `S_S=12`, fit one record-set per block |

**Conclusion:** all 327 names are real clustering decisions — the LLM was given 11–15 candidate-similar names and judged that no two refer to the same entity. None of the 27 blocks were export-fallback.

**Operational consequence:** these 327 names contribute to the cluster file with `cluster_size = 1`, so they fold into the `llm_singleton` bucket counted in §5.2 (38,892 names total). At matching time they behave like fallback (representative = own preprocessed name, no synonym bridging), but they are **conceptually distinct from the 109,509 pre-blocking singletons** — both populations *reached* blocking, but the LLM-singletons additionally got an LLM verdict that they have no peer.

**For Step 1 reporting:** the headline "38,892 LLM-singletons" figure in §5.2 and master-table row 5c is correct as stated. The 327 names in all-singleton blocks are a subset of those 38,892, and they don't need their own row — they're already counted.

---

## 5.4 Source attribution and the Step-4 sampling frame (closes Gap D)

The blocking pipeline's preprocessing (`legacy/generate_embeddings_openai_fixed.py`) concatenates the filtered R-side and C-side names and applies `.unique()` — the **source side is discarded** at this dedup step. So `blocks.csv` and `cluster_assignments_20260517.csv` cannot tell us which of the 334,276 unique preprocessed names came from R, from C, or from both. We re-derive that by re-applying the same filters (type ∈ {RC, RD} for R, type == CA for C; drop union/long-flagged rows; drop null `company_name`) and the same two-stage preprocessing on each ADDRESS parquet, then comparing the per-side unique-name sets.

### R-only / C-only / both partition of the 334,276-name universe

| Source partition | Unique preprocessed names | Share of universe |
|---|---:|---:|
| R-side total (RC ∪ RD, unflagged) | 113,881 | 34.1% |
| C-side total (CA, unflagged) | 267,307 | 80.0% |
| **R-only** (in R, not in C) | **66,969** | **20.0%** |
| **C-only** (in C, not in R) | **220,395** | **65.9%** |
| **Both** (in R *and* C) | **46,912** | **14.0%** |
| Union (R ∪ C) | **334,276** | 100% ← matches `evaluation_report.md` exactly |

Reproducibility check: the recomputed union lands on 334,276 exactly, confirming that `preprocessing_v3.py` and the merged ADDRESS parquets have not drifted since `generate_embeddings_openai_fixed.py` was originally run to produce `lsh_results/company_names.pkl`.

### 3×3 sampling-frame contingency table

Cross-tabulating source (R-only / C-only / both) with cluster-file status (multi_cluster / llm_singleton / pre_blocking_singleton) gives the full Step-4 sampling frame:

| | R-only | C-only | both | **Total** |
|---|---:|---:|---:|---:|
| `multi_cluster` | 34,615 | 124,369 | 26,891 | **185,875** |
| `llm_singleton` | 8,045 | 24,243 | 6,604 | **38,892** |
| `pre_blocking_singleton` | 24,309 | 71,783 | 13,417 | **109,509** |
| **Total** | **66,969** | **220,395** | **46,912** | **334,276** |

Same table as percentages of 334,276:

| | R-only | C-only | both | **Total** |
|---|---:|---:|---:|---:|
| `multi_cluster` | 10.36% | 37.21% | 8.04% | **55.61%** |
| `llm_singleton` | 2.41% | 7.25% | 1.98% | **11.63%** |
| `pre_blocking_singleton` | 7.27% | 21.47% | 4.01% | **32.76%** |
| **Total** | **20.03%** | **65.93%** | **14.03%** | **100%** |

### Cluster-status conditional on source

Restated as "within each source partition, what's the cluster-status breakdown" — useful for stratifying the Step-4 draw:

| Source | n names | `multi_cluster` | `llm_singleton` | `pre_blocking_singleton` |
|---|---:|---:|---:|---:|
| R-only | 66,969 | 51.7% | 12.0% | 36.3% |
| C-only | 220,395 | 56.4% | 11.0% | 32.6% |
| **both** | **46,912** | **57.3%** | **14.1%** | **28.6%** |

### What this tells us

- **The matching universe at the name level is only 46,912 names (14.0% of 334,276).** A name that appears `R-only` (e.g., an RC petition for a firm that has never had a CA charge) **cannot** contribute to an R↔C link no matter how good clustering or matching is. Same for `C-only`. **The denominator for any name-level R↔C matching-recall claim should be 46,912, not 334,276.** Asymmetric counts: 41.2% of R-side unique names (46,912 / 113,881) appear on both sides, but only 17.5% of C-side unique names (46,912 / 267,307) do — because the C-side population is so much larger.
- **Cluster coverage is highest in the `both` partition.** 57.3% of `both` names land in a multi-name cluster, vs 56.4% for C-only and 51.7% for R-only. The mechanism is the same one we saw in §5.2: a name that appears on both sides is by construction more common, so it's more likely to have near-neighbors in the candidate graph and end up in a non-singleton cluster.
- **Within the matching-relevant `both` partition, 42.7% of names are still effectively fallback** (14.1% LLM-singleton + 28.6% pre-blocking-singleton). This is the operationally binding constraint on cluster-method matching recall at the name level — even where R↔C linkage is *possible*, only 57.3% of those firms have a real cluster representative to bridge their R-side and C-side name variants.
- **The 13,417 pre-blocking singletons within `both` are the load-bearing recall losses.** These are firms where (i) the same preprocessed name appears in both R and C cases (so a link is possible) and (ii) the name never entered blocking (so the cluster method cannot help; only exact-match on preprocessed name will succeed). The number that any matching-recall claim should explicitly account for.
- **Step-4 sampling implication.** The full 334,276 universe is the right sampling frame for *clustering* benchmarks (Binette-style entity-centric estimation, where the goal is to characterize the resolver's behavior across all firms). The 46,912 `both` partition is the right frame for *matching*-specific recall, where only co-appearing names matter. Stratifying a Step-4 draw by source (e.g., 200 names from `both`, 100 each from `R-only` and `C-only`) gives clean estimates for both questions from one labeling effort.

---

## 6. Discrepancies and stale numbers to be aware of

These are inconsistencies between docs in the repo that surfaced while tracing the flow. They do not affect the verified counts above but they will cause confusion in any reader who reads the docs cold:

1. **`clustering_results_table.md` is partially stale.** It states the cluster-export script reads "all 334,276 records from the input CSV" and that "177,652 records whose blocks were not processed … are treated as singletons". That description is true of an **earlier** clustering run that was driven by the **legacy** blocking pipeline (217,136 blocks / 177,652 singletons / 156,624 in non-singleton blocks). The actual `cluster_assignments_20260517.csv` in the matching folder has **224,767 rows**, not 334,276 — it was produced from the **new** blocking pipeline's `blocks.csv` (which already excludes singletons), so the "auto-fill singletons" branch of `export_cluster_assignments.py` matched 0 rows for this run. The 224,767 figure is the one that flows into matching today; the 334,276 figure is the universe of unique preprocessed names, of which only 224,767 ever made it to blocks/clusters.
2. **The 38,892-singleton figure in `../NLRB_evaluation_next_steps.md` Step 1.** Verified: `is_singleton == 1` = 38,892 in `cluster_assignments_20260517.csv`. These are **LLM-decided** singletons inside processed blocks (a name that was in a block but the LLM judged it had no peer). They are **not** the same as the pre-blocking singletons (109,509). Both numbers should appear in the coverage figure.
3. **CLAUDE.md (clustering) mentions "mega-block 0 (~50K records)" and `MAX_BLOCK_SIZE=1000`.** That guard is dormant for the 2026-05-17 run because the new blocking pipeline's largest block is 197. The warning is a holdover from the legacy hierarchical pipeline and is harmless as long as the input remains the new `blocks.csv`.
4. **Source attribution is dropped at the dedup step in §2.1 and never restored in the cluster file.** Anywhere a doc reports R-only / C-only counts of clusters, it is reconstructing that by joining the preprocessed name back to the address parquets — not reading it off the cluster file. Worth surfacing in Step 1 so readers know the cluster file is name-centric, not record-centric.
5. **`name_data_flow` ↔ `NLRB_PIPELINE.md`.** `NLRB_PIPELINE.md` notes that downstream stages "should read from `Merge_files/` (or a symlink to it), not from their own local copies." In practice, `nlrb-matching-cases/` holds local copies of the two ADDRESS parquets, and `nlrb-blocking/` reads from `lsh_results/company_names.pkl` (built once, off the merged parquets). Worth a single-line check before each Step-1 publish that all four locations have the same SHA or mtime.

---

## 7. File inventory (where every number above lives)

| File | Stage | Role |
|---|---|---|
| `nlrb-creating-files/{CHIPS,CATS,NxGen}/{R,C}_CASES_ADDRESS_*.ipynb` | 1 | Per-system extracts |
| `nlrb-creating-files/Merge_files/merge_{R,C}_CASES_ADDRESS.ipynb` | 1 | Concat + dedup |
| `nlrb-creating-files/Merge_files/flag_union_names_v2.ipynb` | 1 | `is_union_name`, `is_long_name`, `matched_union_terms` |
| `nlrb-creating-files/Merge_files/merged_{R,C}_CASES_ADDRESS_with_union_flag.parquet` | 1 | Canonical address tables (197,451 / 1,038,762) |
| `nlrb-creating-files/Merge_files/merged_{R,C}_CASES_final.parquet` | 1 | Case-level: type + dates |
| `nlrb-blocking/legacy/generate_embeddings_openai_fixed.py` | 2 | Builds the 334,276-unique-name list (preprocess + dedup + embed) |
| `nlrb-blocking/lsh_results/company_names.pkl`, `embeddings.npy` | 2 | The 334,276 names and their vectors |
| `nlrb-blocking/scripts/02..06_*.py` | 2 | Active blocking pipeline |
| `nlrb-blocking/data/output/blocks.csv` | 2 | 51,630 blocks / 224,767 names |
| `nlrb-blocking/data/output/evaluation_report.md` | 2 | Cost + weak-recall diagnostics |
| `nlrb-clustering-with-LLM/run_full_pipeline.py` + `core/*.py` | 3 | LLM-CER orchestration |
| `nlrb-clustering-with-LLM/blocks_merged.csv` | 3 | 224,767 names re-binned to ~15,764 bins of ~12 |
| `nlrb-clustering-with-LLM/results/blocks_<run>/block_<id>.json` | 3 | Per-block `final_clusters` |
| `nlrb-clustering-with-LLM/export_cluster_assignments.py` | 3 | JSONs → CSV |
| `nlrb-matching-cases/cluster_assignments_20260517.csv` | 3 → 4 | **224,767 rows / 91,120 clusters / 38,892 singletons** (the canonical cluster file) |
| `nlrb-matching-cases/preprocessing_v3.py` + `name_standardization.py` | 4 (also 2 by reuse) | Two-stage name preprocessor |
| `nlrb-matching-cases/add_cluster_representatives.py` | 4 | Adds `cluster_representative` to both ADDRESS parquets |
| `nlrb-matching-cases/match_r_to_c_cases.py` | 4 | Hybrid / exact / fuzzy / cluster matching |
| `nlrb-matching-cases/rc_ac_matches.parquet` (+ `_summary.txt`) | 4 | Fuzzy/hybrid output, 50,472 pairs |
| `nlrb-matching-cases/rc_ac_cluster_matches_20260517.parquet` (+ `_summary.txt`) | 4 | Cluster-exact output, 60,731 pairs |
| `nlrb-matching-cases/compare_matching_methods.ipynb` | 4 | Builds agreement / fuzzy-only / cluster-only pools |
| `nlrb-matching-cases/build_evaluation_sample.ipynb` | 4 | 250-pair stratified audit |
| `nlrb-matching-cases/analyze_evaluation_results.ipynb` | 4 | Per-cell precision + Wilson CIs |
