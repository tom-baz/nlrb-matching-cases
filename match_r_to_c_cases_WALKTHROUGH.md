# `match_r_to_c_cases.py` — One-Page Walkthrough

A map of what the script does, the order functions call each other, and what each
function is responsible for. Read this first, then open the file with an Outline
panel and click into functions as needed.

---

## 1. The big picture (the "spine")

The whole program is four steps, driven by `main()`:

```
main()
  ├─ parse_args()              # read CLI flags (--match-mode, thresholds, paths)
  ├─ load_and_prepare()        # STEP 1: load parquet, clean, preprocess names
  ├─ match_cases()             # STEP 2: run the chosen matching strategy
  │     └─ summarise()         # STEP 3: build the diagnostics text
  └─ (write .parquet / .csv / _summary.txt to disk)
```

If you only remember one thing: **`main` → `load_and_prepare` → `match_cases` → `summarise`.**
Everything else is a helper called from inside one of these.

---

## 2. Full call graph

Indentation = "calls". Helpers prefixed `_` are internal plumbing.

```
main()                              [line 853]  — entry point
│
├── parse_args()                    [789]  CLI argument definitions
│
├── load_and_prepare()             [138]  STEP 1 — produce clean rc, ac frames
│     ├── preprocess_company_series() [119]  → preprocess_employer()        (external)
│     │                                       → standardize_company_name()  (external)
│     ├── normalise_location()       [100]  lowercase / strip / de-punctuate
│     └── filter_case_numbers()             (external, from preprocessing_v3)
│
├── match_cases()                  [592]  STEP 2 — dispatcher by --match-mode
│     ├── _prepare_slim_frames()    [257]  slim columns + drop open/bad-date RC
│     │
│     ├── match_exact()            [336]   mode "exact" / hybrid pass 1
│     │     ├── _apply_date_filter() [298]
│     │     └── _dedup_matches()     [307]
│     │
│     └── match_fuzzy()            [412]   mode "fuzzy" / hybrid pass 2
│           ├── _get_rapidfuzz()    [70]   lazy import guard
│           ├── _apply_date_filter() [298]
│           └── _dedup_matches()     [307]
│
└── summarise()                    [669]  STEP 3 — diagnostics string
```

External dependencies (defined in other files):
- `preprocess_employer`, `filter_case_numbers` ← `preprocessing_v3.py`
- `standardize_company_name` ← `name_standardization.py`
- `rapidfuzz` (`fuzz`, `process`) ← third-party, imported lazily

---

## 3. What each function does (one line each)

| Function | Line | Responsibility |
|----------|------|----------------|
| `_get_rapidfuzz()` | 70 | Lazy-import `rapidfuzz`; raise a friendly error if it's not installed. Keeps exact-only runs dependency-free. |
| `normalise_location()` | 100 | Clean a **state/city** Series: lowercase, strip, drop `. , ' "`, collapse spaces. Blanks stay blank (never match on "nan"). |
| `preprocess_company_series()` | 119 | Run the **two-stage company-name pipeline**: `preprocess_employer()` then `standardize_company_name()`. |
| `load_and_prepare()` | 138 | **STEP 1.** Load 4 parquets → rename case-number cols → filter to RC/CA → parse dates → drop duplicate/flagged addresses → join cases to addresses → build `match_company`, `match_state`, `match_city`, `match_region`. Returns `(rc, ac)`. |
| `_prepare_slim_frames()` | 257 | Keep only matching columns; rename to `r_*`/`c_*`; drop RC cases with no close date or `closed < filed`. |
| `_apply_date_filter()` | 298 | The temporal rule: keep rows where `r_date_filed ≤ c_date_filed ≤ r_date_closed`. |
| `_dedup_matches()` | 307 | Collapse to one row per `(r_case_number, c_case_number)`, keeping the highest `fuzzy_score`. |
| `match_exact()` | 336 | Equi-join on `(company, state, region)`, then a city gate (exact OR fuzzy ≥ city_threshold), then date filter. Processes RC in 5k chunks. |
| `match_fuzzy()` | 412 | Block on `(state, region)`; within each block fuzzy-match company names (`token_sort_ratio ≥ fuzzy_threshold`), expand to rows, city gate, date filter. |
| `match_cases()` | 592 | **STEP 2 dispatcher.** Calls `_prepare_slim_frames`, then runs exact / fuzzy / hybrid; in hybrid, removes fuzzy pairs the exact pass already found (fuzzy is *additive*). Enforces output column order. |
| `summarise()` | 669 | **STEP 3.** Build the human-readable summary string (match rates, method breakdown, fuzzy-score distribution, CA-per-RC and RC-per-CA stats, notes). |
| `parse_args()` | 789 | Define and parse CLI flags. |
| `main()` | 853 | **Entry point.** Wire the four steps together and write outputs. |

---

## 4. The three matching modes (the one real branch)

`match_cases()` is where the logic forks on `--match-mode`:

```
exact   →  match_exact()                              only
fuzzy   →  match_fuzzy()                               only
hybrid  →  match_exact()   (pass 1)
        +  match_fuzzy()   (pass 2, on ALL RC cases)
        −  drop fuzzy pairs already found by exact     ← "additive" dedup
        =  concat → _dedup_matches()
```

**Why hybrid runs fuzzy on *all* RC cases (not just unmatched ones):** an RC case
that already has one exact CA match can still pick up *additional* CA matches that
only surface through fuzzy similarity. The exact-pair removal (lines 628–642)
guarantees fuzzy only contributes genuinely new pairs.

---

## 5. The matching keys (what "same workplace, same time" means here)

Every candidate pair must agree on all of these:

1. **company** — `match_company` (preprocessed name); exact in `match_exact`, `token_sort_ratio ≥ 82` in `match_fuzzy`.
2. **state** — `match_state`; always an exact equi-key.
3. **region** — `match_region`, the leading 2 digits of the case number (e.g. `07-CA-034444` → `07`); always an exact equi-key, like state.
4. **city** — `match_city`; exact OR `fuzz.ratio ≥ 85` (the "city gate").
5. **time** — `_apply_date_filter`: CA filed inside the RC's `[date_filed, date_closed]` window.

---

## 6. How to read it interactively (suggested order)

1. Open the file, open the **Outline** panel (VS Code: Explorer sidebar, or `Ctrl+Shift+O`).
2. Read `main()` top to bottom — it's the table of contents.
3. `Ctrl+Click` into `load_and_prepare()`. Skim the section comments (`# ---- ... ----`); each block is one cleaning step.
4. `Ctrl+Click` into `match_cases()`. Read the `if match_mode == ...` branch only.
5. Open `match_exact()` **or** `match_fuzzy()` — whichever mode you actually run — and ignore the other on the first pass.
6. Treat the `_`-prefixed helpers (`_prepare_slim_frames`, `_apply_date_filter`, `_dedup_matches`) as black boxes until something forces you in.

To *see* the data rather than read about it: paste `load_and_prepare()`'s body into a
notebook cell, run it, and inspect `rc.head()` / `ac.head()` — the `match_*` columns
make the logic concrete.
