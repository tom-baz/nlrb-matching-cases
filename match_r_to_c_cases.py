"""
NLRB R-Case to C-Case Matching (v2 — with fuzzy matching)
==========================================================
Matches RC-type R Cases to CA-type C Cases based on:
  1. Establishment identity (company_name + state + city + NLRB region)
  2. Temporal overlap (C case filed between R case filed and closed dates)

NLRB region is the leading two digits of the case number (e.g. "07-CA-034444"
-> region "07") and is treated as an equi-key, exactly like state: a genuine
RC–CA pair for the same workplace is filed in the same Regional Office.

Match modes (set via --match-mode):
  exact  — original behaviour: equi-join on normalised company + state + city
  fuzzy  — fuzzy company-name matching within state blocks (no exact pass)
  hybrid — (DEFAULT) exact pass first, then fuzzy on ALL RC cases;
           pairs already found by exact are deduplicated, so fuzzy
           matches are strictly additive (new RC–CA pairs only)

The fuzzy pass:
  - Blocks on normalised state + region (exact) to keep the candidate
    space tractable.
  - Within each state block, uses token_sort_ratio from rapidfuzz to compare
    preprocessed company names. Pairs above --fuzzy-threshold (default 82)
    are kept.
  - City is checked separately: pairs where normalised cities match exactly
    are accepted; otherwise a fuzzy city score >= --city-threshold (default 85)
    is required.  This catches minor city-name variations (abbreviations,
    spacing) without letting truly different cities through.
  - After the name/city gate, the same date-window filter is applied.

Company-name matching uses the advanced preprocessing pipeline from
preprocessing_v3.py (OCR fixes, slash handling, stop-word removal with
hyphen guards, digit cleanup, etc.) followed by name_standardization.py
(canonical-form replacement for high-frequency firms like USPS, GM, etc.).

Inputs (parquet files):
  - merged_R_CASES_final.parquet
  - merged_R_CASES_ADDRESS_with_union_flag.parquet
  - merged_C_CASES_final.parquet
  - merged_C_CASES_ADDRESS_with_union_flag.parquet

Dependencies:
  - preprocessing_v3.py
  - name_standardization.py
  - rapidfuzz  (pip install rapidfuzz)

Outputs:
  - rc_ac_matches.parquet   — one row per (r_case_number, c_case_number) match
  - rc_ac_matches.csv       — same, as CSV for quick inspection
  - matching_summary.txt    — diagnostics and summary statistics
"""

import argparse
import pandas as pd
import numpy as np
from pathlib import Path
import textwrap
from collections import defaultdict
from tqdm import tqdm

from preprocessing_v3 import preprocess_employer, filter_case_numbers
from name_standardization import standardize_company_name

# ---------------------------------------------------------------------------
# Lazy import — rapidfuzz is only needed when fuzzy matching is requested
# ---------------------------------------------------------------------------
_rapidfuzz = None


def _get_rapidfuzz():
    global _rapidfuzz
    if _rapidfuzz is None:
        try:
            import rapidfuzz
            _rapidfuzz = rapidfuzz
        except ImportError:
            raise ImportError(
                "Fuzzy matching requires the 'rapidfuzz' package.\n"
                "Install it with:  pip install rapidfuzz"
            )
    return _rapidfuzz


# ---------------------------------------------------------------------------
# CONFIG — adjust these paths to where your files live
# ---------------------------------------------------------------------------
DATA_DIR = Path(".")

R_CASES_FILE = DATA_DIR / "merged_R_CASES_final.parquet"
R_ADDR_FILE  = DATA_DIR / "merged_R_CASES_ADDRESS_with_union_flag.parquet"
C_CASES_FILE = DATA_DIR / "merged_C_CASES_final.parquet"
C_ADDR_FILE  = DATA_DIR / "merged_C_CASES_ADDRESS_with_union_flag.parquet"

OUTPUT_DIR = DATA_DIR


# ---------------------------------------------------------------------------
# HELPER: normalise location fields (state, city) for matching
# ---------------------------------------------------------------------------
def normalise_location(series: pd.Series) -> pd.Series:
    """wha
    Lowercase, strip whitespace, collapse multiple spaces, and remove
    common punctuation so that location strings match despite minor
    formatting differences.

    Missing values are replaced with empty strings so that they never
    accidentally match each other on the literal string "nan".
    """
    s = series.fillna("").astype(str).str.lower().str.strip()
    for char in [".", ",", "'", '"']:
        s = s.str.replace(char, "", regex=False)
    s = s.str.replace(r"\s+", " ", regex=True)
    return s


