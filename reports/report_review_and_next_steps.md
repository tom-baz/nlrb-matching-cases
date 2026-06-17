# Review of `report_1.md` and `report_2.md` — Gaps, Next Steps, and Further Reading

Audience: project notes for Tom. The two reports answer the same question — *how to compare fuzzy vs. LLM clustering on R↔C matching and validate the clustering itself* — and broadly converge on the same answer (complementarity, hybrid policy, independent clustering benchmark). The differences are mainly in emphasis and concreteness.

---

## 1. Side-by-side evaluation

### Where they agree
Both reports independently arrive at four claims that should be carried straight into the article:

1. The two methods are **structurally complementary**, not competitors: clustering catches semantic equivalences, fuzzy catches character-level perturbations.
2. The defensible operational policy is a **hybrid** with clustering as the backbone and high-threshold fuzzy (≥ 90) as a recall booster.
3. Matching-task evaluation is necessary but **insufficient** for the firm-aggregation claim — the clustering needs its own independent benchmark.
4. Global recall over the full R×C universe is not estimable; **conditional / gated recall** is the right target.

That convergence is itself useful evidence — two independently developed reasonings landing on the same recommendation tightens it.

### What `report_1.md` does better
- **Cleanest conceptual reframing** (§1): two tasks, two evaluations. This is the right backbone for the methods section.
- **Concrete recall mechanism**: Lincoln–Petersen + Chao on labeled cells, with the precision-correction step and the dependence-bias warning written out (§3.3). This is the part of the comparison most likely to survive peer review, and `report_2.md` only gestures at it.
- **Names the right tooling**: Binette et al. + the `ER-Evaluation` Python package (§4.2.1). That is the single most actionable pointer in either document.
- **Operationalizes the missing "agreement score"** as K-run consensus / cluster-wise Jaccard stability (§4.3), with a cost-control suggestion (sample blocks, not the whole corpus).
- **Stage table with cost estimates** (§5) — turns the report into a project plan.
- Specific worry about **cluster-representative collisions** under the shortest-name rule (§6) — neither I nor `report_2.md` had flagged this independently; it is a real bug surface.

### What `report_2.md` does better
- **Framing as two end-to-end pipelines, not two name-similarity functions** (§1). `report_1.md` implies this but never says it crisply, and it matters for the methods section — readers will otherwise critique a fuzzy/cluster comparison as if surface-string similarity were the only difference.
- **Coverage-denominator audit** (§1, last paragraph): raw 463,344 → unique preprocessed 334,276 → in-blocking 224,767 across 91,120 clusters → 38,892 in-block singletons → pre-blocking singletons absent by design. Insisting on a pipeline-flow figure is the right call and `report_1.md` does not require it.
- **Blocker vs. matcher as separately evaluable components** (§3, §4), with **pair completeness** as the blocker's own metric. `report_1.md` notices the blocker issue inside Mode B/C of the failure analysis but does not promote it to its own evaluation track.
- **Time-slice holdout** (Ullmann/Hennig/Boulesteix). Tuning prompts/thresholds on one era and locking the pipeline before evaluating on another is a reviewer-resistant move; `report_1.md` does not mention it.
- **Substantive robustness across linkage definitions** (§ "framing"): rerun the downstream sociology results on conservative / hybrid / expansive linksets and report stability. This is the most important sociology-specific recommendation in either report, and `report_1.md` omits it.
- **Provenance flags on every accepted link** — practical, operationalizable, and exactly the form downstream collaborators need.

### Where they conflict or are mutually weak
- **Cited evidence quality**. `report_2.md` cites with placeholder tokens (`fileciteturn0file3`, `turn22academia0`, etc.) that look like an unrendered search-grounded format. Before any of it is reused in a paper, the citations need to be resolved to real references; some of the "academia" tokens may not correspond to a stable, peer-reviewed source.
- **Recall is more rigorously treated in `report_1.md`** (capture–recapture with the dependence-bias caveat) than in `report_2.md` (gestures at PatentsView estimators without the Lincoln–Petersen mechanism).
- **Clustering independence is more rigorously treated in `report_2.md`** (separate blocker audit, pair completeness, time-slice holdout) than in `report_1.md` (which collapses blocker/matcher evaluation into Stage 3/4 internal diagnostics).
- Both reports are **silent on the establishment-vs-firm distinction** (see §2.1 below). This is the single largest conceptual gap in either document.

