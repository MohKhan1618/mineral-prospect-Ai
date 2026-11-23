# Phase 9 - Decision rule (written 2026-11-21, BEFORE any Phase 9 result was computed)

Candidate: logistic regression (Phase 8 choice). Rules are fixed here and changed only by a dated note at the bottom.
Unless stated, results use repeat 0 of the frozen block folds (3 repeats where cheap) and the INCLUSIVE evaluation.

## 1. What is being asked
Is the model right for the right reasons, are its numbers honest, and where is it unreliable?
The Phase 8 verdict stands: this is a local-radiometric ranking. Phase 9 cannot turn G4 into a pass; it can only
describe the model better or find new problems.

## 2. Importance and attribution
- **Permutation importance** on held-out folds: the fold model is fitted on training blocks only; on a test sample
  (all test positives + 200,000 random unlabeled test cells) one feature (or a whole group) is shuffled among cells,
  3 shuffles; the metric is the drop in recall at the top 5 % and in ROC-AUC (percentile method of Phase 8).
  A feature or group is "used" if its drop in recall@5 % is >= 0.03 (same threshold as the ablation).
  Single features that are strongly correlated share credit, so groups are the unit we draw conclusions from.
- **Linear attribution** (exact SHAP for a linear model): contribution_j = coefficient_j x standardised value_j.
  Reported per group, for held-out positives versus typical unlabeled cells, and coefficient sign stability across folds.
- **Location-proxy flag:** smooth regional variables (`mag_IGRF`, `ter_elev`, `mag_RTP_mean_5km`, `nbr_*_5km`) can act
  as a coordinate. If any of the first three is "used" (>= 0.03) it is flagged as a possible location proxy.

## 3. Calibration (only meaningful for "labelled-positive rate")
- Training used class weights, so raw probabilities are inflated by about 1/prevalence. We fit a cross-fitted Platt
  map (logistic regression on the logit of the score, fitted on the other folds' out-of-fold cells, applied to the
  held-out fold; unlabeled cells subsampled with weights). The calibrated value estimates P(cell is a labelled
  positive), a LOWER BOUND on true prospectivity because unlabeled cells include undiscovered deposits.
- Reported: Brier score and Brier skill score against the constant prevalence forecast; reliability table over
  score-percentile bins (top 0.1, 1, 5, 10, 25, 50 %, rest) with block-bootstrap intervals.
- Pass if: Brier skill > 0 AND observed rate rises monotonically across at least 6 of the 7 bins.
  Brier skill will be tiny anyway (prevalence 6e-5); it is reported for completeness, reliability is what matters.

## 4. Uncertainty
- **Ensemble disagreement map**: per cell, standard deviation of the within-fold score percentile across
  (a) the four learned families (logreg, rf, et, hgb) and (b) the three split repeats of logreg. Combined = mean of the two.
- This measures model-choice and training-sample sensitivity, NOT data error or label error. Say so on every map.
- Claim "uncertainty is informative" only if, for held-out positives, the lowest-uncertainty third hits the top 5 %
  at least 0.10 more often than the highest-uncertainty third. Otherwise report it as descriptive only.

## 5. Artefact and bias checks
- **Survey edge:** score percentile and top-5 % share by distance to the survey footprint edge (0-1, 1-2, 2-5, 5-10,
  10+ km). Flag if the mean percentile within 1 km of the edge differs from the interior mean by more than 0.05, or
  the top-5 % share in that zone is more than 2x or less than 0.5x its share of area.
- **Flight lines (200 m spacing, i.e. 4 cells):** 2-D power spectrum of the score map and of the raw uranium grid.
  Look at wavelengths 150-260 m. Flag if the peak power in that band, in any direction, is more than 10x the median
  power of the same band over all directions, and also report the same figure for the raw uranium grid
  (a stripe present in the data and the map = data artefact passed through).
- **Cover:** Quaternary/unconsolidated cover hides bedrock. Report share of area, share of positives, and recall@5 %
  on cover versus non-cover cells.
- **Roads, pipelines, towns:** NOT testable, the project holds no such layer. Recorded as a limitation, not a pass.
- **Spatial residual:** Moran's I of the held-out percentile among positives (k = 5 nearest positives, 999 permutations).
  Positive I = misses cluster in space (model fails regionally, not randomly). Lists the 15 worst-ranked positives.

## 6. Ways this phase could embarrass the model (stated up front)
Importance mostly in `mag_IGRF`/`ter_elev`, strong survey-edge effect, stripe peak present in the map, or clustered
misses in one district. Any of these is reported plainly and carried to the model card.

## Dated notes
- 2026-11-21 (before running): "rises monotonically across at least 6 of the 7 bins" is made precise as: of the 6
  adjacent pairs of bins (best bin first), at least 5 have a higher observed rate in the better-scored bin.
- 2026-11-21 (before running): the survey-edge distance is measured from the edge of the valid-data mask
  (`master_mask.tif`), so water or no-data holes inside the survey also count as "edge".
- 2026-11-21 (AFTER seeing results): the uncertainty-informativeness criterion in section 4 is flawed. Cells ranked
  at the very top cannot have a large percentile spread, so low disagreement is partly mechanical. The rule returned
  'informative' (gap 0.91) but I withdraw that claim; uncertainty is reported as descriptive only.