# ---------------------------------------------------------------------------
# HELPER: preprocess company names using the full pipeline
# ---------------------------------------------------------------------------
def preprocess_company_series(series: pd.Series) -> pd.Series:
    """
    Apply the two-stage company-name preprocessing pipeline:
      1. preprocess_employer()  — OCR fixes, slash→space, DBA removal,
         digit stripping, stop-word removal with hyphen guards, etc.
      2. standardize_company_name() — canonical-form replacement for
         high-frequency firms (USPS, GM, Kaiser, Ford, Red Cross, …).

    Missing values are replaced with empty strings before processing.
    """
    s = series.fillna("").astype(str)
    s = s.apply(preprocess_employer)
    s = s.apply(standardize_company_name)
    return s


# ---------------------------------------------------------------------------
# STEP 1 — Load and filter
# ---------------------------------------------------------------------------
def load_and_prepare(company_column="company_name"):
    print("Loading parquet files …")
    r_cases = pd.read_parquet(R_CASES_FILE)
    r_addr  = pd.read_parquet(R_ADDR_FILE)
    c_cases = pd.read_parquet(C_CASES_FILE)
    c_addr  = pd.read_parquet(C_ADDR_FILE)

    print(f"  R_CASES rows:         {len(r_cases):>10,}")
    print(f"  R_CASES_ADDRESS rows: {len(r_addr):>10,}")
    print(f"  C_CASES rows:         {len(c_cases):>10,}")
    print(f"  C_CASES_ADDRESS rows: {len(c_addr):>10,}")

    # ---- Normalise case-number column names to match schema ----
    for df in [r_cases, r_addr]:
        if "case_number" in df.columns and "r_case_number" not in df.columns:
            df.rename(columns={"case_number": "r_case_number"}, inplace=True)
            print("  ℹ Renamed 'case_number' → 'r_case_number' in R-side table")
    for df in [c_cases, c_addr]:
        if "case_number" in df.columns and "c_case_number" not in df.columns:
            df.rename(columns={"case_number": "c_case_number"}, inplace=True)
            print("  ℹ Renamed 'case_number' → 'c_case_number' in C-side table")

    # ---- Filter by type ----
    r_cases = r_cases[r_cases["type"] == "RC"].copy()
    c_cases = c_cases[c_cases["type"] == "CA"].copy()
    print(f"\n  RC-type R Cases:      {len(r_cases):>10,}")
    print(f"  CA-type C Cases:      {len(c_cases):>10,}")

    # ---- Ensure date columns are datetime ----
    for col in ["date_filed", "date_closed"]:
        r_cases[col] = pd.to_datetime(r_cases[col], errors="coerce")
    c_cases["date_filed"] = pd.to_datetime(c_cases["date_filed"], errors="coerce")

    # ---- Deduplicate address tables by case number ----
    n_r_addr_before = len(r_addr)
    r_addr = r_addr.drop_duplicates(subset=["r_case_number"], keep="first")
    if len(r_addr) < n_r_addr_before:
        print(f"  ⚠ Removed {n_r_addr_before - len(r_addr):,} duplicate R_CASES_ADDRESS rows")

    n_c_addr_before = len(c_addr)
    c_addr = c_addr.drop_duplicates(subset=["c_case_number"], keep="first")
    if len(c_addr) < n_c_addr_before:
        print(f"  ⚠ Removed {n_c_addr_before - len(c_addr):,} duplicate C_CASES_ADDRESS rows")

    # ---- Filter out flagged address rows (union names, too-long names) ----
    for label, addr_df in [("R_CASES_ADDRESS", r_addr), ("C_CASES_ADDRESS", c_addr)]:
        flag_mask = addr_df["is_union_name"] | addr_df["is_long_name"]
        n_flagged = flag_mask.sum()
        if n_flagged > 0:
            print(f"  ⚠ Dropping {n_flagged:,} {label} rows flagged as union name or too long")
    r_addr = r_addr[~(r_addr["is_union_name"] | r_addr["is_long_name"])].copy()
    c_addr = c_addr[~(c_addr["is_union_name"] | c_addr["is_long_name"])].copy()

    # ---- Join cases with their addresses ----
    r_addr_cols = ["r_case_number", "company_name", "state", "city"]
    c_addr_cols = ["c_case_number", "company_name", "state", "city"]
    if company_column != "company_name":
        r_addr_cols.append(company_column)
        c_addr_cols.append(company_column)

    rc = r_cases.merge(
        r_addr[r_addr_cols],
        on="r_case_number",
        how="inner",
    )
    ac = c_cases.merge(
        c_addr[c_addr_cols],
        on="c_case_number",
        how="inner",
    )

    # ---- Filter out rows where company_name is actually a case number ----
    rc = filter_case_numbers(rc, column="company_name")
    ac = filter_case_numbers(ac, column="company_name")

    # ---- Preprocess company names (advanced pipeline) ----
    # Only the raw company_name column needs cleaning. cluster_representative
    # was already preprocessed upstream by add_cluster_representatives.py, so
    # re-running the pipeline on it would be a redundant second pass (the
    # pipeline is not fully idempotent — e.g. a dotted "L.L.C." only loses its
    # suffix on the second pass). We deliberately preprocess exactly once.
    if company_column == "company_name":
        print(f"\nPreprocessing company names (source column: {company_column}) …")
        for df in [rc, ac]:
            df["match_company"] = preprocess_company_series(df[company_column])
    else:
        print(f"\nUsing pre-cleaned company names as-is (source column: "
              f"{company_column}; already preprocessed upstream) …")
        for df in [rc, ac]:
            df["match_company"] = df[company_column].fillna("").astype(str)

    # ---- Normalise location fields (simple lowercase / whitespace) ----
    for df in [rc, ac]:
        df["match_state"] = normalise_location(df["state"])
        df["match_city"]  = normalise_location(df["city"])

    # ---- Extract NLRB Region (leading two digits of the case number) ----
    # Region behaves exactly like state: an equi-key. A genuine RC–CA pair
    # is filed in the same Regional Office (e.g. "07-CA-034444" -> "07"), so
    # company + state + city + region must all agree.
    rc["match_region"] = rc["r_case_number"].astype(str).str.extract(r"^(\d{2})-")[0].fillna("")
    ac["match_region"] = ac["c_case_number"].astype(str).str.extract(r"^(\d{2})-")[0].fillna("")

    # ---- Drop rows where any matching key is empty after normalisation ----
    for label, df in [("RC", rc), ("AC", ac)]:
        empty_mask = (
            (df["match_company"] == "")
            | (df["match_state"] == "")
            | (df["match_city"] == "")
        )
        n_empty = empty_mask.sum()
        if n_empty > 0:
            print(f"  ⚠ Dropping {n_empty:,} {label} rows with missing company/state/city")
    rc = rc[
        (rc["match_company"] != "")
        & (rc["match_state"] != "")
        & (rc["match_city"] != "")
    ].copy()
    ac = ac[
        (ac["match_company"] != "")
        & (ac["match_state"] != "")
        & (ac["match_city"] != "")
    ].copy()

    return rc, ac


