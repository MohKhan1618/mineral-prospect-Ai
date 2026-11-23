# Phase 9 - Interpretation, calibration, uncertainty, bias checks

Status: done   Date: 2026-11-21
Rules written beforehand: [phase-09-decision-rule.md](phase-09-decision-rule.md) (with dated notes).
Candidate: logistic regression, repeat 0 of the frozen block folds unless stated. Code: `src/mpm/interpret.py` (5 new tests, 49 pass).

## 1. What we did
Five pipeline stages (about 2.5 minutes in total): permutation importance and exact linear attribution, cross-fitted calibration, ensemble-disagreement and score maps (`reports/maps/*.tif`), artefact checks (survey edge, flight-line spectrum, cover, spatial residuals), and a summary of the pre-set rules (`reports/phase9_summary.json`).

## 2. Results
**What the model uses (permutation importance; recall in the top 5 % is 0.61 at baseline)**
| Group | Drop in recall@5 % when shuffled | Used (>= 0.03)? |
|---|---|---|
| neighbourhood | **0.51** | yes |
| structure | 0.005 | no |
| magnetic | 0.003 | no |
| terrain, geology, radiometric (point values) | about -0.01 | no |

Shuffling the neighbourhood group removes almost all skill (ROC-AUC 0.86 -> 0.40). Single features: `nbr_U_mean_5km` (0.23), `nbr_U_std_1km` (0.20); nothing else reaches 0.03. This matches the Phase 8 ablation.
Linear attribution (positives minus typical cells, logit units): neighbourhood **+6.0**, structure +0.29, geology +0.12, magnetic +0.11, terrain -0.09, radiometric point values **-1.43**.
Location-proxy check: `mag_IGRF`, `ter_elev`, `mag_RTP_mean_5km` are all below 0.03, so not "used" by the rule. But `mag_IGRF` has the largest coefficient (1.13, same sign in all 5 folds); see red flag 6.

**Calibration** (cross-fitted Platt map; value = P(cell is a labelled positive))
Brier 5.759e-5 versus 5.764e-5 for the constant forecast: skill score 0.0009 (essentially nothing, expected at prevalence 6e-5). Reliability (observed rate per cell, lift over prevalence): top 0.1 %: 0.0055 (95x); top 1 %: 0.0023 (40x); top 5 %: 0.00022 (3.9x); top 10 %: 1.8x; top 25 %: 0.77x; top 50 %: 0.32x; rest: 0.21x. Bins are perfectly ordered (6 of 6 pairs), so the **pre-set rule passes**, but the Platt probabilities themselves are poor: mean predicted is 2.6x too low in the top 0.1 % bin and 3-6x too high in the bottom half.

**Uncertainty** (disagreement of four model families plus three split repeats, in percentile units; mean 0.088). Positives in the lowest-uncertainty third are hit in the top 5 % 100 % of the time, the highest third 9 %. The rule calls this "informative", but see red flag 3.

**Artefacts**
| Check | Result |
|---|---|
| Survey edge | 0-1 km from edge: 6.3 % of area, 16.6 % of positives, top-5 % share 9.6 % (1.9x expected; rule flag at 2x not hit), mean percentile 0.46 vs 0.47-0.55 inside. No flag by rule |
| Flight-line stripes (150-260 m band) | raw uranium grid: peak 20x median (control band 1.7x), so **stripes exist in the data**. Score map: 5.4x (control 3.2x), below the 10x flag |
| Cover (unconsolidated) | 10.5 % of area, 12 positives (6 %); recall@5 % 0.58 vs 0.61 elsewhere; but cover cells enter the top 5 % only 1.5 % of the time (vs 5.4 %) |
| Spatial residual | Moran's I of positive percentiles 0.52 (p 0.001): **misses cluster**. 21 of 199 positives (11 %) fall below the 50th percentile |
| By district | 7: recall@5 % 0.66; 8: 0.75; 1 (13 positives): 0.15; 6 (7, no producers): 0.14, mean percentile 0.37 |
| Roads, pipelines, towns | **not tested** (no layer in the project) |

## 3. Challenges
| Challenge | Solution |
|---|---|
| Permuting single correlated features understates their importance | Groups are the unit for conclusions; single features are detail |
| Different folds' scores are not comparable for maps | Within-fold percentiles; the map has fold seams |
| 55 configs x 3 shuffles x 5 folds is slow | Score a sample (all positives + 200k unlabeled) and use the linear form logit = Z w + b, so a shuffle only changes the affected columns |

## 4. Known limitations / red flags
### 🚩 Red flags
1. **The model is the neighbourhood-uranium group and nothing else.** Consistent with Phase 8; it does not learn geology.
2. **Calibration passes the rule but is not usable as probabilities.** Platt is too flat. Phase 10 must use binned or isotonic rates and describe them as labelled-positive density, never "probability of a deposit". The Brier score is almost uninformative at this prevalence.
3. **The uncertainty "pass" is probably a ceiling artefact.** Top-ranked cells cannot have a large percentile spread, and my rule did not control for the score level. I withdrew the claim (dated note in the rule). Uncertainty also ignores data and label error.
4. **Predictions fail regionally, not randomly.** Misses cluster (Moran's I 0.52); small districts fail. Quote performance per district, not only pooled.
5. **Survey-edge watch item.** 17 % of positives sit within 1 km of the edge on 6 % of the area, and the top-5 % share there is 1.9x expected (threshold 2x), so no pass with margin. Cause unknown: it may be reduced data in the neighbourhood windows, or simply where districts lie.
6. **`mag_IGRF` has the largest linear coefficient** (same sign in all folds) yet shuffling it costs only 0.01 recall. A smooth regional field acts like a coordinate; it probably shares credit with the neighbourhood features. Unproven; a refit without it would settle it (not done).
7. **Neighbourhood uranium variability (`nbr_U_std_1km`) is the second strongest single feature.** It could reflect mine disturbance or flight-line stripes as well as geology. Phase 8's no-producer test found no material change, but that test is weak.
8. **Point radiometric values contribute negatively (-1.43)** while the neighbourhood contributes +6.0: the model prefers high surroundings and, relative to them, lower values at the cell itself. My unproven hypothesis is positional error of the occurrence point (most scores are D), so the point sits beside the anomaly.
9. **Stripes exist in the raw uranium grid** (20x). The score map is mostly clean, but the neighbourhood features may carry some; levelling or de-striping was not done.
10. **Cover and infrastructure.** Radiometrics see only the top 30-50 cm, so mineralisation under cover is invisible. Only 12 positives lie on cover, too few to judge. Roads and infrastructure were not tested at all.

## 5. Concepts learned
- **Permutation importance:** shuffle a feature among held-out cells; the damage to the ranking is its importance. Correlated features share credit.
- **Exact SHAP for a linear model** is coefficient x standardised value.
- **Calibration vs ranking:** a model can rank well and still give wrong probabilities; with unlabeled data the "probability" is the labelled-positive rate, a lower bound.
- **Brier skill score** compares with the constant-prevalence forecast; at tiny prevalence everything is near zero.
- **Ceiling effect** in ensemble disagreement.
- **Moran's I:** spatial autocorrelation; applied to errors it shows whether failures are regional.
- **Power spectrum** reveals periodic stripes (200 m flight-line spacing = 4 cells).

## 6. How to reproduce
```powershell
.\.venv\Scripts\python.exe scripts\run_pipeline.py
```
Outputs: `reports/phase9_*.csv/json`, maps in `reports/maps/`.
