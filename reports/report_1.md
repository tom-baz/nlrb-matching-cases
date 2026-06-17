# Evaluating Fuzzy Matching vs. LLM Clustering for NLRB Entity Resolution
### A methodological strategy for the comparison and for validating the clustering itself

---

## 0. Executive summary

Your project actually contains **two distinct tasks that need two distinct evaluations**, and most of the difficulty you describe comes from treating them as one:

1. **The matching task** — linking R Cases to C Cases (a *bipartite record-linkage* problem). This is what `match_r_to_c_cases.py` and your evaluation sample measure.
2. **The clustering task** — resolving all ~334k company-name strings into firm-level entities (a *clustering / deduplication* problem). This is the thing the IC2S2 abstract actually promises ("enabling firm-level aggregation").

The R↔C matching task is a *downstream application* of the clustering and only a **partial, biased proxy** for clustering quality: it exercises only the clusters that happen to contain both an R-side and a C-side name in the same city and time window. So "the matching looks good" is necessary but not sufficient evidence that "the clustering is good enough to aggregate firms."

Headline recommendations:

- **For the comparison (Q1):** stop framing it as "fuzzy vs. clustering, pick a winner." Your own failure analysis already shows the two are *structurally complementary*. The defensible scientific claims are (a) clustering recovers semantic matches that fuzzy *cannot* get (the cluster-only cell, 100% precision, is your strongest result), and (b) a **hybrid** (clustering + high-confidence fuzzy) dominates either method alone. Add a **recall estimate** via capture–recapture so you can report F1, not just precision, and report the **cost/scalability/generalizability** axis that the abstract actually rests on.
- **For validating the clustering (Q2):** prefer the *independent* route (your option 2.ii). Use an **entity-centric benchmark**: sample whole clusters with probability proportional to size, fully resolve them by hand, and estimate **B-cubed / pairwise / cluster precision *and* recall with confidence intervals**. This is a mature, published methodology with a ready-made Python package and a near-identical precedent (PatentsView inventor-name disambiguation).
- **For the missing "agreement measure":** generate a clustering confidence score the way the unsupervised-clustering literature does — **consensus/stability**. Re-run the LLM clustering several times with permuted record-set orderings/seeds and record, for each pair, the fraction of runs in which the two names land in the same cluster. That co-clustering frequency is a per-edge confidence in [0,1], directly analogous to the fuzzy score, and it is well-motivated because Fu et al. show that record ordering materially affects in-context clustering.

The rest of this document develops each of these.

---

## 1. Reframing: two tasks, two evaluations

### 1.1 The matching task
A bipartite linkage: each RC petition may link to zero or more CA charges filed at the same establishment during the petition's open window. Your pipeline gates every candidate on **same state + fuzzy-same city + C filed within the R window**, then decides name equivalence either by fuzzy `token_sort_ratio ≥ 82` or by "same cluster representative." The natural metrics are **pairwise precision and recall** over candidate (R,C) pairs.

### 1.2 The clustering task
A deduplication/clustering of the full 334,276-name space into firm entities. The natural metrics are **cluster-comparison metrics**: pairwise P/R/F1, B-cubed P/R/F1, and the metrics the source paper uses — FP-measure, accuracy, and Normalized Mutual Information (NMI).

### 1.3 Why matching-task success ≠ clustering success
The matching task only ever "looks at" a cluster when that cluster simultaneously contains:
- at least one R-side name **and** at least one C-side name,
- in the **same city/state**, and
- with **overlapping dates**.

Consequences:
- A cluster that wrongly merges two genuinely different firms ("Hilton" downtown vs. "Hilton" airport, or two unrelated "ABC Mechanical") can still produce *correct-looking* R↔C links if the gating happens to separate them — so the matching task **under-detects over-merging** (precision failures of the clustering).
- A cluster that wrongly splits one firm into two (the failure modes A/B/C in your `clustering_failure_analysis.md`) only shows up in the matching task if the split happens to break a cross-source, same-city, same-window pair — so the matching task also **under-detects under-merging** (recall failures of the clustering).
- The vast majority of clusters (single-source, or cross-city, or no temporal overlap) are **never tested at all** by the matching task.

So: the matching evaluation is a real and useful end-to-end test of *one application*, but it is a biased keyhole onto the clustering. For the abstract's firm-level-aggregation claim you need a clustering-level evaluation too (Section 4).

---

## 2. What your current evaluation already establishes — and its limits

