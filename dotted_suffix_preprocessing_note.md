# Note: Dotted Legal Suffixes & Single-Pass Preprocessing in Cluster Matching

**Date:** 2026-06-11
**Status:** Known, minor, intentionally left as-is. Revisit only if dotted-acronym matches become important.

## TL;DR

The name-cleaning pipeline (`preprocessing_v3.py`) treats **dotted** legal suffixes
(`L.L.C.`, `L.T.D.`, `L.P.`, …) differently from their **undotted** forms (`LLC`, `LTD`, `LP`)
when run a single time. Cluster matching now runs the pipeline **exactly once** on
`cluster_representative`, so a handful of "same company, dotted vs. undotted" pairs no
longer match. This costs ~3 pairs out of ~59,000 (0.005%) and is accepted.

## The underlying quirk: the pipeline is not idempotent

`preprocess_employer()` performs two relevant steps **in this order**:

1. **Stop-word removal** (`preprocessing_v3.py` ~line 190). The regex looks for the
   suffix as contiguous letters, e.g. `\bllc\b`. It matches `llc` and `llc.`, but **not**
   `l.l.c.` — the dots break the letters apart, so a dotted suffix is **not recognized**.
2. **Punctuation stripping** (~line 204), which runs **after** step 1 and removes the dots.

Trace `DISH Network Service L.L.C.` through **one** pass:

- Step 1 sees `l.l.c.` → not recognized as `llc` → suffix **survives**.
- Step 2 strips the dots → `llc`.
- Result: `dish network service llc`  ← suffix still present.

Run a **second** pass on that result:

- Step 1 now sees a clean `llc` → recognized → **removed**.
- Result: `dish network service`.

So `preprocess(x) != preprocess(preprocess(x))` for dotted inputs. Measured impact of a
second pass: changes **476** R-side and **1,510** C-side address rows — all of the form
"strip a residual `llc`/`ltd`/etc."

Concretely, the same company written two ways diverges after **one** pass and converges
after **two**:

```
ONE pass  : ['dish network service llc', 'dish network service']   # L.L.C. vs LLC -> DON'T match
TWO passes: ['dish network service',     'dish network service']   # -> match
```

## Why cluster matching now runs preprocessing only once

`cluster_representative` is already preprocessed **once** upstream by
`add_cluster_representatives.py` (the cluster file's names, and the singleton fallbacks,
are both one-pass outputs).

Previously, `load_and_prepare()` in `match_r_to_c_cases.py` re-ran
`preprocess_company_series()` on `cluster_representative` — a redundant **second** pass
that, as a side effect, canonicalized dotted suffixes (`L.L.C.` ↔ `LLC`).

We changed `load_and_prepare()` so cluster mode uses the column **as-is**:

```python
if company_column == "company_name":
    df["match_company"] = preprocess_company_series(df[company_column])  # raw -> clean once
else:
    df["match_company"] = df[company_column].fillna("").astype(str)      # already clean upstream
```

Reasons:
- **Do not modify `preprocessing_v3.py`** — it was used to build the cluster file; changing
  it would desynchronize new cleaning from the existing clusters.
- **Preprocess exactly once** — conceptually clean; matches how the cluster file was built.

## The cost (measured)

Dropping the redundant second pass means dotted-suffix names keep their suffix and no
longer match their undotted twins. Net effect on the cluster output:

**59,415 → 59,412 pairs (−3).**

The exact 3 pairs lost (all genuine same-company, same-city, same-region matches):

| R case | C case | R name | C name |
|--------|--------|--------|--------|
| 13-RC-018503 | 13-CA-031168 | `L.T.D. COMMODITIES` | `LTD COMMODITIES` |
| 13-RC-018503 | 13-CA-031206 | `L.T.D. COMMODITIES` | `LTD COMMODITIES` |
| 22-RC-012235 | 22-CA-025342 | `22 Hillside, L.L.C.` | `22 Hillside LLC` |

(Two companies; the L.T.D. Commodities R-case matched two C-cases.)

These look like **true** matches, so the change costs a few real matches — but at 0.005%
of the output it is negligible.

## If you want to fix it in the future

Pick the option that fits; do **not** reintroduce a blanket double-pass, and do **not**
edit `preprocessing_v3.py` (cluster-file consistency).

1. **Targeted pre-normalization (recommended):** before matching, collapse dotted
   single-letter acronyms to their undotted form, e.g. regex
   `\b([a-z])\.(?=[a-z]\.)` style cleanup or specifically map `l.l.c.`→`llc`,
   `l.t.d.`→`ltd`, `l.p.`→`lp`. Apply it to `match_company` in `load_and_prepare()` for
   both R and C sides so both ends agree.
2. **Fix the ordering upstream (larger blast radius):** in a *future* preprocessing
   version, strip punctuation **before** stop-word removal so a single pass is idempotent.
   This would require **rebuilding the cluster file** with the new pipeline to stay
   consistent — only worth it if you are regenerating clusters anyway.

## Related

- Memory note: `cluster-coverage-and-preprocessing` (records the non-idempotency and this code change).
- Code: `match_r_to_c_cases.py` → `load_and_prepare()` (the once-vs-twice branch).
- Code: `preprocessing_v3.py` → `preprocess_employer()` (stop-word removal before punctuation stripping).
- Upstream: `add_cluster_representatives.py` (builds the one-pass `cluster_representative` column).
