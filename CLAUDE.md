# NLRB R-Case to C-Case Matching

## Project Goal

Link NLRB union organizing petitions (RC-type R Cases) to unfair labor practice charges (CA-type C Cases). These live in separate tables with **no foreign key** between them, so the connection must be inferred by matching on establishment identity and temporal overlap (C Case filed during the R Case's active window).

## Domain Context

- **R Cases** — Representation cases. We focus on type **RC** (petitions for union certification elections).
- **C Cases** — Unfair labor practice charges. We focus on type **CA** (charges against employers).
- A match means: same workplace, and the CA charge was filed between the RC petition's `date_filed` and `date_closed`.
- NLRB data spans three filing systems: **CHIPS** (1984–2001), **CATS** (1999–2011), **NxGen** (2011–present). Each had different table/variable structures; the data here has already been unified.

## Two Matching Methods

### 1. Fuzzy Matching (implemented)

`match_r_to_c_cases.py` — Hybrid exact + fuzzy matching:
- **Exact pass**: equi-join on preprocessed company name, state, city, then date-window filter.
- **Fuzzy pass**: blocks on state, uses `rapidfuzz.token_sort_ratio` on preprocessed company names (threshold 82), with a city gate (exact or fuzzy >= 85), then date-window filter.
- Output: `rc_ac_matches.parquet` / `rc_ac_matches.csv`

### 2. Clustering-Based Matching

- Company names from address tables were clustered using LLM-powered Clustering-based Entity Resolution (LLM-CER), following the paper "In-context Clustering-based Entity Resolution with Large Language Models."
- Blocking (LSH) and clustering were done in separate project folders.
- The result is `cluster_assignments_20260517.csv`: each row maps a company name to a `global_cluster_id`. Names in the same cluster are considered the same entity.
- `add_cluster_representatives.py` adds a `cluster_representative` column to the address tables (shortest name per cluster, fallback to preprocessed name for singletons).
- `match_r_to_c_cases.py --match-mode exact --company-column cluster_representative --output-prefix rc_ac_cluster_matches_20260517` then runs exact matching on the cluster representatives.
- Output: `rc_ac_cluster_matches_20260517.parquet` / `.csv`

## Data Files

| File | Description |
|------|-------------|
| `merged_R_CASES_final.parquet` | Unified R Cases table (case number, type, dates, filing system) |
| `merged_R_CASES_ADDRESS_with_union_flag.parquet` | R Cases address table (company name, state, city, zip) |
| `merged_C_CASES_final.parquet` | Unified C Cases table (case number, type, dates, filing system) |
| `merged_C_CASES_ADDRESS_with_union_flag.parquet` | C Cases address table (company name, state, city, zip) |
| `cluster_assignments_20260517.csv` | LLM-CER clustering output — columns: `block_id`, `company_idx`, `company_name`, `source`, `global_cluster_id`, `cluster_size`, `is_singleton` (and others) |
| `rc_ac_matches.parquet` / `.csv` | Output of fuzzy matching |
| `matching_summary.txt` | Diagnostics from fuzzy matching run |
| `rc_ac_cluster_matches_20260517.parquet` / `.csv` | Output of cluster-based matching |
| `rc_ac_cluster_matches_20260517_summary.txt` | Diagnostics from cluster matching run |

## Key Scripts

| Script | Purpose |
|--------|---------|
| `match_r_to_c_cases.py` | Matching pipeline — runs fuzzy matching by default, or cluster-based matching via `--company-column cluster_representative` |
| `add_cluster_representatives.py` | Adds a `cluster_representative` column to both address parquets by joining to `cluster_assignments_20260517.csv` (run once before cluster matching) |
| `preprocessing_v3.py` | Company name preprocessing (OCR fixes, slash handling, stop-word removal, hyphen guards, digit cleanup) |
| `name_standardization.py` | Canonical-form replacement for high-frequency firms (USPS, GM, etc.) |

## Notebooks

| Notebook | Purpose |
|----------|---------|
| `compare_matching_methods.ipynb` | Compares fuzzy vs cluster matching results: pair-level overlap, RC/CA-level overlap, samples |
| `evaluation/build_evaluation_sample.ipynb` | Builds the stratified 250-pair evaluation sample (blinded, seeded) |
| `evaluation/analyze_evaluation_results.ipynb` | Unblinds labels and reports per-cell precision with Wilson CIs |

## Schema

See `schema/nlrb_schema_diagram.md` for the full ER diagram. Key relationships:
- `R_CASES` 1:1 `R_CASES_ADDRESS` (joined on `r_case_number`)
- `C_CASES` 1:1 `C_CASES_ADDRESS` (joined on `c_case_number`)
- `R_CASES` 1:many `ELECTIONS` (not used in matching)

## Conventions

- Python, pandas, parquet for data processing.
- Company name preprocessing always uses the two-stage pipeline: `preprocess_employer()` then `standardize_company_name()`.
- Location fields are normalized (lowercased, stripped, punctuation removed) before matching.
- Case numbers: R Cases use `r_case_number`, C Cases use `c_case_number`. Some raw files have `case_number` which gets renamed.
