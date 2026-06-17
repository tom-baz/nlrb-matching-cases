# Methods Write-up — Resolving Multi-Linked C Cases via Region & ZIP

**Date:** 2026-06-02
**Scope:** Diagnosing and partially resolving the problem of a single C Case (CA charge) being matched to multiple R Cases (RC petitions) in the RC→CA matching pipeline, using two new discriminators — **NLRB Region** and a **validated ZIP-reliability flag**.

---

## 1. Background — the problem

The matching pipeline (`match_r_to_c_cases.py`) links RC petitions to CA charges on **company name + city + date window**. With those keys, one CA charge can end up attached to **several RC petitions**. This is sometimes legitimate and sometimes a matching error:

- **Legitimate:** different bargaining units inside one establishment each petitioned, or one company-wide ULP genuinely affected several establishments.
- **Error:** the same CA charge is wrongly attached to two different *branches* of a firm in the same city (only one truly filed), or fuzzy/cluster name-collapsing merged firms that are not the same entity.

Today's work built two notebooks to (a) quantify and characterise this, and (b) test whether ZIP can help separate the legitimate cases from the errors — after first establishing whether the ZIP data is even trustworthy.

---

## 2. Notebooks created today

### 2.1 `investigate_c_to_multiple_r.ipynb`
Investigates C Cases matched to multiple R Cases, across **both** matching outputs (`rc_ac_matches.parquet` = fuzzy/hybrid; `rc_ac_cluster_matches_20260517.parquet` = cluster).

What it checks, by section:
1. **Prevalence** — how many CA cases are matched to >1 RC.
2. **Distribution** — the full `RC-per-CA` distribution and its tail.
3. **Region consistency** — cross-region rate across all pairs (a clean overall quality metric). Region = leading digits of the case number; a genuine RC–CA pair should share a Region.
4. **Characterisation** — per multi-R group, a `region_flag` (within-region vs crosses-regions) × `geo_pattern` (different cities / same city, diff zip / same city, same-or-blank zip), with an `ca_nxgen` caveat flag.
5. **Method breakdown** — whether multi-R links lean on the exact or fuzzy pass.
6. **Examples** — sampled groups for eyeballing.
7. **ZIP-reliability-gated branch analysis** *(added today)* — joins the validated `zip_reliable` flag and runs three tests: **coverage**, **characterize**, **resolve** (see §4.5).
8. **Export** — per-group profiles + link-level detail for review.

### 2.2 `validate_zip_city_state.ipynb`
Checks, for every address row, whether the **ZIP is actually located in the city & state listed**, and produces a per-case reliability flag.

What it checks:
- **Reference:** GeoNames US postal dataset (`geonames_US.zip`, public domain) — authoritative state, primary place name, and lat/lon centroid per ZIP.
- **State check:** ZIP's GeoNames state must equal the listed state (exact, authoritative).
- **City check (geographic):** passes if the normalised city equals the ZIP's place name, *or* the ZIP centroid is within `DIST_KM` (40 km) of the claimed city's centroid; fuzzy name fallback when the city isn't in the reference. City names normalised on both sides (`norm_city`: expands `st`/`ste`/`mt`/`ft` and directional prefixes, treats hyphens as spaces).
- **Unified `zip_reliability` flag** across eras: NxGen uses the source authors' own flag (HQ-aware); CHIPS/CATS derive from the GeoNames verdict. `reliability_basis` records which logic was used.

---

## 3. ZIP provenance — what we learned from the source build scripts

Before trusting ZIP, we traced how city/state/ZIP were built per filing system (in `../nlrb-creating-files/`). Key finding: **the merged address tables dropped two NxGen quality columns** (`zip_reliability`, `data_notes`), and the eras differ fundamentally in provenance.

| Era | City/State source | ZIP source | HQ-contamination risk | Source validation |
|-----|-------------------|-----------|-----------------------|-------------------|
| **CHIPS** (R & C) | `Emp-City` / `State-final` (single employer address block) | `Employer_Zip` | Unknown **and undetectable** (one address field only) | **None** |
| **CATS C** | `C_CASE.Dispute_Loc_*` — the actual dispute location | `Dispute_Loc_Zip` | Low by design | Yes (91.6% vs participant) |
| **CATS R** | FRF/elections **unit location** (primary) → `R_PARTICIPANT Emp01` (fallback) | Emp01 zip | Low w/ FRF; HQ risk on fallback (documented) | Yes |
| **NxGen R/C** | City column (validated establishment) | Participants employer zip | zip HQ-prone (R **keeps** HQ zips w/ flag; C **nulls** mismatched zips at source) | Yes (`zip_reliability`) |

