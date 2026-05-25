# Cluster-Based R-Case to C-Case Matching

## Overview

This document describes how to run the **cluster-based matching** method, which uses pre-computed LLM entity clusters (from `cluster_assignments_20260517.csv`) to link RC-type R Cases to CA-type C Cases. This is the second matching method, complementing the existing fuzzy matching.

The approach is simple: replace each case's company name with a **cluster representative name** (a canonical name shared by all members of the same entity cluster), then run the same exact-match logic that `match_r_to_c_cases.py` already provides.

## What Changed

### New file: `add_cluster_representatives.py`

A short script that enriches both address parquet files with a `cluster_representative` column:

1. Loads `cluster_assignments_20260517.csv` and picks one representative name per cluster (the shortest name in the cluster).
2. Preprocesses company names in the address parquets using the same two-stage pipeline (`preprocess_employer` + `standardize_company_name`) to match the cluster lookup keys.
3. Left-joins each address table to the cluster lookup on the preprocessed name.
4. Adds a `cluster_representative` column. If a name has no cluster match, it falls back to the preprocessed name (effectively treating it as its own singleton cluster).
5. Saves the updated parquets back in place.

**Arguments:**

| Flag | Default | Description |
|------|---------|-------------|
| `--cluster-file` | `./cluster_assignments.csv` | Path to the cluster assignments file (pass `--cluster-file cluster_assignments_20260517.csv` to use the current file) |
| `--data-dir` | `.` | Directory containing the address parquet files |

### Edited file: `match_r_to_c_cases.py`

Two new CLI flags were added, and `match_exact` was updated to use fuzzy city matching.

| Flag | Default | Description |
|------|---------|-------------|
| `--company-column` | `company_name` | Which column in the address table to use for building the `match_company` key. Set to `cluster_representative` for cluster-based matching. |
| `--output-prefix` | `rc_ac_matches` | Prefix for output filenames (`.parquet`, `.csv`, `_summary.txt`). Allows saving cluster results alongside fuzzy results without overwriting. |

Other changes:
- `load_and_prepare()` now accepts a `company_column` parameter that controls which column is preprocessed into `match_company`.
- `match_exact()` now joins on `(match_company, match_state)` and applies a **fuzzy city gate** (exact city match accepted, otherwise `fuzz.ratio >= city_threshold`). This makes the city-matching logic consistent across all match modes (exact, fuzzy, hybrid), so that fuzzy and cluster-based results are directly comparable.

## Usage

### Step 1: Add cluster representatives to address files

```bash
python add_cluster_representatives.py --cluster-file cluster_assignments_20260517.csv
```

This modifies the parquet files in place, adding the `cluster_representative` column. You only need to run this once (unless the cluster assignments or parquet files change).

The script prints coverage statistics showing how many names matched a cluster vs. fell back to the preprocessed name.

### Step 2: Run matching with cluster representatives

```bash
python match_r_to_c_cases.py --match-mode exact --company-column cluster_representative --output-prefix rc_ac_cluster_matches_20260517
```

This produces:
- `rc_ac_cluster_matches_20260517.parquet`
- `rc_ac_cluster_matches_20260517.csv`
- `rc_ac_cluster_matches_20260517_summary.txt`

The dated suffix tags the run with the cluster-assignments file it consumed. If you later regenerate the clusters, change the date in both the `--cluster-file` and `--output-prefix` arguments accordingly.

The output schema is the same as the fuzzy matching output (`rc_ac_matches.parquet`), making the two methods directly comparable.

### Running the original fuzzy matching

The default behavior is preserved:

```bash
python match_r_to_c_cases.py
```

This produces `rc_ac_matches.parquet` / `.csv` / `rc_ac_matches_summary.txt`.

Note: the exact pass within hybrid mode now uses the same fuzzy city gate as the fuzzy pass (see below), so results may differ slightly from earlier runs that required exact city match in the exact pass.

## Fuzzy City Gate (all match modes)

`match_exact()` now joins on `(match_company, match_state)` and applies a **fuzzy city gate** instead of requiring an exact city match. The gate works the same way as in the fuzzy pass:

- Exact city match is accepted immediately.
- Otherwise, `rapidfuzz.fuzz.ratio` is computed between the two city names. If the score is >= `--city-threshold` (default 85), the pair passes.

This applies to **all match modes** (exact, fuzzy, hybrid), ensuring that city-matching logic is consistent and that fuzzy and cluster-based results are directly comparable.