# ---------------------------------------------------------------------------
# Prepare slim DataFrames used by both exact and fuzzy passes
# ---------------------------------------------------------------------------
def _prepare_slim_frames(rc: pd.DataFrame, ac: pd.DataFrame):
    """
    Build lean copies of the RC and AC frames with only the columns needed
    for matching, and apply date-based filters to RC cases.  Shared by both
    exact and fuzzy matching to avoid duplicating this logic.
    """
    rc_slim = rc[["r_case_number", "date_filed", "date_closed",
                   "company_name", "state", "city",
                   "match_company", "match_state", "match_city",
                   "match_region"]].copy()
    rc_slim.rename(columns={"date_filed":    "r_date_filed",
                             "date_closed":   "r_date_closed",
                             "company_name":  "r_company_name",
                             "state":         "r_state",
                             "city":          "r_city"}, inplace=True)

    # Exclude open cases (no close date)
    n_before = len(rc_slim)
    rc_slim = rc_slim.dropna(subset=["r_date_closed"])
    n_dropped_open = n_before - len(rc_slim)
    if n_dropped_open:
        print(f"  RC cases dropped (still open / no close date): {n_dropped_open:,}")

    # Exclude impossible date intervals
    bad_dates = rc_slim["r_date_closed"] < rc_slim["r_date_filed"]
    if bad_dates.sum() > 0:
        print(f"  ⚠ Dropping {bad_dates.sum():,} RC cases where date_closed < date_filed")
        rc_slim = rc_slim[~bad_dates]

    ac_slim = ac[["c_case_number", "date_filed",
                   "company_name", "state", "city",
                   "match_company", "match_state", "match_city",
                   "match_region"]].copy()
    ac_slim.rename(columns={"date_filed":    "c_date_filed",
                             "company_name":  "c_company_name",
                             "state":         "c_state",
                             "city":          "c_city"}, inplace=True)

    return rc_slim, ac_slim


def _apply_date_filter(merged: pd.DataFrame) -> pd.DataFrame:
    """Keep only rows where the CA case was filed within the RC window."""
    mask = (
        (merged["c_date_filed"] >= merged["r_date_filed"])
        & (merged["c_date_filed"] <= merged["r_date_closed"])
    )
    return merged.loc[mask]