---

## 2. Crucial points both reports miss or underweight

### 2.1 Establishment ≠ firm
R Cases and C Cases are about **establishments** (workplaces) and that is exactly why the matching task already gates on city. The IC2S2 abstract, however, promises **firm-level aggregation** — a different object. McDonald's has thousands of establishments; clustering company names alone collapses them. Two consequences neither report draws out:

- The R↔C matching task and the firm-aggregation use case have **different correctness criteria**. A clustering can be excellent for firm aggregation (correctly grouping all Walmart establishments) yet wrong for R↔C matching at a specific store (because it loses the per-store identity that the city gate normally recovers).
- The clustering should carry a **two-level identity**: a `firm_id` (= cluster) and an `establishment_id` (cluster × city × zip, or similar). Without that, the abstract's claim is one level too coarse for the data it lives on.

This deserves a paragraph in the methods section and probably an explicit decision about which level the paper reports on.

### 2.2 Zip code (and NAICS, if present) as additional gates
The address tables carry **zip codes**, but `match_r_to_c_cases.py` only gates on state + (fuzzy) city. Adding zip as a soft tiebreaker on ambiguous chains (Walmart, USPS, Home Depot, large hospital systems) is cheap and gives you a cleaner over-merge audit without changing the clustering. The same applies to industry codes if the NLRB extracts carry them on either side. Neither report mentions this.

### 2.3 A third method baseline (probabilistic / `fastLink` / `Splink`)
The comparison as currently scoped is "string fuzzy vs. LLM clustering," which is two points on a much larger method spectrum. For a sociology audience the most expected omission is **Enamorado, Fifield & Imai's `fastLink`** (Fellegi–Sunter probabilistic record linkage, with documented use in political science / sociology). Including it as a third baseline — even at small scale — makes the "we chose LLM clustering" claim much more defensible because the comparison is no longer two-of-many. `Splink` (UK admin-data community) and `Magellan` (academic ER benchmark) are reasonable alternates.

### 2.4 LLM reproducibility / versioning
Neither report addresses what happens when the OpenAI/Anthropic model behind the LLM-CER step is retired or updated. For an academic paper this is a real liability: the cluster file `cluster_assignments_20260517.csv` is reproducible only against a specific model version. The methods section needs to fix (and record) the model identifier and prompt revision, and ideally archive prompts + raw LLM responses for the evaluated subset. `report_1.md` mentions date-suffix discipline but not model/prompt provenance.

### 2.5 Preprocessing is itself a methodological choice
`preprocessing_v3.py` + `name_standardization.py` do a lot of work — OCR fixes, stop-word removal, USPS/GM canonicalization. A small **preprocessing ablation** (no canonicalization; no stop-word removal) on a sample is cheap and answers the inevitable reviewer question: "Is the LLM gain just from better preprocessing piped into a generic clusterer?" Neither report builds this in.

### 2.6 Active learning for the next labeling round
`report_1.md` mentions OASIS once but doesn't make it concrete. Given the cost of expert labels and the near-ceiling precision in current cells, the next 250 labels should be drawn where they discriminate most — fuzzy-only at scores `[82, 90)` (the only cell with non-trivial false-positive risk) and clustering pairs with low internal consensus / large clusters / low within-cluster similarity. This is a small piece of code but a big efficiency gain.

### 2.7 Substantive-result robustness is part of the methods evidence
`report_2.md` raises this; `report_1.md` does not. For a sociology article, the most convincing single sentence is: *"All headline estimates are within X% across conservative, hybrid, and expansive linkages."* If that sentence is true, almost no reviewer will challenge the linkage methodology. Provenance flags (§ `report_2.md`) are the prerequisite.

### 2.8 Comparison-table normalization
`report_1.md` correctly notes that the three cells were sampled at very different rates and need pool-size reweighting before a single aggregate precision is computed. Neither report fully writes out the formula, but it is worth doing: weighted precision = Σ (cell_size × cell_precision) / Σ cell_size, with the trivial-agreement pool included at precision ≈ 1.