**Establishes (well):**
- A clean, *blinded*, stratified precision audit. Blinding is exactly right and is the part reviewers will trust most.
- Cluster-only precision **100% (n=99; Wilson CI ~[96%,100%])** and fuzzy-only ≥90 precision **100% (n=48)** — strong evidence of the complementarity thesis.
- A careful, honest failure taxonomy (modes A/B/C) that already reads like a paper subsection.

**Limits to close:**
1. **Precision only.** You explicitly note recall is hard. Section 3.3 gives a tractable estimate.
2. **The "agreement" cell is filtered to non-identical preprocessed names** (good — avoids trivial inflation), but that means your three cells are *not* a partition you can naively recombine into an overall precision without re-weighting by the true cell sizes (9,688 / 1,046 / 11,305 … and the trivial agreement pool of 39,738). Report **pool-size-weighted** precision so the aggregate reflects the real population.
3. **Small denominators per stratum** (n≈50) → ±5–10 pt margins; fine for "near-ceiling," too coarse to rank two near-100% methods. If a ranking claim matters, raise n in the relevant cell.
4. **No measure of clustering precision** at the entity level (over-merging), because the matching task hides it (Section 1.3).

---

## 3. Question 1 — A defensible comparison strategy for the article

### 3.1 Frame it as complementarity → hybrid, not as a winner-take-all
Your data already refute the "one is simply better" framing. The honest and stronger claim:

> Fuzzy string similarity and LLM clustering fail on *structurally different* populations — fuzzy misses semantic equivalences with low character overlap (USPS ↔ United States Postal Service), clustering misses character-level typos in short, neighbor-less names. Neither dominates; a hybrid that uses clustering as the primary linker and high-confidence fuzzy (`token_sort_ratio ≥ 90`) as an additive recall layer dominates either alone.

This is both what reviewers will find credible *and* what your numbers support. The cluster-only cell is the centerpiece: it isolates the matches that **only** the semantic method can find.

### 3.2 Adopt the standard ER metric vocabulary so the work is placeable
Report the comparison in metrics the ER community recognizes, computed on the **labeled pairs** (and the recall estimate from 3.3):

- **Pairwise precision / recall / F1** — the lingua franca of record linkage.
- **B-cubed precision / recall / F1** — record-centric; specifically catches over-merging and splitting that pairwise metrics can mask. (B-cubed precision = for each record, the share of its cluster-mates that truly belong; B-cubed recall = the share of its true siblings that were captured.)
- For the **clustering-level** results (Section 4), also report **FP-measure, accuracy, and NMI** — the exact metrics in Fu et al. (2025). Matching their metrics lets a reader compare your NLRB application directly against the method's benchmark numbers.

Why both pairwise and B-cubed: they can *rank methods differently*, and reviewers in this area know it (Maidasani/Menestrina; the GMD paper). Reporting both pre-empts the "you picked the metric that flatters you" critique.

### 3.3 Estimate recall with capture–recapture (dual-system estimation)
You cannot enumerate all true matches, but you have **two imperfect detectors of the same truth** — and that is exactly the setup of capture–recapture (a.k.a. dual-system / multiple-systems estimation), the standard tool in census coverage and human-rights casualty estimation, and increasingly in record linkage.

**The idea.** Within the shared candidate population (pairs passing the same state+city+date gate), let:
- `a` = true matches found by **both** methods,
- `b` = true matches found by **fuzzy only**,
- `c` = true matches found by **clustering only**.

If the two methods detected matches *independently*, the Lincoln–Petersen estimator of the total true matches is

```
N_hat = (n_fuzzy * n_cluster) / a
```

where `n_fuzzy = a + b`, `n_cluster = a + c`. Then estimated recall is `n_fuzzy / N_hat` for fuzzy, `n_cluster / N_hat` for clustering, and `(a+b+c)/N_hat` for the union. The number you can't see directly — true matches **both** methods missed — is `N_hat − (a+b+c)`.

**Crucial correction — use the *labeled* match counts, not raw cell sizes.** Your cells contain false positives. Plug in precision-corrected counts: e.g. fuzzy-only true matches ≈ `1,046 × 0.959`, cluster-only ≈ `11,305 × 1.00`, agreement (non-trivial) ≈ `9,688 × 1.00`, **plus** the trivial identical-name agreement pool (39,738), which are essentially all true and found by both. Propagate the precision CIs through to `N_hat` (a small bootstrap over the labeled sample does this cleanly).