def _dedup_matches(matches: pd.DataFrame) -> pd.DataFrame:
    """Deduplicate on (r_case_number, c_case_number), keeping best score."""
    n_before = len(matches)
    if "fuzzy_score" in matches.columns:
        matches = matches.sort_values("fuzzy_score", ascending=False)
    matches = matches.drop_duplicates(subset=["r_case_number", "c_case_number"])
    if len(matches) < n_before:
        print(f"  ⚠ Removed {n_before - len(matches):,} duplicate (r_case, c_case) pairs")
    return matches


# ---------------------------------------------------------------------------
# OUTPUT COLUMNS — kept consistent across match methods
# ---------------------------------------------------------------------------
_OUTPUT_COLS = [
    "r_case_number", "c_case_number",
    "r_date_filed", "r_date_closed", "c_date_filed",
    "r_company_name", "r_state", "r_city",
    "c_company_name", "c_state", "c_city",
    "match_company_r", "match_company_c",
    "match_state_r", "match_state_c",
    "match_city_r", "match_city_c",
    "match_method", "fuzzy_score",
]


# ---------------------------------------------------------------------------
# EXACT MATCHING — original equi-join logic
# ---------------------------------------------------------------------------
def match_exact(
    rc_slim: pd.DataFrame,
    ac_slim: pd.DataFrame,
    city_threshold: float = 85,
) -> pd.DataFrame:
    """
    Equi-join on (match_company, match_state) with fuzzy city gate, then
    date filter.

    City gate: exact city match is accepted; otherwise fuzz.ratio >=
    *city_threshold* is required.
    """
    from rapidfuzz import fuzz as rfuzz

    print(f"\n── Exact matching on (company, state) + fuzzy city "
          f"(threshold={city_threshold}) ──")

    CHUNK_SIZE = 5_000
    chunks = [rc_slim.iloc[i:i + CHUNK_SIZE]
              for i in range(0, len(rc_slim), CHUNK_SIZE)]

    result_parts = []
    total_candidates = 0

    for chunk in tqdm(chunks, desc="Exact RC → AC", unit="chunk"):
        merged = chunk.merge(
            ac_slim,
            on=["match_company", "match_state", "match_region"],
            how="inner",
            suffixes=("", "_ac"),
        )
        total_candidates += len(merged)

        # ---- Fuzzy city gate ----
        if not merged.empty:
            city_exact = merged["match_city"] == merged["match_city_ac"]
            city_needs_fuzzy = ~city_exact
            if city_needs_fuzzy.any():
                city_scores = merged.loc[city_needs_fuzzy].apply(
                    lambda row: rfuzz.ratio(
                        row["match_city"], row["match_city_ac"]
                    ),
                    axis=1,
                )
                city_pass = city_exact.copy()
                city_pass.loc[city_needs_fuzzy] = city_scores >= city_threshold
            else:
                city_pass = city_exact
            merged = merged.loc[city_pass]

        result_parts.append(_apply_date_filter(merged))

    matches = pd.concat(result_parts, ignore_index=True)
    matches["match_method"] = "exact"
    matches["fuzzy_score"] = 100.0

    # Build _r / _c columns for a consistent output schema.
    matches["match_company_r"] = matches["match_company"]
    matches["match_company_c"] = matches["match_company"]
    matches["match_state_r"]   = matches["match_state"]
    matches["match_state_c"]   = matches["match_state"]
    matches["match_city_r"]    = matches["match_city"]
    matches["match_city_c"]    = matches["match_city_ac"]
    matches.drop(columns=["match_company", "match_state",
                           "match_city", "match_city_ac"],
                 inplace=True)

    print(f"  Candidate pairs after location join: {total_candidates:,}")
    print(f"  Matches after date-window filter:    {len(matches):,}")

    return _dedup_matches(matches)


