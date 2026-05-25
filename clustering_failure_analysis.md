# LLM Clustering — Failure Analysis

Summary of where the LLM clustering pipeline (used in `rc_ac_cluster_matches_20260517.parquet`) misses true RC↔CA matches that fuzzy matching catches. Based on the 93 fuzzy-only pairs in the labeled evaluation sample (`evaluation_sample.csv`) that were manually labeled as true matches.

## Context

- **Cluster file evaluated:** `cluster_assignments_20260517.csv` (224,767 names across 91,120 clusters, of which 38,892 are singleton clusters from blocks; pre-blocking singletons are excluded by design).
- **Comparison method:** fuzzy matching from `match_r_to_c_cases.py` (hybrid mode, threshold 82).
- **Evaluation sample:** 250 stratified random pairs, manually labeled.
- **Cluster precision in the sample:** 100% (149 cluster-flagged pairs, no false positives).
- **Cluster recall gap:** 93 of 97 labeled fuzzy-only pairs are true matches that clustering missed — i.e., the recall side has a real, structured failure population.

This document characterizes those 93 misses.

## Findings — three failure modes, each roughly one third

| Failure mode | Count | Share | Where the failure occurred |
|---|---:|---:|---|
| LLM same-block split | 31 | 33% | The LLM saw both names in the same block but judged them as different entities |
| Blocking — different blocks | 28 | 30% | LSH put the two names in different blocks; LLM never compared them |
| Pre-blocking singleton (one or both) | 34 | 37% | Name(s) never reached the blocking stage; absent from the cluster file |

### Mode A — LLM same-block split (31 / 33%)

The LLM had both candidates in the same block and decided they're not the same entity. The errors look like obvious-to-a-human equivalences:

| R preprocessed | C preprocessed | Same block? |
|---|---|---|
| `st anthonys medical center h` | `st anthonys medical center` | block 787 (R: gcid 787_10, C: gcid 787_8) |
| `meadowlands hospital medical cntr` | `meadowlands hosp medical ctr` | block 3621 |
| `aggregate equipment and supply` | `bet services aggregate equipment and supply` | block 53454 (merged from 15506, 3259) |
| `bayou contracting` | `bayou construction` | block 54762 (merged from 26881, 11758) |

Pattern: truncation markers, abbreviation variants ("hospital" vs "hosp", "center" vs "cntr"), prefix words (parent/DBA), industry synonyms.

**Levers for future work:** prompt tuning, model swap, or a lightweight post-clustering pass that merges clusters within the same block when their representatives have very high string similarity (e.g., `token_sort_ratio ≥ 95`).

### Mode B — Blocking failure, different blocks (28 / 30%)

Both names exist in the cluster file but were placed in different LSH blocks, so the LLM never saw them as candidates.

| R preprocessed (block) | C preprocessed (block) |
|---|---|
| `m v transportation` (block 51) | `mv transportation` (block 585) |
| `shore-form` (block 62470) | `shor-form` (block 58007) |
| `bci coca cola bottling` (block 53160) | `coca cola bottling` (block 622) |
| `ha industries a division of a` (block 56674) | `ha industries a division of am castle and` (block 61006) |

Pattern: whitespace differences (`M V` vs `MV`), single-character typos (`Shore` vs `Shor`), prefix-word differences (`BCI` prefix), name truncations.

**Likely root cause:** the LSH stage uses OpenAI embeddings with a default `min_similarity` of 0.80. Small surface-level edits don't reliably produce embeddings within that threshold — embeddings encode meaning, not characters, so a one-letter typo can land the variant elsewhere in the embedding space.

**Levers for future work:** pre-normalize more aggressively before computing the LSH signature (strip whitespace/punctuation, normalize case); add a second blocker on a character-level key (e.g., first-N characters or a phonetic key) to catch what embedding similarity misses; or lower `min_similarity` (at the cost of more candidate pairs and higher LLM cost).

### Mode C — Pre-blocking singletons (34 / 37%)

One or both names didn't make it into any LSH block, so they're absent from `cluster_assignments_20260517.csv` entirely. The matching pipeline treats them as singletons (each represents only itself), so they can only match a same-preprocessed-name peer.

Subdivision:
- R is pre-blocking singleton: 12
- C is pre-blocking singleton: 13
- Both are pre-blocking singletons: 9

| R raw (preprocessed) | C raw (preprocessed) |
|---|---|
| `Pyromax` (`pyromax`) | `Pyomax, Inc.` (`pyomax`) — both absent |
| `MAGLA PRODUCTS, INC.` (`magla products`) | `MALGA PRODUCTS` (`malga products`) — both absent |
| `Jonis Realty Management` | `Janis Realty Management Inc.` — both absent |
| `UNIGORM PRINGTING AND SUPPLY` | `UNIFORM PRINTING & SUPPLY  INC.` (`uniform printing and supply`) — R absent |
| `City Stationery, Inc.` | `City Stationary, Inc.` (`city stationary`) — C absent |
| `Suiza Dairy Corp.` | `Suiza Diary Corporation` (`suiza diary`) — C absent |
| `B&B Trucking Co.` (`bandb trucking`) | `B & B Trucking Co.` (`b and b trucking`) — R absent |

