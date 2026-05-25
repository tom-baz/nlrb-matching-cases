"""
Add cluster representative names to R/C address parquet files.

Joins cluster_assignments.csv to each address table on the preprocessed
company name, adding a ``cluster_representative`` column.  This column
can then be fed to match_r_to_c_cases.py via --company-column to run
cluster-based matching.

Usage:
    python add_cluster_representatives.py
    python add_cluster_representatives.py --cluster-file path/to/cluster_assignments.csv
"""

import argparse
import pandas as pd
from pathlib import Path
from preprocessing_v3 import preprocess_employer
from name_standardization import standardize_company_name


def preprocess_name(name):
    """Two-stage preprocessing (same pipeline as match_r_to_c_cases.py)."""
    if pd.isna(name):
        return ""
    return standardize_company_name(preprocess_employer(str(name)))


def load_cluster_lookup(path):
    """Build a lookup: preprocessed company_name -> cluster_representative."""
    print(f"Loading cluster assignments from {path} …")
    ca = pd.read_csv(
        path,
        usecols=["company_name", "global_cluster_id", "cluster_size"],
        low_memory=False,
    )
    print(f"  {len(ca):,} records, {ca['global_cluster_id'].nunique():,} clusters")

    # Pick representative per cluster: shortest name
    reps = (
        ca.sort_values("company_name", key=lambda s: s.str.len())
        .drop_duplicates(subset="global_cluster_id", keep="first")
        [["global_cluster_id", "company_name"]]
        .rename(columns={"company_name": "cluster_representative"})
    )

    # Map every name in the cluster to the representative
    lookup = ca[["company_name", "global_cluster_id"]].merge(
        reps, on="global_cluster_id", how="left"
    )
    lookup = lookup[["company_name", "cluster_representative"]].drop_duplicates(
        subset="company_name"
    )
    print(f"  {len(lookup):,} unique names in lookup")
    return lookup


def add_representatives(addr_path, lookup):
    """Add cluster_representative column to an address parquet file."""
    df = pd.read_parquet(addr_path)
    n_total = len(df)
    print(f"  Rows: {n_total:,}")

    # Drop any pre-existing cluster_representative column from a prior run,
    # so this script is idempotent and the merge below isn't suffixed.
    df.drop(columns=["cluster_representative", "cluster_representative_cluster"],
            errors="ignore", inplace=True)

    # Preprocess company names to match the cluster lookup keys
    df["_preprocessed"] = df["company_name"].apply(preprocess_name)

    # Left-join to cluster lookup
    df = df.merge(
        lookup,
        left_on="_preprocessed",
        right_on="company_name",
        how="left",
        suffixes=("", "_cluster"),
    )

    # Fall back to preprocessed name when no cluster was found
    n_matched = df["cluster_representative"].notna().sum()
    df["cluster_representative"] = df["cluster_representative"].fillna(df["_preprocessed"])

    # Clean up helper columns
    df.drop(columns=["_preprocessed", "company_name_cluster"], errors="ignore", inplace=True)

    print(f"  Cluster match: {n_matched:,} / {n_total:,} ({100 * n_matched / n_total:.1f}%)")
    print(f"  No cluster (fallback to preprocessed name): {n_total - n_matched:,}")

    df.to_parquet(addr_path, index=False)
    print(f"  Saved -> {addr_path}")


def main():
    parser = argparse.ArgumentParser(
        description="Add cluster representative names to address parquet files."
    )
    parser.add_argument(
        "--cluster-file", default="cluster_assignments.csv",
        help="Path to cluster_assignments.csv (default: ./cluster_assignments.csv)",
    )
    parser.add_argument(
        "--data-dir", default=".",
        help="Directory containing address parquet files (default: current dir)",
    )
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    lookup = load_cluster_lookup(args.cluster_file)

    for fname in [
        "merged_R_CASES_ADDRESS_with_union_flag.parquet",
        "merged_C_CASES_ADDRESS_with_union_flag.parquet",
    ]:
        path = data_dir / fname
        print(f"\nProcessing {fname} …")
        add_representatives(path, lookup)

    print("\nDone.")


if __name__ == "__main__":
    main()