# ---------------------------------------------------------------------------
# FUZZY MATCHING — state-blocked, fuzzy company + city
# ---------------------------------------------------------------------------
def match_fuzzy(
    rc_slim: pd.DataFrame,
    ac_slim: pd.DataFrame,
    fuzzy_threshold: float = 82,
    city_threshold: float = 85,
) -> pd.DataFrame:
    """
    Fuzzy company-name matching, blocked by state.

    Within each state:
      1. Deduplicate company names on both sides to build a lookup table.
      2. For each unique RC company name, find AC company names with
         token_sort_ratio >= fuzzy_threshold.
      3. Expand back to case-level rows and check city similarity
         (exact match accepted; otherwise fuzzy >= city_threshold).
      4. Apply the date-window filter.

    Using token_sort_ratio rather than plain ratio because company names
    often have the same words in different orders (e.g. "acme steel corp"
    vs "steel corp acme").
    """
    rapidfuzz = _get_rapidfuzz()
    from rapidfuzz import fuzz, process

    print(f"\n── Fuzzy matching (company threshold={fuzzy_threshold}, "
          f"city threshold={city_threshold}) ──")
    print(f"  Blocking on normalised state + region …")

    # Group by (state, region) — region is an equi-key, exactly like state,
    # so fuzzy name comparison only happens within the same Region.
    rc_by_block = dict(list(rc_slim.groupby(["match_state", "match_region"])))
    ac_by_block = dict(list(ac_slim.groupby(["match_state", "match_region"])))

    blocks_shared = sorted(set(rc_by_block) & set(ac_by_block))
    print(f"  (state, region) blocks with both RC and AC cases: {len(blocks_shared)}")

    result_parts = []
    total_candidates = 0

    for block in tqdm(blocks_shared, desc="Fuzzy by state+region", unit="block"):
        rc_state = rc_by_block[block]
        ac_state = ac_by_block[block]

        # --- Build unique company-name lists for this state ---
        rc_names = rc_state["match_company"].unique().tolist()
        ac_names = ac_state["match_company"].unique().tolist()

        if not rc_names or not ac_names:
            continue

        # --- For each RC company name, find fuzzy matches among AC names ---
        # rapidfuzz.process.extract returns [(match, score, index), ...]
        # We use cdist for efficiency when both sides are large, but
        # extract is simpler and fast enough with score_cutoff pruning.

        # Build a mapping: rc_name -> list of (ac_name, score)
        name_pairs = []
        for rc_name in rc_names:
            hits = process.extract(
                rc_name,
                ac_names,
                scorer=fuzz.token_sort_ratio,
                score_cutoff=fuzzy_threshold,
                limit=None,  # return all above threshold
            )
            for ac_name, score, _ in hits:
                # Note: this intentionally includes score-100 (exact name)
                # pairs.  In hybrid mode, duplicates with the exact pass
                # are removed afterwards in match_cases().
                name_pairs.append((rc_name, ac_name, score))

        if not name_pairs:
            continue

        # --- Expand name pairs back to case-level rows ---
        # Build temporary DataFrames for the merge
        pairs_df = pd.DataFrame(name_pairs,
                                columns=["match_company_rc", "match_company_ac",
                                         "fuzzy_score"])

        rc_state_slim = rc_state.rename(
            columns={"match_company": "match_company_rc"})
        ac_state_slim = ac_state.rename(
            columns={"match_company": "match_company_ac"})

        # Merge: pairs -> RC rows -> AC rows
        merged = (
            pairs_df
            .merge(rc_state_slim, on="match_company_rc", how="inner")
            .merge(ac_state_slim, on="match_company_ac", how="inner",
                   suffixes=("", "_ac_dup"))
        )

        total_candidates += len(merged)

        if merged.empty:
            continue

        # --- City gate: exact match OR fuzzy above city_threshold ---
        city_exact = merged["match_city"] == merged.get(
            "match_city_ac_dup", merged["match_city"])

        # Compute fuzzy city score only where exact didn't match
        if "match_city_ac_dup" in merged.columns:
            city_needs_fuzzy = ~city_exact
            if city_needs_fuzzy.any():
                city_scores = merged.loc[city_needs_fuzzy].apply(
                    lambda row: fuzz.ratio(
                        row["match_city"], row["match_city_ac_dup"]
                    ),
                    axis=1,
                )
                city_fuzzy_pass = city_scores >= city_threshold
                city_pass = city_exact.copy()
                city_pass.loc[city_needs_fuzzy] = city_fuzzy_pass
            else:
                city_pass = city_exact
        else:
            city_pass = city_exact

        merged = merged.loc[city_pass]

        if merged.empty:
            continue

        # --- Date-window filter ---
        merged = _apply_date_filter(merged)

        if merged.empty:
            continue

        # --- Harmonise columns to _r / _c naming convention ---
        # After the double merge we have:
        #   match_company_rc, match_company_ac  (from pairs_df)
        #   match_state (RC side), match_state_ac_dup (AC side)
        #   match_city  (RC side), match_city_ac_dup  (AC side)
        merged.rename(columns={
            "match_company_rc":  "match_company_r",
            "match_company_ac":  "match_company_c",
            "match_state":       "match_state_r",
            "match_city":        "match_city_r",
        }, inplace=True)

        # AC-side state/city may appear as _ac_dup suffixed columns
        if "match_state_ac_dup" in merged.columns:
            merged.rename(columns={"match_state_ac_dup": "match_state_c"},
                          inplace=True)
        else:
            # If no suffix collision, AC state has the same name as RC state
            # (both were "match_state" and the merge kept one copy because
            # they were identical — state is the blocking key).
            merged["match_state_c"] = merged["match_state_r"]

        if "match_city_ac_dup" in merged.columns:
            merged.rename(columns={"match_city_ac_dup": "match_city_c"},
                          inplace=True)
        else:
            merged["match_city_c"] = merged["match_city_r"]

        merged["match_method"] = "fuzzy"

        result_parts.append(merged)

    if result_parts:
        matches = pd.concat(result_parts, ignore_index=True)
    else:
        matches = pd.DataFrame(columns=rc_slim.columns.tolist()
                               + ac_slim.columns.tolist()
                               + ["match_method", "fuzzy_score"])

    print(f"  Candidate pairs after state block + fuzzy name + city gate: "
          f"{total_candidates:,}")
    print(f"  Matches after date-window filter: {len(matches):,}")

    return _dedup_matches(matches)