**The assumption that will get challenged, and how to handle it.** Lincoln–Petersen assumes the two captures are independent and homogeneous. Two threats:
- **Positive dependence from shared easy cases.** Identical-/near-identical-name matches are caught by *both* methods with probability ≈1. This heterogeneity (some matches are "easy," some "hard") makes the overlap `a` too large, which makes `N_hat` too small and **over-states recall**. *Mitigation:* run the estimator on the **non-trivial subset** (preprocessed names differ) — which is where the recall question is interesting anyway — and report it separately from the trivial pool. Also report a heterogeneity-robust estimator (Chao's lower-bound estimator, or a log-linear model with an interaction term) alongside Lincoln–Petersen; the gap between them bounds the dependence bias.
- **The shared gate.** Both methods sit behind the same state/city/date filter, so this procedure estimates **recall *conditional on* passing that gate**, not recall against the universe of all conceivable R↔C links. State this explicitly — it is still the policy-relevant quantity (you only ever act on gated candidates), and it is honest.

**Why your setting is unusually favorable for this.** Capture–recapture is most trustworthy when the two lists are independent. Your failure analysis shows the two methods miss *different* structural populations (semantic vs. character-level) — i.e. their errors are closer to independent (even mildly negatively correlated) than two variants of the same method would be. That is a genuine methodological selling point: you can argue the independence assumption is *approximately* satisfied *because* the methods are complementary.

### 3.4 Report the non-accuracy axes — that is where clustering actually wins
The abstract's real argument is not "clustering is more precise"; it is "clustering **generalizes**" to firm-level aggregation that fuzzy all-pairs matching cannot scale to. Make that explicit and quantify it:

- **Scalability / cost.** Fuzzy all-pairs is O(n²) across 334k names (intractable without blocking); LLM-CER's blocking + in-context clustering reduces LLM calls by up to ~5× vs. pairwise LLM baselines (Fu et al.). Report wall-clock, API cost, and number of comparisons for each method at full scale.
- **Generalizability.** Clustering yields a *reusable firm key* usable for R↔R, C↔C, and firm-level panels; fuzzy as deployed only answers the specific bipartite R↔C question and would need re-running per task.
- **Transitivity / internal consistency.** Clustering output is transitive by construction (if A≡B and B≡C then A≡C). Threshold fuzzy matching is **not** transitive and can produce inconsistent linksets — a real, citable disadvantage for firm aggregation.

### 3.5 Concrete deliverable for the paper
A single comparison table with rows = {Fuzzy only, Cluster only, Union, **Hybrid (cluster + fuzzy≥90)**} and columns = {pairwise P, pairwise R (capture–recapture), pairwise F1, B-cubed P/R/F1, est. cost, transitive? (Y/N)}. The hybrid row carrying the best F1 *is* your justification.

---

## 4. Question 2 — Validating the clustering itself

### 4.1 Option 2.i — generalize the matching task into clustering validation
Useful as a cheap extension, but inherently a **biased proxy** (Section 1.3). If you do pursue it, the two highest-value extensions are:

- **Drop the city/date gate and test pure name equivalence.** Sample cross-source pairs that clustering links but that differ in city or fall outside any window, and label whether the *names* refer to the same firm. This isolates the entity-resolution decision from the temporal/geographic logic and starts to probe **over-merging** (precision of the clustering proper).
- **Add within-source pairs (R↔R, C↔C).** The matching task only tests cross-source links. Sampling same-source pairs that the clustering merges tests whether the firm key behaves for the *aggregation* use case the abstract is really about.

Even extended, this remains conditioned on "clusters that contain matchable pairs." Treat it as corroborating, not primary, evidence.

### 4.2 Option 2.ii — independent clustering evaluation (recommended)

#### 4.2.1 Entity-centric benchmark with uncertainty (the main recommendation)
This is the mature, published answer to "how do I get precision *and* recall for a clustering when there are hundreds of thousands of names and I can't sample non-matches." The key move (Binette et al.; the ER-Evaluation framework and Python package; applied at scale to PatentsView inventor disambiguation — essentially your problem) is to **sample whole entities, not pairs**:

1. **Draw a probability sample of predicted clusters**, sampled with probability **proportional to cluster size** (this is the statistically efficient design and the package handles the weighting).
2. **Fully resolve each sampled cluster by hand** — for each name in the cluster, determine the true firm it belongs to, including names that *should* have been in the cluster but were split out (this is what gives you **recall**, not just precision). Your existing blinded-labeling workflow extends naturally to this.
3. **Estimate B-cubed / pairwise / cluster precision, recall, and F1 with confidence intervals** from the sample, using the package's estimators. Because you sampled by a known design, these are **unbiased estimates of the whole-dataset performance**, with quantified uncertainty — not just descriptive stats on the sample.

This sidesteps the needle-in-a-haystack problem precisely because it never samples the enormous non-match space; it samples *clusters* and reconstructs ground truth locally. It is the single most defensible thing you can add for the firm-aggregation claim, and "we follow Binette et al.'s entity-centric estimation framework" is a clean methods sentence.

The same framework gives **root-cause error analysis** (which cluster features predict errors), which dovetails with your failure modes A/B/C and turns them into quantified shares of total error rather than illustrative anecdotes.

#### 4.2.2 Label-free internal diagnostics (cheap, run on the full file)
Run these over the entire `cluster_assignments_20260517.csv` as automated sanity checks — they need no labels and surface suspicious clusters for targeted review:

- **Transitivity audit.** Free for clustering (it's transitive by construction) — but compute the analogous statistic for the *fuzzy* linkset and report how often fuzzy violates transitivity. A concrete number here strengthens 3.4.
- **Within-cluster string-similarity distribution.** For each multi-record cluster, compute pairwise `token_sort_ratio` among members. Clusters with low *minimum* internal similarity are over-merge suspects (the LLM linked names with little surface overlap — sometimes a great semantic catch, sometimes an error). Rank by this and hand-review the tail. This is also where clustering and fuzzy *should* disagree most, so it doubles as a sampling frame for 4.1.
- **Singleton audit.** 38,892 of your clusters are singletons. Sample singletons and check (via fuzzy `≥95` against the rest of the file) whether each has an obvious twin that was wrongly left unmerged — this directly estimates the **recall leak** from failure modes B/C, independent of the matching task.
- **Representative-collision check.** Because cluster matching substitutes a *shortest-name* representative, two different firms whose representatives happen to coincide after preprocessing will be silently merged downstream. Flag any representative shared across clusters with very different member sets.

### 4.3 Giving the clustering a confidence score (your missing "agreement measure")
Fuzzy hands you a `token_sort_ratio`; the LLM clustering hands you a hard 0/1. You can manufacture a graded confidence using the standard unsupervised-clustering device of **consensus / stability**:

- **Permutation/consensus re-runs.** Re-run the clustering K times (e.g. K=10) varying only the record-set ordering and/or the k-means seed in the NRS step. For every pair of names that are ever co-clustered, record the **fraction of runs in which they co-cluster** (the entry of the *consensus matrix*). That fraction ∈ [0,1] is a per-edge confidence: 1.0 = the LLM groups them regardless of context; 0.3 = fragile, context-dependent. This is *especially* well-motivated here because Fu et al. demonstrate that set size, diversity, and **ordering** change in-context clustering output — so the variability you'd be measuring is real and decision-relevant, not noise to hide.
  - Cost control: you only need to re-run the NRS/CMR stages on a *sample of blocks*, not the whole corpus, to characterize the confidence distribution and to attach confidence to your evaluation-sample pairs.
- **Cluster-level stability.** Summarize each cluster by its mean internal consensus (Hennig's cluster-wise Jaccard stability is the standard statistic) to flag fragile clusters for review.
- **LLM-native signals.** Have the clustering prompt also emit a brief rationale or a self-reported confidence per merge, and/or use the kNN-verification margin from the CMR step as a continuous score. (Self-reported LLM confidence is weaker than consensus — report it as secondary.)

The payoff: with a consensus score you can draw an ROC/precision–coverage curve for clustering just like a fuzzy-threshold sweep, making the two methods **directly comparable on the same axes**, and you can define a high-confidence clustering tier analogous to "fuzzy ≥ 90."

### 4.4 External / silver-standard validation (if available)
If any external firm registry with establishment-level identifiers can be matched to even a slice of the NLRB data (e.g., a state employer registration, a union/employer directory, SEC/EIN-linked sources for large firms, or the hand-matched samples from prior NLRB studies such as Ferguson 2008), use it as a **silver standard**: project the clustering onto that slice and report agreement. Even partial external coverage (large firms only) is a powerful triangulation that neither the matching task nor internal diagnostics provides. Worth a scoping check before committing.

---

## 5. A staged plan (what to do, in order)

| Stage | Action | What it buys you | Cost |
|---|---|---|---|
| 1 | Re-weight existing precision by true pool sizes; add B-cubed + pairwise to the labeled sample | Reviewer-legible metrics, honest aggregate precision | hours |
| 2 | Capture–recapture recall (Lincoln–Petersen + Chao), non-trivial subset, bootstrap CIs | Recall & F1 without sampling non-matches | hours |
| 3 | Label-free internal diagnostics over the full cluster file (transitivity, within-cluster similarity, singleton + representative audits) | Cheap over-/under-merge detection on the *whole* clustering | 1–2 days |
| 4 | Entity-centric benchmark: sample ~100–200 clusters ∝ size, fully resolve, estimate B-cubed/pairwise/cluster P-R-F1 with CIs (ER-Evaluation framework) | The defensible firm-level clustering validation the abstract needs | 1–2 weeks labeling |
| 5 | Consensus re-runs on sampled blocks → per-edge confidence; redo comparison on shared confidence/threshold axes | The missing agreement measure; apples-to-apples method comparison | compute + days |
| 6 | (If feasible) external silver-standard cross-check | Independent triangulation | scoping-dependent |

Stages 1–3 are quick wins that materially upgrade the current draft. Stage 4 is the one new substantial labeling effort and is the highest-value addition for the clustering claim. Stage 5 resolves your stated "no agreement measure" limitation.

---

## 6. Pitfalls specific to your setup

- **Don't recombine the three cells into one precision without re-weighting** by true cell/pool sizes — the cells were sampled at very different rates.
- **Capture–recapture estimates gated recall**, not universal recall; say so, and run it on the non-trivial subset to limit heterogeneity bias.
- **Cluster representative = shortest name** is a silent failure surface: short generic names ("ABC Inc.") make poor representatives and can cause representative collisions. Audit it (4.2.2), and consider a more robust representative (e.g., most-frequent name, or longest non-abbreviated form).
- **Pre-blocking singletons are absent from the cluster file by design**, so any clustering recall metric computed only over the file will be optimistic — your benchmark (Stage 4) and singleton audit (Stage 3) must explicitly include names that never reached blocking, or you'll miss failure mode C entirely.
- **Date/version hygiene:** every metric is tied to `cluster_assignments_20260517.csv`. If clusters are regenerated, all of Stages 1–5 must be recomputed; keep the date suffix discipline you already use.
- **Blinding:** keep the entity-centric labeling (Stage 4) blinded to method just as your pair labeling is.

---

## References

- Fu, J., Tang, H., Khan, A., Mehrotra, S., Ke, X., & Gao, Y. (2025). *In-context Clustering-based Entity Resolution with Large Language Models: A Design Space Exploration.* Proc. ACM Manag. Data / SIGMOD '26. arXiv:2506.02509. — your source method; uses FP-measure, accuracy, NMI; documents ordering/set-size effects (basis for the consensus-confidence idea).
- Binette, O., et al. (2024). *How to Evaluate Entity Resolution Systems: An Entity-Centric Framework with Application to Inventor Name Disambiguation.* arXiv:2404.05622. — sample-clusters-not-pairs benchmark; B-cubed/pairwise/cluster metrics as weighted cluster-wise aggregates.
- Binette, O., et al. (2022). *Estimating the Performance of Entity Resolution Algorithms.* arXiv:2210.01230 (PatentsView). — cluster/block sampling estimators for precision *and* recall on huge name datasets; the closest published analog to your task.
- ER-Evaluation Python package — github.com/OlivierBinette/er-evaluation; docs at er-evaluation.readthedocs.io. — ready implementation of the above with uncertainty quantification and error analysis.
- Menestrina, D., Whang, S. E., & Garcia-Molina, H. (2010). *Evaluating Entity Resolution Results.* PVLDB. — pairwise F1, cluster F1, Generalized Merge Distance; shows ER metrics can rank methods differently (motivates reporting both pairwise and B-cubed).
- Maidasani / "A Practitioner's Guide to Evaluating Entity Resolution Results." arXiv:1509.04238. — accessible definitions of pairwise vs. B-cubed precision/recall and the large-database inter-cluster-pair caveat.
- Sadinle, M. (2018). *Bayesian Propagation of Record Linkage Uncertainty into Population Size Estimation.* arXiv:1812.09590; and the multiple-systems-estimation / capture–recapture literature (Lincoln–Petersen; Chao's estimator; log-linear MSE). — recall via two independent detectors; handling list dependence.
- Marchant, N., & Rubinstein, B. (2017). *In Search of an Entity Resolution OASIS: Optimal Asymptotic Sequential Importance Sampling.* arXiv:1703.00617. — biased/active sampling that yields consistent precision, recall, and F1 estimates with up to ~75% fewer labels (an efficient alternative to uniform labeling if you scale up).
- Cluster stability / consensus clustering: Monti et al. (Consensus Clustering); Hennig (2007, cluster-wise stability); Liu et al. (2022, WIREs review). — basis for the permutation-based per-edge confidence score.
- Amigó, E., Gonzalo, J., Artiles, J., & Verdejo, F. (2009). — formal properties of B-cubed for name-disambiguation evaluation.
