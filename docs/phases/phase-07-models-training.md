# Phase 7 - Approach, baselines and model training

Status: done (metrics are provisional; Phase 8 re-evaluates)   Date: 2026-11-21
Gate: every candidate trained under spatial CV with no test-fold leakage (PASS); every model beats the baselines it should (PARTIAL, see 6).

## 1. What we did
- Installed scikit-learn; wrote `metrics.py` (ROC-AUC, PR-AUC, recall and lift at top p%), `models.py` (seven candidates behind one interface) and `train.py` (buffered spatial block CV, resumable); stage `07_train`; 7 new tests (38 in total).
- Trained 7 models x 3 repeats x 5 folds = 105 fits. Run time 11 minutes on 8 threads.
- Saved a full out-of-fold score map per model and repeat (`models/oof/<hash>/<model>_r<k>.npy`) and the per-fold metrics (`reports/phase7_model_runs.csv`, `phase7_model_summary.csv`).

## 2. What it does
For each fold, trains on the other blocks (minus everything within 2 km of a test positive), scores every cell of the held-out blocks, and measures how well test positives are ranked against test unlabeled cells.

## 3. Why it was necessary
Models are only trustworthy relative to simpler ones. The ladder prevalence -> rule -> single feature -> linear -> trees shows how much each added complexity buys.

## 4. Concepts learned
- **Baselines first:** a model is only "good" compared with something simple. Here "look where uranium counts are high" already gets ROC-AUC 0.83.
- **Class imbalance (1 positive per ~17,000 cells):** class weights, and a fixed 40,000-cell background sample so training is fast and models see the same data.
- **Bias-variance in numbers:** random forest training AUC 1.00 vs test 0.88 = high variance (memorises); logistic regression 0.93 vs 0.87 is the gentler gap.
- **Bagging (RF, ET)** averages many deep trees to cut variance; **boosting (HGB)** adds shallow trees one after another to cut bias. With 200 positives, simple regularised models tend to win.
- **Buffered CV:** removing training cells close to test positives stops the model from being tested on near-copies of what it saw.

## 5. Challenges faced and how we solved them
| Challenge | Impact | How we solved it |
|---|---|---|
| Test used the same random seed for labels and metric tie-breaks | false alarm in a unit test | tie-break seed made explicit in the test |
| Fold 0 logistic regression PR-AUC 0.85 looked too good | possible artefact | investigated (below): not a bug, an evaluation choice that flatters PR-AUC |
| 11-minute run | long wait, crash risk | one resumable file per model and repeat, atomic writes, run in background |

## 6. Results (mean over 15 fold-runs; spread = std across folds and repeats, large)
| Model | ROC-AUC | PR-AUC* | Recall at top 1% | Recall at top 5% | Lift top 5% | Train AUC |
|---|---|---|---|---|---|---|
| prevalence | 0.50 | 0.00006 | 0.01 | 0.04 | 0.7 | 0.50 |
| rule_geology | 0.71 | 0.0002 | 0.05 | 0.19 | 3.8 | 0.71 |
| single_rad_U | 0.83 | 0.156 | 0.38 | 0.58 | 11.6 | 0.84 |
| logreg | 0.87 | 0.304 | 0.52 | 0.64 | 12.9 | 0.93 |
| **rf** | **0.88** | 0.234 | 0.51 | 0.63 | 12.5 | 1.00 |
| et | 0.87 | 0.246 | 0.52 | 0.64 | 12.8 | 0.995 |
| hgb | 0.86 | 0.253 | 0.41 | 0.56 | 11.2 | 0.98 |

*PR-AUC excludes the 2 km buffer cells from the unlabeled set; see red flag 1.
ROC-AUC std across folds is about 0.10 for every learned model. Per fold (repeat 0): ROC-AUC 0.99 and 0.97-0.99 in the two district folds, 0.74-0.87 in folds 2-4 (RF 0.99, 0.97, 0.86, 0.84, 0.80).

Reading it honestly:
- All learned models beat the baselines clearly, but **logreg, rf and et are statistically indistinguishable**: differences of 0.01 are a tenth of the fold-to-fold spread.
- **Single-feature U gets most of the way (0.83)**. The full model adds about 0.04-0.05 ROC-AUC and about 0.06 recall at top 5%.
- The geology rule is weak (0.71). It also is not independent of the labels (rule chosen after Phase 4).
- Producer positives are easier than non-producers: RF ROC-AUC 0.93 vs 0.87; logreg 0.91 vs 0.85; U alone 0.87 vs 0.82. Non-producers alone still beat chance clearly.

## 7. Decisions and trade-offs
See `docs/decisions.md`. Finalists for Phase 8: logreg, rf, et. HGB is dropped for now. No hyper-parameter tuning yet.

## 8. Known limitations / open items
### 🚩 Red flags
1. **The PR-AUC in this phase is inflated by about 50 times.** Evaluation here removes the 2 km ring around positives from the unlabeled cells. That ring holds the cells most like positives (the halo around a mine), so removing it removes exactly the hardest false alarms. Scoring the same out-of-fold maps with the ring included: PR-AUC logreg 0.317 -> 0.005, rf 0.228 -> 0.003, et 0.249 -> 0.005, U alone 0.154 -> 0.004; recall at top 1 % falls from 0.53 to 0.43 (logreg) and 0.53 to 0.37 (rf). Still 50-80 times better than chance (prevalence 0.00006), but not "30 % precision". **Phase 8 reports the inclusive numbers as the headline** and shows both.
2. **ROC-AUC 0.87 averages two very different situations.** In the two district folds it is 0.97-0.99 (the model recognises the district), in the other three folds 0.74-0.87. Do not quote 0.88 without the spread, and treat the lowest folds as the honest estimate of finding a new district.
3. **Mine records are easier to find.** Non-producers score 0.05-0.07 lower ROC-AUC in every model (repeat 0). 98 of 199 positives are producers, so the headline is partly "can the model find mines". Phase 8 headline should be the non-producer number, or a model trained without producers.
4. **Random forest memorises** (train AUC 1.00). Heavier regularisation or smaller trees may help; tuning is for Phase 8 in nested CV, not here.
5. **Models barely beat the single uranium feature.** Combined with Phase 6 flag 1 and 2 (district proxies, mine disturbance), the extra skill may mostly be district recognition. Needs the leave-one-district-out test and a feature-group ablation.
6. **Everything is one region.** Nothing here shows transfer to another area; state that in the model card.
7. **3 of 5 repeats used.** They are nearly the same assignment (Phase 5), so the extra two add little.

## 9. How to reproduce
```powershell
.\.venv\Scripts\python.exe scripts\run_pipeline.py
```
Finished (model, repeat) units are skipped; delete `models/oof/` to retrain from scratch.