### 2.9 Pre-blocking singletons are absent from the cluster file *by design*
Both reports note this; only `report_1.md` warns that any clustering-level metric computed from the file alone will be optimistic. Worth restating because it is the single easiest mistake to make in the entity-centric benchmark.

---

## 3. Three practical next steps

These are sequenced for maximum leverage — each builds on the previous and the first two are quick wins.

### Step 1 — Pipeline-flow audit + label-free internal diagnostics (≈ 2–3 days)
Deliverable: one figure and one diagnostics report.

- **Pipeline-flow figure**: raw strings (463,344) → unique preprocessed names (334,276) → entered blocking → in cluster file (224,767 across 91,120 clusters) → pre-blocking singletons (count to be recovered from the `nlrb-blocking` folder logs). Annotated with cluster-size distribution and singleton share. Resolves `report_2.md`'s denominator concern and gives you a figure 1 for the paper.
- **Label-free diagnostics** (per `report_1.md` §4.2.2): within-cluster `token_sort_ratio` distribution (rank the low-min tail for review), singleton fuzzy-twin audit (`≥ 95` against the full file), representative-collision check, transitivity-violation count for the *fuzzy* linkset (free win for the comparison table).
- **Add zip-code sensitivity check** (§2.2 above): rerun the matching with a `state + city + zip` gate, count how many cluster-flagged pairs survive. Pairs that drop are over-merge suspects; sample 30 and label.

This step costs almost no expert time and produces three artifacts that go directly into the paper.

### Step 2 — Recall + clustering confidence in one labeling pass (≈ 1–2 weeks)
Deliverable: a P/R/F1 table with uncertainty, and a per-edge LLM confidence score.

