# `add_cluster_representatives.py` — One-Page Walkthrough

A map of what this script does, the order functions call each other, and what each
function is responsible for. This is a **small, linear** script (123 lines, 4
functions) — read this once and the file is fully open to you.

---

## 1. The big picture (the "spine")

The job: take the LLM-CER clustering output (`cluster_assignments.csv`) and stamp a
**`cluster_representative`** column onto each address parquet, so that
`match_r_to_c_cases.py --company-column cluster_representative` can match on the
cluster name instead of the raw company name.

This is a **one-time prep step** you run *before* cluster-based matching.

```
main()
  ├─ load_cluster_lookup()        # build: preprocessed name → cluster representative
  └─ for each of the 2 address parquets:
        add_representatives()      # add the column, overwrite the parquet in place
```

There is **no branching logic** — it's a straight line that runs twice (once for the
R address table, once for the C address table).

---

## 2. Full call graph

Indentation = "calls". External functions are defined in other files.

```
main()                          [line 94]  — entry point
│
├── load_cluster_lookup()       [28]  read CSV → choose 1 representative per cluster
│                                      → return lookup table (name → representative)
│
└── add_representatives()       [57]  (called once per address parquet)
      └── preprocess_name()     [21]  → preprocess_employer()        (external)
                                      → standardize_company_name()   (external)
```

External dependencies (must match what `match_r_to_c_cases.py` uses):
- `preprocess_employer` ← `preprocessing_v3.py`
- `standardize_company_name` ← `name_standardization.py`

> **Key consistency point:** `preprocess_name()` here applies the **same two-stage
> pipeline** as `match_r_to_c_cases.py`. That is what makes the join keys line up — if
> these pipelines ever diverge, the cluster lookup will silently stop matching.

---

## 3. What each function does (one line each)

| Function | Line | Responsibility |
|----------|------|----------------|
| `preprocess_name()` | 21 | Run one name through the two-stage pipeline (`preprocess_employer` → `standardize_company_name`); return `""` for NaN. Same recipe as the matcher. |
| `load_cluster_lookup()` | 28 | Read `cluster_assignments.csv`; pick **one representative per cluster** (the *shortest* `company_name`); return a deduped `name → cluster_representative` lookup. |
| `add_representatives()` | 57 | For one address parquet: preprocess names, left-join to the lookup, fall back to the preprocessed name when no cluster is found, and **overwrite the parquet in place**. |
| `main()` | 94 | Entry point: parse args, build the lookup once, then run `add_representatives()` on both the R and C address tables. |

---

## 4. The data flow inside `add_representatives()` (the heart of it)

```
read parquet
   │
   ├─ drop any old cluster_representative columns   (idempotent: safe to re-run)
   │
   ├─ df["_preprocessed"] = company_name → preprocess_name()
   │
   ├─ left-join lookup  ON _preprocessed == lookup.company_name
   │
   ├─ cluster_representative = cluster_representative.fillna(_preprocessed)
   │        └─ FALLBACK: names not in any cluster keep their own preprocessed name
   │
   ├─ drop helper columns (_preprocessed, company_name_cluster)
   │
   └─ write parquet back to the SAME path  (overwrites in place)
```

Two design choices worth noting:

- **Idempotent** (lines 65–66): it deletes any pre-existing
  `cluster_representative` columns before joining, so running the script twice is
  safe and won't create suffixed `_cluster` columns.
- **Graceful fallback** (line 82): a company name that wasn't part of any cluster
  (e.g. a singleton, or a name unseen by the clustering step) still gets a usable
  value — its own preprocessed name. So the output column is **never empty**, and
  exact matching on it degrades to "match identical preprocessed names" rather than
  dropping the row.

---

## 5. How the "representative" is chosen

In `load_cluster_lookup()` (lines 39–44): within each `global_cluster_id`, sort the
member names by **string length** and keep the **shortest** as the representative.

```
cluster 1234:  ["acme steel corporation", "acme steel", "acme steel co"]
                                  │
                                  └─ representative = "acme steel"   (shortest)
```

Rationale: the shortest name is usually the cleanest "core" of the entity (fewer
suffixes/qualifiers), so it's a stable canonical label for the whole cluster.

> ⚠️ It's a deterministic but arbitrary tiebreak — if two names tie on length,
> `drop_duplicates(keep="first")` after a length-sort picks whichever pandas ordered
> first. Fine for a representative *label*, but don't read meaning into *which* of two
> equally-short names won.

---

## 6. How to read it interactively (suggested order)

1. Open the file with the **Outline** panel (VS Code: `Ctrl+Shift+O`). You'll see all
   four functions at once — that *is* the whole structure.
2. Read `main()` (line 94) — it's short and shows the two-step flow.
3. Read `load_cluster_lookup()` to see how the lookup table is built.
4. Read `add_representatives()` alongside the data-flow diagram in §4 above.
5. To *see* it: in a notebook, call `lookup = load_cluster_lookup("cluster_assignments_20260517.csv")`
   and inspect `lookup.head()`; then read one address parquet and watch the
   `_preprocessed` → `cluster_representative` columns line up.

---

## 7. Where this fits in the pipeline

```
cluster_assignments_20260517.csv
        │
        ▼
add_cluster_representatives.py        ← (this script) stamps cluster_representative
        │                                onto both address parquets, in place
        ▼
match_r_to_c_cases.py  --match-mode exact
                       --company-column cluster_representative
                       --output-prefix rc_ac_cluster_matches_20260517
        │
        ▼
rc_ac_cluster_matches_20260517.parquet / .csv
```

So: **this script must run first** (and be re-run whenever the clustering output
changes), because it produces the `cluster_representative` column the matcher reads.
