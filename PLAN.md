# Mineral Prospectivity Mapping (Uranium) - Phase Plan v2

Goal: an end-to-end, crash-safe, CPU-only prospectivity pipeline on public data, from data
collection to a Dockerized app on GCP Cloud Run. Output is a *ranked favorability map with
uncertainty*, never a claim of deposit discovery.

Design rule for the whole project: **sparse positives are the central risk**, so they shape
the region choice, labels, splits, models and metrics from Phase 1 onward.

## Crash-safety rules (apply to every phase)
1. Every stage is a script: files in -> files out. No state lives only in memory or a notebook.
2. Every stage skips itself if its outputs exist and its inputs are unchanged (hash check).
3. Downloads are resumable and checksum-verified; partial files are never trusted.
4. Training checkpoints per (model, fold, seed); a crash resumes at the unfinished unit.
5. Fixed random seeds; all settings live in one config file.
6. Git commit at the end of every phase.
7. Large data and models are git-ignored but listed in a manifest with checksums.
8. **Documentation rule:** a phase is not finished until its record exists in
   `docs/phases/phase-NN-*.md` (from `TEMPLATE.md`) and `docs/PROJECT_DOCUMENTATION.md`
   (status table, glossary, architecture) is updated. Challenges are logged as they happen.

## Phase 0 - Foundation
- Folder layout, Python 3.11 environment (project uses 3.11, not the system 3.9), Git, .gitignore.
- Config file, logging, resume-safe stage runner, Dockerfile skeleton (dev image from day one).
- Teach: why this architecture, why stages are idempotent.
- Done when: `run_stage` skips completed work and a smoke test passes inside Docker.

## Phase 1 - Framing, region selection, positive-count gate  (new gate)
- Write the problem statement, success metrics and the baselines we must beat
  (prevalence baseline, a geology-only rule-based score, label-shuffle).
- Build the data catalog: source, URL, license, format, resolution, size.
- Download occurrence points FIRST. Count positives in each candidate region.
- **Gate:** need roughly >=100 positives total and >=20 per spatial fold. If a region fails,
  widen it or switch region. Record the decision and the numbers in `docs/decisions.md`.
- Teach: mineral systems (source, pathway, trap, preservation) -> which layers we need and why.

## Phase 2 - Data collection
- Resumable downloads: occurrences, radiometrics (eU, eTh, K), magnetics, DEM, geology/faults.
- Checksums, manifest, raw files are read-only afterwards.
- Teach: raster vs vector vs table, CRS, resolution, line spacing of airborne surveys.

## Phase 3 - Raw data validation and exploratory analysis
- Checks: file opens, CRS, extent overlap, nodata flags (e.g. -99999), value ranges, units,
  survey artifacts (flight-line striping), duplicate or misplaced occurrence points.
- EDA plots tied to the geology: eU/eTh behavior, magnetic lows over faults, cover areas.
- Validation report saved to `reports/`. Failing checks stop the pipeline.
- Teach: why each check exists and what failure looks like.

## Phase 4 - Preprocessing and master grid
- One target CRS (meters), one cell size, one study box. Reproject, clip, resample
  (bilinear for continuous, nearest for categorical), float32, tiled to fit 8 GB RAM.
- Second validation pass on processed grids (alignment, nodata masks, no shifted pixels).
- Teach: resampling, alignment, why 8 GB RAM forces tiling.

## Phase 5 - Label design and spatial split design  (expanded)
- Positives: all uranium occurrences, prospects and mines (more positives, documented).
- Background: unlabeled cells, not proven barren (positive-unlabeled framing). Sample several
  independent background sets with a buffer around known points.
- Spatial blocks assigned so each fold has a fair share of positives (stratified by block);
  repeated with several block layouts and seeds.
- Teach: spatial autocorrelation, leakage, class imbalance, PU learning.
- Splits are frozen to disk before any modeling so every model is judged on the same folds.

## Phase 6 - Feature engineering and transformation
- Radiometric ratios (eU/eTh, eU/K), log transforms, magnetic derivatives, terrain slope and
  roughness, distance to faults, lithology encoding, neighborhood statistics.
- Optional knowledge-driven favorability score from the mineral-system mind map.
- Fit scalers/encoders on training folds only (no leakage). Save the feature table (parquet).
- Teach: each feature mapped to its geological meaning.

## Phase 7 - Approach and model selection, baselines, training
- Baselines first: prevalence, geology rule score, logistic regression.
- Candidates, kept regularized for few positives: random forest / extra trees (bagging),
  shallow histogram gradient boosting / LightGBM (boosting), stacking only if it earns it.
- Train per (model, fold, seed) with checkpoints; CPU, n_jobs, float32.
- Teach: bias-variance, bagging vs boosting vs stacking, why simple wins on small data.

## Phase 8 - Cross-validation, bias/variance, rigorous evaluation  (expanded)
- Repeated spatial CV over several block layouts and seeds -> score distributions, not one number.
- Metrics: ROC-AUC, PR-AUC vs prevalence baseline, precision, recall, F-scores at chosen
  thresholds, top-k% area capture / lift, Brier score.
- Bootstrap confidence intervals, label-shuffle test, learning curves (variance), train vs
  validation gap (overfitting), compare to every baseline.
- Hyperparameter tuning with nested or spatially-blocked CV, with resumable search state.
- Decision rule written down before looking at test results.

## Phase 9 - Interpretation, calibration, uncertainty, bias checks
- Permutation importance and SHAP-style checks: is the model using geology or artifacts
  (flight lines, roads, survey edges)?
- Calibration curve; ensemble-disagreement uncertainty map; spatial residual check.
- Honest limits section: cover masking, sparse labels, survey resolution.

## Phase 10 - Final model, saving, serving
- Refit on all data with the chosen config; save model + preprocessor + metadata + model card.
- FastAPI endpoint (bounding box or point -> score, uncertainty, top features).
- Streamlit app: layers, heatmap, threshold slider, metrics and limitations page.
- Tests for the API and for inference reproducibility.

## Phase 11 - Dockerization
- Multi-stage, slim image; data and model mounted or baked per size; healthchecks;
  docker-compose for API + UI locally; verify a cold start from a clean clone.

## Phase 12 - GCP Cloud Run deployment (you hold the account)
- I prepare: Dockerfile, deploy commands, a checklist, cost and quota notes.
- You do: project, billing, auth, API enablement. I never enter credentials.
- No deploy without your explicit go-ahead. Then smoke test, logs, a basic budget alert, teardown steps.

## Phase 13 - Wrap-up
- README, architecture diagram, model card, results summary, reproduction guide.
- If time: a second region as an out-of-area generalization test.

## Phase gates summary
| Gate | After | Pass condition |
|------|-------|----------------|
| G1 | Phase 1 | Enough positives per region and per fold |
| G2 | Phase 3 | All raw validation checks pass or are documented |
| G3 | Phase 4 | Processed grids aligned and clean |
| G4 | Phase 8 | Beats all baselines with CI excluding the baseline; shuffle test fails as it should |
| G5 | Phase 11 | Clean-clone Docker run reproduces the result |