Pattern: almost all are **one-letter typos**, **letter transpositions**, or **truncated names**. Many appear to be OCR-like corruptions of an otherwise common name.

**Hypothesized root cause:** the LSH blocker emits a name into the cluster file only if it found at least one LSH-candidate neighbor above the `min_similarity` threshold. A typo'd or unique-occurrence name with no embedding neighbor above 0.80 produces no candidate pairs and is dropped from the output rather than emitted as a singleton block.

**Levers for future work:**
- Add a typo-recovery pre-pass before the LSH stage that groups names within edit-distance ≤ 1 (or `token_sort_ratio ≥ 95`) and lets each group enter blocking as a unit.
- Emit unpaired names as singleton blocks rather than dropping them, so they at least appear in the cluster file as their own cluster (matching the matching-pipeline's existing fallback behavior).
- Accept this gap as a structural property of embedding-based LSH and **rely on fuzzy matching as an additive layer** for the typo class — fuzzy's `token_sort_ratio` catches one-letter typos trivially.

## Why the failure modes are structurally complementary to fuzzy

| | Catches | Misses |
|---|---|---|
| **LLM clustering** | Semantic equivalences: DBAs, parent/subsidiary, abbreviation expansions, brand variants, industry synonyms | Character-level typos (especially in short names with no neighbors) |
| **Fuzzy (`token_sort_ratio`)** | Character-level typos, word reorderings, minor edits | Semantic links where names share few characters (e.g., "Crothall Healthcare" vs "Compass Group d/b/a Crothall") |

The evaluation sample confirms this:
- **Fuzzy-only at score ≥ 90:** 100% precision (n=48) — almost entirely typo-recovery cases that clustering structurally cannot catch.
- **Cluster-only:** 100% precision (n=99) — almost entirely semantic-equivalence cases that fuzzy structurally cannot catch.

A hybrid (clustering as primary + fuzzy ≥ 90 as additive layer) is well-motivated for this reason, not just empirically.

## Where the real blocking work lives

The blocking that produced `cluster_assignments_20260517.csv` was run from:

```
C:\Users\PsyLab-9221\Documents\DIWA\nlrb-blocking
```

To investigate failure modes B and C above, look at that folder's current scripts and any logs/configs for the specific parameters used (`min_similarity`, `pre_filter_min_tokens`, blocker version, embedding model, etc.).

## Concrete next-step investigations

In rough order of likely payoff:

1. **Verify the parameters used for `cluster_assignments_20260517.csv`.** Specifically: `min_similarity`, `pre_filter_min_tokens`, `min_name_tokens`, and the embedding model. Without these confirmed, it's hard to know which lever to pull first.
2. **Add a typo-recovery pre-pass to the blocking stage.** Group names within `token_sort_ratio ≥ 95` (or edit-distance ≤ 1) before LSH, so typo variants enter blocking as a unit. Most directly addresses Mode C (~37% of the gap).
3. **Add a character-level secondary blocker** alongside the embedding-based one. Catches whitespace/punctuation/typo-driven block misalignments. Directly addresses Mode B (~30%).
4. **Within-block string-similarity merge post-pass.** Cheap to implement: for any two clusters in the same block with representatives at `token_sort_ratio ≥ 95`, merge them. Directly addresses Mode A (~33%).
5. **Or accept the gap and rely on fuzzy ≥ 90 as a recall booster.** Free, no new pipeline work, validated at 100% precision in the sample.

## Reference data

| File | Purpose |
|---|---|
| `evaluation_sample.csv` | Labeled sample (250 rows). Filter to `source_cell == 'fuzzy_only'` and `label == 'match'` for the 93-row diagnostic population. |
| `evaluation_sample_key.csv` | Unblinding key (source_cell, stratum, fuzzy_score, etc.) |
| `analyze_evaluation_results.ipynb` | Generates the precision tables and CI reported above |
| `rc_ac_matches.parquet` | Fuzzy matching output (50,472 pairs). Contains `match_company_r` / `match_company_c` (preprocessed names) |
| `rc_ac_cluster_matches_20260517.parquet` | Cluster matching output (60,731 pairs). Note: `match_company_r/c` here are cluster *representatives*, not preprocessed names |
| `cluster_assignments_20260517.csv` | Cluster file. Includes `block_id`, `original_block_ids`, `global_cluster_id`. Pre-blocking singletons are absent. |
| `merged_R_CASES_ADDRESS_with_union_flag.parquet` | R-side raw company names (input to preprocessing) |
| `merged_C_CASES_ADDRESS_with_union_flag.parquet` | C-side raw company names |

The reproducible diagnostic command (classifies each fuzzy-only true-match pair into one of the three failure modes) is in the conversation history that produced this document; rerunning it requires only the labeled CSV and the cluster file.