# ---------------------------------------------------------------------------
# STEP 2 — Match dispatcher
# ---------------------------------------------------------------------------
def match_cases(
    rc: pd.DataFrame,
    ac: pd.DataFrame,
    match_mode: str = "hybrid",
    fuzzy_threshold: float = 82,
    city_threshold: float = 85,
) -> pd.DataFrame:
    """
    Run matching in the requested mode and return a unified result table.
    """
    rc_slim, ac_slim = _prepare_slim_frames(rc, ac)

    if match_mode == "exact":
        matches = match_exact(rc_slim, ac_slim, city_threshold)

    elif match_mode == "fuzzy":
        matches = match_fuzzy(rc_slim, ac_slim, fuzzy_threshold, city_threshold)

    elif match_mode == "hybrid":
        # --- Pass 1: exact ---
        exact_matches = match_exact(rc_slim, ac_slim, city_threshold)

        # --- Pass 2: fuzzy on ALL RC cases ---
        # We run fuzzy against the full RC set so that an RC case which
        # already has an exact CA match can still pick up additional CA
        # matches that only surface through fuzzy name/city similarity.
        # After the fuzzy pass we remove any (RC, CA) pairs that the
        # exact pass already found, keeping only genuinely new pairs.
        print(f"\n  Running fuzzy pass on all {rc_slim['r_case_number'].nunique():,} "
              f"RC cases (not just unmatched) …")

        fuzzy_matches = match_fuzzy(
            rc_slim, ac_slim, fuzzy_threshold, city_threshold
        )

        # Remove fuzzy pairs that duplicate an exact pair
        if len(fuzzy_matches) > 0 and len(exact_matches) > 0:
            exact_pairs = set(
                zip(exact_matches["r_case_number"],
                    exact_matches["c_case_number"])
            )
            is_dup = fuzzy_matches.apply(
                lambda row: (row["r_case_number"], row["c_case_number"])
                in exact_pairs,
                axis=1,
            )
            n_dup = is_dup.sum()
            fuzzy_matches = fuzzy_matches[~is_dup]
            print(f"  Fuzzy pairs already found by exact pass (removed): {n_dup:,}")
            print(f"  New fuzzy pairs (additive):                        "
                  f"{len(fuzzy_matches):,}")

        matches = pd.concat([exact_matches, fuzzy_matches], ignore_index=True)
        matches = _dedup_matches(matches)

        print(f"\n  Combined matches (exact + fuzzy): {len(matches):,}")
    else:
        raise ValueError(f"Unknown match_mode: {match_mode!r}. "
                         f"Use 'exact', 'fuzzy', or 'hybrid'.")

    # ---- Ensure output columns exist and are in consistent order ----
    for col in _OUTPUT_COLS:
        if col not in matches.columns:
            matches[col] = np.nan

    matches = (
        matches[_OUTPUT_COLS]
        .sort_values(["r_case_number", "c_date_filed"])
        .reset_index(drop=True)
    )

    return matches


