# Phase 8 - Cross-validation, bias/variance, rigorous evaluation

Status: done   Date: 2026-11-21
Gate G4 (beats all baselines with CI excluding the baseline; shuffle test fails as it should): **NOT MET.**
Rules were written before any result: [phase-08-decision-rule.md](phase-08-decision-rule.md) (with dated notes).

## 1. What we did
- Wrote `evaluate.py` (inclusive evaluation, percentile scoring, block bootstrap, paired differences), `experiments.py` (spatial-CV runner with switches, leave-one-district-out, nested tuning) and `phase8.py` (stage functions, G4 summary); 6 new tests (44 pass).
- Eight pipeline stages, total about 40 minutes: inclusive evaluation, leave-one-district-out, shuffle test, training without producers, learning curve, feature-group ablation, nested tuning, random-position null, G4 summary.
- Results in `reports/phase8_*.csv` and `phase8_g4.json`.

## 2. Headline results (inclusive evaluation: the 2 km ring counts as unlabeled)
Pooled over 3 repeats; 95 % block-bootstrap interval in brackets (resampling 15 km blocks; still optimistic).

| Model | ROC-AUC, all 199 | Recall in top 5 % of cells, all | ROC-AUC, 101 non-producers | Recall top 5 %, non-producers |
|---|---|---|---|---|
| prevalence | 0.50 | 0.05 (chance) | 0.50 | 0.05 |
| geology rule | 0.71 [0.55, 0.79] | 0.17 [0.08, 0.26] | 0.68 | 0.16 |
| uranium count alone | 0.83 [0.70, 0.90] | 0.53 [0.28, 0.67] | 0.78 [0.68, 0.84] | 0.43 [0.25, 0.56] |
| **logreg** | 0.86 [0.72, 0.92] | 0.61 [0.33, 0.76] | 0.80 [0.68, 0.87] | 0.43 [0.23, 0.60] |
| rf | 0.87 [0.75, 0.92] | 0.60 [0.29, 0.75] | 0.82 [0.72, 0.88] | 0.41 [0.22, 0.55] |
| et | 0.87 [0.72, 0.93] | 0.62 [0.32, 0.76] | 0.81 [0.68, 0.89] | 0.46 [0.24, 0.62] |
| hgb | 0.85 [0.71, 0.90] | 0.51 [0.25, 0.62] | 0.79 | 0.35 |

- Plain reading: by examining the best-scored 5 % of the area, the logistic model finds about 6 in 10 known occurrences (4 in 10 for non-producers), against about 5 in 100 by chance.
- Inclusive PR-AUC is 0.003-0.005 per fold, about 50-80 times the prevalence (0.00006). Phase 7's 0.2-0.3 was the exclusion artefact.
- Mean lift in the top 5 %: 11.6-12.0 (logreg, rf, et), 10.3 for uranium alone.

## 3. Gate G4, criterion by criterion
| Criterion | Result |
|---|---|
| Beats prevalence and geology rule, CI excludes 0 (ROC-AUC and recall@5 %) | **Yes**, all models, both positive sets. Versus the rule: +0.16 ROC-AUC, +0.43 recall |
| Beats single-uranium baseline, CI excludes 0 | **No.** logreg +0.034 ROC [-0.026, 0.088], +0.075 recall [-0.014, 0.137]; rf +0.045 [-0.002, 0.098]; et +0.040 [-0.026, 0.101]. For non-producers recall@5 % the difference is 0.00 (logreg), -0.02 (rf), +0.03 (et) |
| Shuffle test within 0.45-0.55 | **No**: 0.31 (logreg), 0.31 (rf), 0.21 (et); see red flag 2 |
| LODO beats uranium alone in at least half of the districts | logreg yes (2 of 3), rf and et no (1 of 3) |
Verdict: **G4 not met.** Per the rule written beforehand, we state that the model adds modest value over "look where uranium counts are high", and make no claim of geological understanding.

## 4. Other experiments
**Leave-one-district-out** (districts = positives linked within 12 km; held out with a 12 km surround; only 3 districts have at least 10 positives):
| District (positives, of which producers) | uranium alone ROC / recall@5 % | logreg | rf | et |
|---|---|---|---|---|
| 1 (13, 1) | 0.77 / 0.15 | 0.55 / 0.08 | 0.56 / 0.08 | 0.47 / 0.08 |
| 7 (90, 49) | 0.79 / 0.58 | 0.88 / 0.70 | 0.85 / 0.64 | 0.84 / 0.59 |
| 8 (77, 45) | 0.87 / 0.52 | 0.88 / 0.61 | 0.88 / 0.44 | 0.87 / 0.52 |
The two big districts transfer to each other well (the rock and signal are alike); the small third one does not (learned models are near chance, uranium alone is far better).

**Choosing among finalists** (rule: mean of block-CV and LODO recall@5 %): logreg 0.54, et 0.51, rf 0.49. **Logistic regression** is chosen (also simplest).

**Training without producers** (half the training positives removed, evaluated on non-producers): ROC-AUC logreg 0.833 -> 0.842, rf 0.846 -> 0.834, et 0.839 -> 0.831. All changes under the 0.02 threshold: no material mine effect by the rule. But recall@5 % for rf and et falls by about 0.05, so training data matters more than mine contamination.

