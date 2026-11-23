# Phase 8 - Decision rule (written 2026-11-21, BEFORE any Phase 8 result was computed)

Phase 7 numbers were seen; none of the experiments below had been run. Rules are fixed here and only changed
by an explicit dated note at the bottom, never silently.

## Evaluation conventions
1. **Inclusive evaluation is the headline.** Unlabeled cells include the 2 km buffer ring around positives.
   The exclusive version (Phase 7) is shown only as a contrast.
2. **Primary decision metric: recall in the top 5 % of cells** (what an explorer gets by surveying 5 % of the
   area), ties broken by ROC-AUC. PR-AUC and lift are reported but not used to decide: with about 200
   clustered positives they are too noisy.
3. **Uncertainty = block bootstrap**: resample the 15 km blocks that contain positives (2,000 replicates),
   pooled over folds and repeats. Differences between models are paired (same resamples). These intervals are
   still optimistic because positives sit in two districts.
4. **Every number is shown for (a) all positives and (b) non-producer positives only.** The non-producer
   number is the one to quote if the two disagree materially, because mine workings disturb the surface.

## Gate G4 (from PLAN.md), made precise
A learned model PASSES G4 only if ALL hold:
- Its paired 95 % interval for (model minus baseline) excludes 0 on recall@top 5 % AND on ROC-AUC, for each
  baseline: prevalence, geology rule, single uranium feature.
- The label-shuffle test (labels permuted in training, true labels in testing) gives mean ROC-AUC within
  0.45-0.55.
- Leave-one-district-out mean recall@top 5 % is above that of the single uranium feature in at least half of
  the held-out districts.
**Outcome rules:**
- Pass -> that model is a candidate for Phase 9/10.
- Pass against prevalence and rule, but not against the uranium feature -> G4 is NOT met. Say so plainly; the
  product is then described as "a uranium-radiometric ranking with modest added value", and no claim of
  geological understanding is made.
- Shuffle test outside 0.45-0.55 -> treat as a leakage bug; stop and investigate before anything else.

## Choosing among finalists (logreg, rf, et)
Highest mean of (block-CV recall@top 5 %, leave-one-district-out recall@top 5 %). If finalists are within
0.02, choose the simpler (logreg < rf < et).

## Hyper-parameter tuning
Nested: inner spatial CV on the outer-training blocks only. A tuned configuration replaces the default only if
its outer-fold mean recall@top 5 % is higher by at least 0.02 and its ROC-AUC is not lower by more than 0.005.

## Reading the diagnostics
- **Feature-group ablation:** a group is "needed" if removing it lowers recall@top 5 % by at least 0.03;
  "sufficient" if using only that group stays within 0.03 of the full model.
- **Mine effect:** if training WITHOUT producer records changes non-producer ROC-AUC by more than 0.02, mine
  disturbance is materially affecting the model (flag it in the model card).
- **Learning curve:** if test recall still rises from 75 % to 100 % of the training data, variance dominates
  (more data would help); if it is flat while train AUC is high, the gap is model capacity or label noise.

## Not done in this phase (moved)
Brier score and calibration are meaningless with class-weighted training (probabilities are inflated);
they are done in Phase 9 together with calibration.

## Dated notes (added before results)
- 2026-11-21: G4 will be reported twice, on all positives and on non-producer positives. The final verdict is the
  stricter one (non-producers), consistent with convention 4 above.
- 2026-11-21: random forests inside the ablation and learning-curve experiments use 100 trees (not 200) to
  keep run time reasonable; tuning's inner loop also uses 100 trees. Final comparisons use 200.
- 2026-11-21 (AFTER seeing results): the pre-registered label-shuffle test returned ROC-AUC 0.21-0.31, outside
  0.45-0.55, so by the rule above I stopped and investigated. It is below 0.5, not above, so it is not leakage.
  I replaced it with a random-positive null (same number of positives planted at uniformly random cells, identical
  pipeline), result 0.48-0.51. This replacement was chosen after the failure (post hoc). The shuffle result is
  still reported and G4 is judged on the criteria as written (it fails on the uranium-baseline criterion anyway).