- **Capture–recapture recall** (per `report_1.md` §3.3): on the non-trivial subset, compute Lincoln–Petersen and Chao with bootstrap CIs over the labeled precisions. Report gated recall and F1 — *not* universal recall — and explicitly state the conditioning on the state+city+date gate.
- **Consensus reruns** (per `report_1.md` §4.3): rerun the LLM clustering step K=5–10 times on a stratified sample of ~200 blocks with permuted record orderings. Build a per-edge co-clustering frequency in [0,1]. Use the same labeled evaluation pairs as anchor: report precision/recall as a function of consensus threshold (the ROC analogue of fuzzy's score sweep). This is the missing "agreement measure."
- **Active-learning round** (§2.6 above): allocate the next 100 labels to fuzzy-only `[82, 90)` and low-consensus cluster edges. These are the two cells whose precision is least pinned down.

The Step-1 diagnostics feed the sampling design here: low-min within-cluster similarity and low-consensus pairs are the same population.

### Step 3 — Entity-centric clustering benchmark on a time-slice holdout (≈ 2–3 weeks of labeling)
Deliverable: B-cubed / pairwise / cluster P-R-F1 with confidence intervals — the independent clustering validation the IC2S2 abstract needs.

- **Sample 100–200 clusters with probability proportional to size** using the `ER-Evaluation` framework (`github.com/OlivierBinette/er-evaluation`). For each sampled cluster, **fully resolve the local neighborhood** — every name in the cluster *plus* candidate "should-have-been-here" names pulled from the full file via fuzzy ≥ 90 and via embedding kNN against the cluster representative. Resolving the neighborhood (not just the cluster) is what gives you recall.
- **Time-slice holdout** (§2.4 of `report_2.md`): partition by filing system (CHIPS 1984–2001 / CATS 1999–2011 / NxGen 2011–present) or by year ranges. Tune any policy decisions (consensus thresholds, fuzzy boost cutoffs, post-blocking merge rules) on one slice; evaluate on the other(s). Report whether B-cubed F1 is stable across slices — this is the generalizability claim.
- **Pair-completeness audit of the blocker**: among hand-labeled positive pairs from this benchmark, what fraction landed in the same block at any stage? This is the upper bound on what the LLM step could have caught and is the strongest evidence about where remaining recall lives.
- **Establishment-level extension**: for clusters that contain chains (Walmart, USPS, large hospital systems), do the benchmark twice — once at the firm level, once at the firm × city level. This is the empirical answer to §2.1 above.

After Step 3 the methods section has: a precision audit (existing), a gated-recall audit (Step 2), a clustering-level audit on a holdout (Step 3), a blocker audit (Step 3), and a confidence-curve comparison (Step 2). That is roughly the upper bound of what is realistically defensible for this kind of project, and it is more than most published NLRB-data papers carry.

---

## 4. Important sources neither report cites prominently

The two reports already include the core references (Fu et al. 2025; Binette et al. 2022/2024; Menestrina et al. 2010; Sadinle 2018; Hennig 2007 cluster stability; Marchant & Rubinstein 2017 OASIS). The most consequential omissions, in priority order:

1. **Enamorado, Fifield & Imai (2019). "Using a Probabilistic Model to Assist Merging of Large-Scale Administrative Records." *American Political Science Review* 113(2): 353–371.** Fellegi–Sunter probabilistic record linkage, with the `fastLink` R package. The most-cited methods paper in political science / sociology record linkage of the last decade; reviewers in your discipline *will* expect it. Use it as a third comparison baseline (§2.3).
2. **Binette & Steorts (2022). "(Almost) All of Entity Resolution." *Science Advances* 8(12).** The single best modern overview of ER as a methodological problem. If you cite one survey, cite this one.
3. **Christen (2012). *Data Matching: Concepts and Techniques for Record Linkage, Entity Resolution, and Duplicate Detection.* Springer.** The textbook. Useful for the blocking vs. matching decomposition and the standard vocabulary.
4. **Peeters & Bizer (2023). "Using ChatGPT for Entity Matching." *arXiv:2305.03423*; and Narayan, Chami, Orr & Ré (2022). "Can Foundation Models Wrangle Your Data?" *VLDB.*** The two LLM-for-ER papers that immediately precede Fu et al. (2025). Citing them alongside establishes that LLM-CER is one design choice in a small but real literature, not a one-off.
5. **Steorts, R. C. (2015). "Entity Resolution with Empirically Motivated Priors." *Bayesian Analysis*; and Steorts, Hall & Fienberg (2016) "A Bayesian Approach to Graphical Record Linkage and De-duplication." *JASA.*** If the project ever wants to propagate linkage uncertainty into downstream sociology results (per `report_2.md`'s Bayesian post-scoring suggestion), these are the foundations.
6. **Larsen & Rubin (2001), "Iterative automated record linkage using mixture models." *JASA.*** Foundational for the probabilistic-ER baseline.
7. **For NLRB-specific silver-standard candidates**: Ferguson, J.-P. (2008) "The Eyes of the Needles: A Sequential Model of Union Organizing Drives, 1999–2004" *ILR Review*; and the Kate Bronfenbrenner studies on union election outcomes — both maintain hand-curated firm samples that could be matched to your cluster file as external validation.
8. **For the blocker layer specifically**: Papadakis et al. (2020). "Blocking and Filtering Techniques for Entity Resolution: A Survey." *ACM Computing Surveys.* Standard reference for pair-completeness and the blocker-as-component framing.

A reasonable reading order for ~one afternoon: Binette & Steorts (2022) first for the map; Enamorado/Fifield/Imai (2019) for the discipline-expected baseline; Papadakis et al. (2020) just the blocking section; Peeters & Bizer (2023) for the LLM-ER context.

---

## 5. One-paragraph bottom line

Both reports are usable and largely correct. `report_1.md` is the better methodological skeleton — adopt its two-task reframing, its capture–recapture mechanic, its consensus-confidence proposal, and its Stage 1–6 plan. Then patch in from `report_2.md`: the pipeline-as-pipeline framing, the coverage-denominator audit, the blocker-as-its-own-evaluation-target, the time-slice holdout, and provenance flags + substantive robustness across linkage definitions. Resolve `report_2.md`'s placeholder citations before any of it is reused in writing. The biggest gap in *both* documents is the establishment-vs-firm distinction, which should be made explicit in the methods section, and a probabilistic-ER baseline (`fastLink`) is the most expected omission for a sociology audience. The three steps above — diagnostics, recall + confidence, entity-centric benchmark on a holdout — are the minimum sufficient set to support both the R↔C matching claim and the firm-aggregation claim from the IC2S2 abstract.