Mechanism details (verified in code):
- **The merge drops the flag columns** via a "select required columns" step in `merge_{R,C}_CASES_ADDRESS.ipynb`; it does not touch the ZIP values.
- **NxGen R** retained ~7,114 `potentially_hq` ZIPs (corporate HQ, not establishment) — the cause of the NxGen-R state-mismatch spike.
- **NxGen C** nulled mismatched ZIPs at *source creation* (45,090 `city_mismatch` + 9,642 `missing` → blank), so the merged C ZIPs are clean but ~22% missing.
- The R merge's `state_mismatches_CORRECTED.csv` is **diagnostic only** (not applied); the C merge's intended city/state validation **crashed** (broken `uszipcode`) and never ran — so the GeoNames notebook is the first working city/state check on the C side.
- CHIPS raw also contains an employer **street address (`Emp-Address`)** that was dropped in intermediate creation (recoverable only by re-parsing `namtxt*.txt`). Decided **not** to use street for now (messy free-text; doesn't fix provenance).

---

## 4. Findings

### 4.1 Prevalence of multi-linked C Cases
| Method | Matched CA cases | CA matched to >1 RC | % | max RC/CA | excess links |
|--------|------------------|---------------------|---|-----------|--------------|
| fuzzy | 46,573 | 2,609 | 5.6% | 17 | 3,899 |
| cluster | 55,611 | 3,496 | 6.3% | 17 | 5,120 |

### 4.2 Region consistency (the decisive discriminator)
- **All pairs:** cross-region rate ~2% (fuzzy 2.07%, cluster 2.17%) — a clean quality metric.
- **Multi-R groups:** cross-region ~9% (fuzzy 224/2,609 = 8.6%; cluster 317/3,496 = 9.1%) — ~4× the baseline, confirming multi-R groups disproportionately harbour spurious links. A charge cannot really span Regions, so cross-region links are high-confidence drop candidates.
- The genuine "same ULP, multiple establishments in different cities" case is **rare** — within-region + different-cities = only 18 (fuzzy) / 35 (cluster) groups.

### 4.3 ZIP reliability flag — validated
- **State dimension cross-validated** against an independent ZIP-prefix→state map: **99.9% agreement** (R 99.93%, C 99.96%).
- **`reliable` class is high-precision** (spot-checks found no false-reliable). All flag errors are conservative (false-*unreliable*, never false-reliable).
- A **city-normalisation fix** + a **verdict split** (`city_mismatch` = ZIP genuinely far; `city_unconfirmed` = small city not in GeoNames, ZIP usually fine → `unverifiable`) tightened the `unreliable` class to genuine problems only.
- **Final unified reliability:**
  - R: reliable **161,967 (82.0%)** / unreliable 11,290 / unverifiable 13,786 / missing 10,408
  - C: reliable **877,693 (84.5%)** / unreliable 66,185 / unverifiable 62,015 / missing 32,869
- **Known limit:** `unverifiable` is dominated by suburbs/neighbourhoods/retired ZIPs absent from GeoNames' one-place-per-ZIP export — not bad ZIPs. Fully resolving them needs a richer ZIP→multiple-cities crosswalk (e.g. USPS), not more regex.

### 4.4 ZIP era breakdown (rows with a ZIP, % consistent)
| Era | R-side valid | C-side valid |
|-----|--------------|--------------|
| CHIPS | 85.7% | 86.4% |
| CATS | 88.9% | 90.1% |
| NxGen | 82.3% (R: HQ-zip issue) | 95.4% |

Note: NxGen city↔ZIP consistency is **not** worse than older eras among rows that have a ZIP — the NxGen issues are (a) missingness (C-side) and (b) HQ ZIPs (R-side), not city drift.

### 4.5 Does reliable ZIP help resolve the multi-R groups?
Applying the unified `zip_reliable` flag inside the multi-R groups (notebook §7):

- **Coverage — high.** ~81% of multi-R groups are "resolve-ready" (C ZIP reliable **and** ≥2 R cases with reliable ZIPs): fuzzy 2,108/2,609 (80.8%), cluster 2,832/3,496 (81.0%).
- **Characterize.** Of the raw `same city, diff zip` branch signals, ~80% **survive** when restricted to reliable ZIPs (fuzzy 347/437 = 79.4%; cluster 463/573 = 80.8%) — the rest were ZIP-data artifacts.
- **Resolve.**
  - ~85% of resolve-ready groups are **same reliable ZIP** → confirmed legitimate *same establishment*, not errors.
  - Genuine branch ambiguity (≥2 *distinct* reliable R ZIPs + reliable C ZIP): 315 (fuzzy) / 427 (cluster) groups.
  - The C ZIP **resolves** 263 (fuzzy) / 359 (cluster) of them to a single branch → keep the matching R, drop the others (removes **418 / 538** spurious R links).
  - 52 (fuzzy) / 68 (cluster) have the C case at a *third* ZIP → flagged for manual review.

**Net:** ZIP is a precise scalpel — it clears the legitimate same-place majority, resolves a few hundred genuine branch errors (~11% of excess fuzzy links directly), filters ~20% ZIP-noise, and flags a small residue. It **composes with** the Region filter (which handles cross-region links separately).

---

## 5. Data files produced today

| File | Description |
|------|-------------|
| `investigate_c_to_multiple_r.ipynb` | Multi-R-per-C investigation (region + ZIP-gated) |
| `validate_zip_city_state.ipynb` | ZIP↔city/state validation + unified reliability flag |
| `geonames_US.zip` | GeoNames US postal reference crosswalk (cached) |
| `zip_validation_R_cases.csv` / `zip_validation_C_cases.csv` | Per-case ZIP flags: `verdict`, `zip_valid`, `zip_reliability`, `reliability_basis`, `source_zip_reliability`, `zip_reliable`, `dist_km` |
| `multi_r_per_c_{fuzzy,cluster}_profile.csv` | Per multi-R CA group: region/geo labels |
| `multi_r_per_c_{fuzzy,cluster}_detail.csv` | Link-level detail for every multi-R CA group |
| `multi_r_zip_resolvable_{fuzzy,cluster}.csv` | Groups the C-ZIP test could disambiguate (`c_relzip`, outcome, `n_keep`, `n_drop_diff_branch`) |

---

## 6. Interpretation guidance (for downstream analysis)

A two-layer strategy emerged. **Clean what you can at the data level first; use statistics for the residual you cannot resolve.**

- **Don't gate on ZIP.** Requiring a reliable ZIP would drop cases *non-randomly* (CHIPS era, small towns, territories), biasing time trends and cross-sectional comparisons. Use ZIP as a **subtractor** (remove links it actively contradicts) and a **confidence tier** (`high` = ZIP-confirmed; `medium` = ZIP unavailable; `low` = ZIP-contradicted), never as an inclusion gate.
- **Decide the unit of analysis & measure.** For petition-level outcomes (election win, case duration), the **R case** is the right unit; encode ULP exposure as **both** an indicator (`any_ulp`) and a count (`n_ulp`) and report both — the count tests dose-response but is more sensitive to spurious links; the indicator is more robust but coarser.
- **The multiplicity manifests as predictor measurement error + non-independence**, fixed mainly by cleaning links (region + ZIP) plus:
  - **Clustered standard errors** (by establishment or shared C case) — R cases sharing a ULP are not independent; clustering keeps significance honest (changes SEs, not coefficients).
  - **Sensitivity analysis** — re-run with spurious links (cross-region + ZIP-contradicted) in vs out; if the coefficient is stable, the residual ambiguity doesn't threaten the result.
- **Caveat:** statistics handles random-ish error and dependence, but **not systematic bias** (if spurious links correlate with the outcome). That is why upstream link-cleaning matters.

---

## 7. Next steps

1. **Bake the region-consistency filter into `match_r_to_c_cases.py`** — drop (or flag) cross-region RC–CA links. Highest-confidence, cheap win (~2% of all pairs). *(Planned; not yet implemented.)*
   - Caveat to encode: NLRB region renumbering/consolidation over 1984–present could create a few false cross-region flags at reorganised boundaries — confirm before hard-dropping.
2. **Decide whether to apply the ZIP-resolvable drops** (`multi_r_zip_resolvable_*.csv`) to the match output, or keep them as flags. Recommendation: flag, don't silently drop.
3. **Re-join `zip_reliability` from the NxGen source parquets into the merged address tables** (cheap; keys already aligned via `standardize_case_number`) so the flag survives downstream. Optionally restore `data_notes`.
4. **Add a `match_confidence` tier + `ambiguous_multi_r` flag** to the match output (high / medium / low per §6) rather than a hard filter.
5. **Manual review** of the residue: the 52 (fuzzy) / 68 (cluster) "C at a third ZIP" groups, plus NxGen-only diff-ZIP and suspected name over-merges.
6. **Optional, lower priority:**
   - Richer ZIP→multiple-cities crosswalk (USPS) to confirm the `unverifiable` suburbs.
   - Re-extract CHIPS `Emp-Address` (street) only if same-city branch disambiguation for the CHIPS era becomes necessary (decided against for now).
7. **At analysis time:** implement clustered SEs + the indicator/count + sensitivity-analysis plan from §6.