**Feature groups** (repeat 0, logreg / rf; recall@5 % all positives):
| Configuration | logreg | rf |
|---|---|---|
| full (49 features) | 0.585 | 0.587 |
| drop neighbourhood | 0.524 | 0.547 |
| drop radiometric | 0.586 | 0.586 |
| drop geology / terrain / magnetic | 0.623 / 0.607 / 0.607 | 0.587 / 0.586 / 0.583 |
| drop structure | 0.585 | 0.556 |
| only neighbourhood (11) | 0.596 | 0.523 |
| only radiometric (11) | 0.537 | 0.433 |
| only geology / terrain / magnetic / structure | 0.075 / 0.054 / 0.187 / 0.066 | 0.072 / 0.031 / 0.168 / 0.060 |
By the rule, only the neighbourhood group is "needed" (dropping it costs 0.04-0.06) and it is nearly "sufficient" alone. Geology, terrain and magnetics add nothing (dropping geology even raises logreg recall by 0.04).

**Learning curve** (25 / 50 / 75 / 100 % of training data): logreg ROC-AUC 0.846 / 0.840 / 0.841 / 0.853, recall flat about 0.59; rf 0.842 / 0.851 / 0.859 / 0.873, recall noisy 0.55-0.59. Train AUC: logreg 0.96 -> 0.93, rf 1.00 always. Logreg is flat (limited by signal, not data amount); rf still creeps up with more data (variance) and memorises (train 1.00 vs test 0.87).

**Nested tuning:** logreg best by inner CV was the strongest regularisation or the default (inner recall 0.585 vs 0.586); tuned vs default outer recall 0.602 vs 0.585 (+0.016) and ROC +0.005, below the +0.02 rule, so default kept. rf tuned = default (0.602, 0.873). Hyper-parameters are not what limits performance.

## 5. Challenges
| Challenge | How we solved it |
|---|---|
| Phase 7 PR-AUC was inflated 50x by excluding the ring | Inclusive evaluation as the headline |
| Cross-fold scores are not comparable | Per-positive percentile within each fold, pooled and bootstrapped by block |
| Shuffle test result outside the rule's range | Stopped, investigated, added a null test; deviation recorded openly (see 6.2) |
| Run time | Resumable stages, forests use 100 trees in ablation, learning curve, inner tuning |

## 6. Known limitations / red flags
### 🚩 Red flags
1. **G4 is not met.** The learned models do not beat the uranium count alone with confidence. For non-producers (the stricter set) recall@5 % is identical to uranium alone (0.43). The honest product statement is: "ranks areas by local radiometric uranium context; adds about +0.03-0.05 ROC-AUC over the raw uranium count, not statistically separable".
2. **The pre-registered shuffle test failed, in the below-0.5 direction.** Scores 0.21-0.31 cannot come from leakage, which pushes scores up. My hypothesis (not directly proven): true positives sit in the sparse high-uranium tail where a model fitted to noise often outputs exactly 0, which ranks them below typical cells. Supporting evidence: the random-position null (same pipeline, positives planted at random typical cells) gives 0.48 (logreg), 0.51 (rf), 0.51 (et), so the pipeline itself does not inflate scores. The replacement was chosen after the failure, which is post hoc; a stricter reviewer may still call this criterion unmet, and it is unmet as written.
3. **The signal is local radiometrics, not the geology we engineered.** Only the neighbourhood group matters; geology, terrain, magnetics and structure add nothing to the model, even though positives sit on clastic sedimentary rock and closer to faults. Those facts are real but are already captured by the radiometric context, or too coarse to help.
4. **Transfer between districts is uneven.** Good between the two big districts (both hold 167 of 199 positives and are likely geologically alike), near chance for the small third. We have no evidence about a different geology or survey.
5. **Intervals are wide (about +/-0.1 ROC-AUC, +/-0.2 recall) and still optimistic** because 199 positives are clustered in 2 districts; model differences are within noise.
6. **Mine records are not the explanation by the pre-set rule** (changes below 0.02) but the test halves the training positives, so the check is weak. Non-producer results remain the ones to quote.
7. **Random forest and extra trees memorise** (train AUC 1.00). Logreg is preferred partly for this reason.
8. **Not done here (moved):** Brier score, calibration (Phase 9). Precision/F-score at thresholds omitted deliberately: unlabeled cells are not true negatives so precision is a lower bound and the threshold is arbitrary; lift and recall are reported instead.
9. **Minor:** the prevalence baseline's recall@5 % shows 0.00 in the bootstrap table because ties score as the 50th percentile; chance is 0.05, so differences against it are overstated by about 0.05. Ablation, learning curve, tuning, shuffle and null use repeat 0 only.

## 7. Concepts learned
- **Baseline hierarchy:** a model is only as good as its margin over the simplest sensible rule (here the raw uranium count).
- **Inclusive evaluation:** removing look-alike cells from the negatives flatters precision-type metrics.
- **Block bootstrap:** treat a whole spatial cluster as one unit when resampling.
- **Nested CV:** tune inside the training blocks only.
- **A null/negative control** tests the pipeline, not the model; a failed control needs investigation, not a quiet redefinition.
- **Learning curves:** flat curve = signal-limited; rising curve = data-limited (variance).

## 8. How to reproduce
```powershell
.\.venv\Scripts\python.exe scripts\run_pipeline.py
```
