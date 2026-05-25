# Manual Evaluation: Fuzzy vs. Cluster Matching

## Purpose

Estimate the **precision** of each matching method (fuzzy and cluster) by manually labeling a stratified random sample of RC×CA match pairs. The design is **blinded** — the labeler does not know which method flagged each pair, so judgment is not biased toward the expected "better" method.

Precision (not recall) is what we measure here. Recall would require sampling from the population of *non-matches*, which is intractable: with ~100 million possible RC×CA pairs and very few true matches, uniform sampling would yield essentially zero true positives.

## Three source cells

The sample is drawn from three disjoint sets of pairs:

| Cell | Definition | Pool used for sampling | Sampled | Stratification |
|---|---|---:|---:|---|
| **Agreement** | Both fuzzy and cluster say match, **and preprocessed names differ** | 9,688 | 50 | none |
| **Fuzzy-only** | Fuzzy says match, cluster doesn't | 1,046 | 100 | 50 from `score ∈ [82, 90)`, 50 from `[90, 100]` |
| **Cluster-only** | Cluster says match, fuzzy doesn't | 11,305 | 100 | 50 from `cluster_size ≤ 5`, 50 from `cluster_size > 5` |

Total: **250 pairs** to label.

### Why the agreement cell is filtered

Both methods operate on **preprocessed** names. About 80% of all agreement pairs
(39,738 out of 49,426) have *identical* preprocessed names — meaning both methods
linked them trivially by simple string equality, not by any real entity-resolution
work. A random sample of 50 from the full agreement pool would be dominated by
these trivial cases and waste labeling effort.

Restricting the agreement sample to pairs where preprocessed names **differ**
(9,688 pairs) tests the meaningful agreement cases: where fuzzy linked them via
token similarity ≥ 82 **and** clustering independently linked them by placing both
names in the same LLM-derived cluster.

The **fuzzy-only** and **cluster-only** cells are structurally guaranteed to be
non-trivial — if preprocessed names were identical, both methods would link the
pair and it would land in the agreement cell. So no filter is needed there.

## Files

| File | Role |
|---|---|
| `build_evaluation_sample.ipynb` | Builds the stratified sample (seeded, reproducible) |
| `analyze_evaluation_results.ipynb` | Unblinds the labels and reports precision per cell and per stratum |
| `evaluation_sample.csv` | **The file you label.** 250 rows, no methodology hints |
| `evaluation_sample_key.csv` | Hidden unblinding key (`pair_id → source_cell`, stratum, scores). **Do not open until labeling is complete.** |

## Workflow

### Step 1 — Build the sample (already done once)

```powershell
jupyter nbconvert --to notebook --execute --inplace build_evaluation_sample.ipynb
```

Produces `evaluation_sample.csv` and `evaluation_sample_key.csv`. Both are seeded (`SEED=42`), so re-running gives an identical draw. If you want a different sample, change `SEED` at the top of the notebook.

### Step 2 — Label the sample manually

Open `evaluation_sample.csv` in Excel, Google Sheets, or any CSV editor. For each row, fill in the `label` column with exactly one of:

| Label | Meaning |
|---|---|
| `match` | The R-case and C-case clearly refer to the **same workplace** |
| `no_match` | The R-case and C-case clearly refer to **different workplaces** |
| `unclear` | Not enough information to decide (use sparingly) |

Optionally fill `notes` with brief reasoning, especially for `no_match` and `unclear`.

Save back as CSV (preserve UTF-8 encoding and the original column order).

#### Visible context for each pair

The labeler sees:
- `r_case_number`, `c_case_number`
- `r_company_name`, `c_company_name` (original, not preprocessed)
- `r_state`, `r_city`, `c_state`, `c_city`
- `r_date_filed`, `r_date_closed`, `c_date_filed`

The labeler does **not** see fuzzy score, cluster size, method, or preprocessed/cluster-representative name, to prevent biased judgment.

#### Labeling rubric

- **Likely `match`:** same company name + same city + C-case filed during R-case active window. Subsidiaries, DBAs, division names, parent/child relationships, common abbreviations.
- **Likely `no_match`:** different industries, different addresses, names that only superficially resemble each other (e.g., both contain a common word like "Hilton", "Hospital", "Mechanical").
- **Likely `unclear`:** name is too generic (e.g., "ABC Inc."), city/state missing, only one side has identifying info, or the connection is plausible but not verifiable from the data shown.

### Step 3 — Analyze results

After labeling is done:

```powershell
jupyter nbconvert --to notebook --execute --inplace analyze_evaluation_results.ipynb
```

Or open it in Jupyter and run all cells. It will print:

1. **Label distribution** and any unlabeled rows (sanity check)
2. **Precision by source cell** — `match / (match + no_match)` for each of agreement / fuzzy-only / cluster-only
3. **Precision by stratum** — broken down by score band and cluster size
4. **Wilson 95% confidence intervals** on the per-cell precision estimates
5. **Sample of `no_match` (false positive) examples** per cell — useful for spotting error patterns
6. **Sample of `unclear` cases** — useful for understanding the ceiling on labelable accuracy
7. **Headline summary**

## Interpreting results

With n=100 per disagreement cell and n=50 for agreement, expect Wilson 95% margins of error in the ballpark of:
- ±5 pts when precision is near 95-100%
- ±10 pts when precision is near 50%

So an observation like "fuzzy-only precision is 60% (CI 50%-69%)" is solidly more informative than "fuzzy-only is sometimes wrong" — but you cannot distinguish, say, 60% from 65% at this sample size. For tighter intervals, raise `n` per cell in `build_evaluation_sample.ipynb` (e.g., to 200-300) and re-label.

## Customizing

To change sample sizes, strata, or score/cluster-size thresholds, edit `build_evaluation_sample.ipynb`:

- **Sample sizes:** the `.sample(n=...)` calls in the "Sample each stratum" cell.
- **Score bands:** the `low_band` / `high_band` filters (currently `[82, 90)` and `[90, 100]`).
- **Cluster-size cutoff:** the `small` / `large` filters (currently `≤5` and `>5`).
- **Seed:** the `SEED` constant at the top.

After editing, re-run the notebook end-to-end. The CSV will be regenerated and overwrite the previous one — **back up any in-progress labels first.**

## Recall (a note on what this evaluation does not measure)

This setup estimates **precision only** — of pairs a method calls a match, what fraction are correct.

It does **not** measure recall — of all true matches that exist, what fraction does the method find. Recall would require sampling from the "neither method linked them" cell, which has hundreds of thousands of pairs and a vanishingly low true-positive rate. A future extension could sample within plausible-candidate restrictions (same state, same city, overlapping date window) where neither method linked them — but defining "plausible candidate" carefully is its own design problem.

## Related files

- `compare_matching_methods.ipynb` — aggregate comparison of the two methods (counts, overlap, samples)
- `cluster_matching_guide.md` — how the cluster-based matching pipeline works
- `CLAUDE.md` — project overview