# ---------------------------------------------------------------------------
# STEP 3 — Diagnostics
# ---------------------------------------------------------------------------
def summarise(
    matches: pd.DataFrame,
    rc: pd.DataFrame,
    ac: pd.DataFrame,
    match_mode: str,
    fuzzy_threshold: float,
    city_threshold: float,
) -> str:
    lines = []
    lines.append("=" * 60)
    lines.append("MATCHING SUMMARY")
    lines.append("=" * 60)

    n_rc_total = rc["r_case_number"].nunique()
    n_ac_total = ac["c_case_number"].nunique()

    lines.append(f"\nMatch mode:  {match_mode}")
    if match_mode in ("fuzzy", "hybrid"):
        lines.append(f"  Company fuzzy threshold: {fuzzy_threshold}")
        lines.append(f"  City fuzzy threshold:    {city_threshold}")

    if len(matches) == 0:
        lines.append("\nNo matches found. See notes below for possible reasons.")
    else:
        n_rc_matched = matches["r_case_number"].nunique()
        n_ac_matched = matches["c_case_number"].nunique()

        lines.append(f"\nRC cases in dataset:       {n_rc_total:>10,}")
        lines.append(f"RC cases with ≥1 CA match: {n_rc_matched:>10,}  "
                      f"({100 * n_rc_matched / n_rc_total:.1f}%)")
        lines.append(f"\nCA cases in dataset:       {n_ac_total:>10,}")
        lines.append(f"CA cases matched to ≥1 RC: {n_ac_matched:>10,}  "
                      f"({100 * n_ac_matched / n_ac_total:.1f}%)")
        lines.append(f"\nTotal match pairs:         {len(matches):>10,}")

        # ---- Breakdown by match method ----
        method_counts = matches["match_method"].value_counts()
        lines.append(f"\nMatch pairs by method:")
        for method, count in method_counts.items():
            lines.append(f"  {method:>6s}: {count:>10,}  "
                          f"({100 * count / len(matches):.1f}%)")

        if "fuzzy" in method_counts.index:
            fuzzy_scores = matches.loc[
                matches["match_method"] == "fuzzy", "fuzzy_score"
            ]
            lines.append(f"\nFuzzy score distribution (fuzzy matches only):")
            lines.append(f"  mean   = {fuzzy_scores.mean():.1f}")
            lines.append(f"  median = {fuzzy_scores.median():.1f}")
            lines.append(f"  min    = {fuzzy_scores.min():.1f}")
            lines.append(f"  p10    = {fuzzy_scores.quantile(0.10):.1f}")
            lines.append(f"  p25    = {fuzzy_scores.quantile(0.25):.1f}")

        # ---- Distribution of CA per RC ----
        ac_per_rc = matches.groupby("r_case_number")["c_case_number"].nunique()
        lines.append(f"\nCA cases per matched RC case:")
        lines.append(f"  mean   = {ac_per_rc.mean():.2f}")
        lines.append(f"  median = {ac_per_rc.median():.1f}")
        lines.append(f"  max    = {ac_per_rc.max()}")
        lines.append(f"  p90    = {ac_per_rc.quantile(0.9):.0f}")
        lines.append(f"  p99    = {ac_per_rc.quantile(0.99):.0f}")

        # ---- Distribution of RC per CA ----
        rc_per_ac = matches.groupby("c_case_number")["r_case_number"].nunique()
        lines.append(f"\nRC cases per matched CA case:")
        lines.append(f"  mean   = {rc_per_ac.mean():.2f}")
        lines.append(f"  median = {rc_per_ac.median():.1f}")
        lines.append(f"  max    = {rc_per_ac.max()}")
        if (rc_per_ac > 1).sum() > 0:
            lines.append(f"  CA cases matched to >1 RC: {(rc_per_ac > 1).sum():,} "
                          f"({100 * (rc_per_ac > 1).mean():.1f}%)")

    lines.append("\n" + "=" * 60)
    lines.append("NOTES")
    lines.append("=" * 60)
    lines.append(textwrap.dedent("""\
    - Company-name matching uses the advanced preprocessing pipeline:
      preprocessing_v3.py (OCR fixes, slash handling, DBA removal,
      digit stripping, stop-word removal with hyphen guards, etc.)
      followed by name_standardization.py (canonical-form replacement
      for high-frequency firms such as USPS, GM, Kaiser, Ford, Red Cross).
    - Rows where company_name is actually an NLRB case number are
      filtered out before matching.
    - State and city are normalised with simple lowercasing and
      whitespace collapse.
    - R Cases with a missing date_closed are excluded from matching.
    - A single CA case *can* match multiple RC cases. The summary above
      reports how common this is so you can decide how to handle it.
    """))

    if match_mode in ("fuzzy", "hybrid"):
        lines.append(textwrap.dedent(f"""\
    Fuzzy matching details:
    - Blocking: exact match on normalised state.
    - Company similarity: rapidfuzz token_sort_ratio >= {fuzzy_threshold}.
      token_sort_ratio is order-invariant, so "acme steel" and "steel acme"
      score 100.
    - City gate: exact normalised city match accepted; otherwise
      rapidfuzz ratio >= {city_threshold} required.
    - In hybrid mode, fuzzy matching runs on ALL RC cases (not just
      those without an exact match). Pairs already found by the exact
      pass are then deduplicated, so fuzzy matches are strictly additive:
      they contribute new RC–CA pairs only. This ensures that an RC case
      with one exact CA match can still pick up additional CA matches
      that only surface through fuzzy similarity.
    - The fuzzy_score column records the company-name similarity score
      (100.0 for exact matches).
    - Preprocessed names and normalised locations are stored separately
      for each side: match_company_r / match_company_c,
      match_city_r / match_city_c, match_state_r / match_state_c.
      For exact matches these pairs are identical; for fuzzy matches
      they show exactly what was compared.
    """))

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def parse_args():
    parser = argparse.ArgumentParser(
        description="Match RC-type R Cases to CA-type C Cases.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
        Examples:
          python match_r_to_c_cases.py                           # hybrid (default)
          python match_r_to_c_cases.py --match-mode exact        # exact only
          python match_r_to_c_cases.py --match-mode fuzzy --fuzzy-threshold 85
          python match_r_to_c_cases.py --match-mode hybrid --fuzzy-threshold 80 --city-threshold 90
        """),
    )
    parser.add_argument(
        "--match-mode",
        choices=["exact", "fuzzy", "hybrid"],
        default="hybrid",
        help="Matching strategy (default: hybrid).",
    )
    parser.add_argument(
        "--fuzzy-threshold",
        type=float,
        default=82,
        help="Minimum token_sort_ratio for company-name fuzzy match "
             "(0–100, default: 82). Ignored in exact mode.",
    )
    parser.add_argument(
        "--city-threshold",
        type=float,
        default=85,
        help="Minimum fuzz.ratio for city when exact city match fails "
             "(0–100, default: 85). Ignored in exact mode.",
    )
    parser.add_argument(
        "--data-dir",
        type=str,
        default=".",
        help="Directory containing input parquet files (default: current dir).",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default=None,
        help="Directory for output files (default: same as --data-dir).",
    )
    parser.add_argument(
        "--company-column",
        type=str,
        default="company_name",
        help="Address-table column to use for company matching "
             "(default: company_name). Use 'cluster_representative' for "
             "cluster-based matching.",
    )
    parser.add_argument(
        "--output-prefix",
        type=str,
        default="rc_ac_matches",
        help="Prefix for output filenames (default: rc_ac_matches).",
    )
    return parser.parse_args()


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------
def main():
    args = parse_args()

    # Update paths if specified
    global DATA_DIR, R_CASES_FILE, R_ADDR_FILE, C_CASES_FILE, C_ADDR_FILE, OUTPUT_DIR
    DATA_DIR = Path(args.data_dir)
    R_CASES_FILE = DATA_DIR / "merged_R_CASES_final.parquet"
    R_ADDR_FILE  = DATA_DIR / "merged_R_CASES_ADDRESS_with_union_flag.parquet"
    C_CASES_FILE = DATA_DIR / "merged_C_CASES_final.parquet"
    C_ADDR_FILE  = DATA_DIR / "merged_C_CASES_ADDRESS_with_union_flag.parquet"
    OUTPUT_DIR   = Path(args.output_dir) if args.output_dir else DATA_DIR

    print(f"Match mode:        {args.match_mode}")
    if args.match_mode != "exact":
        print(f"Fuzzy threshold:   {args.fuzzy_threshold}")
        print(f"City threshold:    {args.city_threshold}")
    print()

    rc, ac = load_and_prepare(company_column=args.company_column)

    matches = match_cases(
        rc, ac,
        match_mode=args.match_mode,
        fuzzy_threshold=args.fuzzy_threshold,
        city_threshold=args.city_threshold,
    )

    summary = summarise(
        matches, rc, ac,
        match_mode=args.match_mode,
        fuzzy_threshold=args.fuzzy_threshold,
        city_threshold=args.city_threshold,
    )
    print("\n" + summary)

    # ---- Save outputs ----
    out_parquet = OUTPUT_DIR / f"{args.output_prefix}.parquet"
    out_csv     = OUTPUT_DIR / f"{args.output_prefix}.csv"
    out_summary = OUTPUT_DIR / f"{args.output_prefix}_summary.txt"

    matches.to_parquet(out_parquet, index=False)
    matches.to_csv(out_csv, index=False)
    with open(out_summary, "w", encoding="utf-8") as f:
        f.write(summary)

    print(f"\nOutputs saved:")
    print(f"  {out_parquet}")
    print(f"  {out_csv}")
    print(f"  {out_summary}")


if __name__ == "__main__":
    main()
