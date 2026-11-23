# Decision log

Every non-obvious choice goes here with the reason, so we never re-argue it.

## 2026-11-20 - Phase 0
- **Python 3.13** locally and in Docker (3.11 not installed; 3.13 has wheels for the stack).
- **Stage = files in, files out**, skipped via input/param fingerprint. Reason: the dev machine
  crashes unpredictably; no work may live only in memory.
- **Atomic writes** for every output so a crash never leaves a half-written file that looks done.
- **Region is not chosen yet.** Phase 1 decides it using a positive-count gate (see config.yaml).
- Docker Desktop was not running at setup; needed from Phase 11.

## 2026-11-20 - Phase 1
- **Region shortlist:** South Pass-Granite Mountains (primary, 535 unique positives), Shirley Mtns-Hartville (backup, 220). Sierra Madre-Medicine Bow dropped (94 < 100).
- **Occurrence source:** MRDS via mrdata.usgs.gov (reachable; ScienceBase/usgs.gov return 403 to scripts).
- **Count unique coordinates**, not records, so duplicates do not inflate positives.
- Candidate boxes are approximate until the real survey extents are read in Phase 2.

## 2026-11-20 - Phase 2
- **Use `.grd` grids, not contractor GeoTIFFs** (the TIFFs are RGB pictures). Needs conversion.
- **Verify, don't extract, in code** (Deflate64 zips; user extracted manually).
- **True positive count is 188** inside the real footprint (Phase 1 said 535 using an approximate box). Gate still passes; margin thin.
- Red flags are raised in chat and recorded in each phase record (user request).

## 2026-11-21 - Phase 3
- **Grids exported as COG float GeoTIFF** via Geosoft Viewer; stored in `radiometrics/CONVERTED` and `magnetics/CONVERTED`.
- **Units from the report:** radiometric grids are counts/sec, not ppm (ppm = counts / sensitivity: U 10.4, Th 6.2; K % = counts / 99.5).
- **`_s` grids excluded** until their meaning is documented (values look normalised).
- **Use only cells valid in all layers** and require all layers to share one grid (enforced by `check_alignment`).
- **Positive count corrected to 205** (inside the real footprint; Phase 2's 188 used the old box). 202 on valid cells.
- **Signal check method:** single-layer AUC vs all surveyed cells with bootstrap CI, split by producers/non-producers. Result: radiometrics informative, magnetics weak.
- **Cleaning rules R1-R5** (see phase-03 record): common mask; negatives to 0; cap at 99.9th percentile (not delete: spikes are clusters); centre RTP/Mag_IGRF by the median (no detrend, plane R2 = 0.004); `_s` unused.
- **Cleaned grids** live in `data/interim/clean/`; raw never modified.

## 2026-11-21 - Phase 4
- **Master grid = the survey grid** (EPSG:32613, 50 m); study area fixed to the survey footprint.
- **Terrain: SRTM 1 arc-second** (AWS open tiles); **geology: SGMC Wyoming** from mrdata.usgs.gov. USGS ScienceBase stays blocked for scripts.
- **Average resampling for terrain** (30 m to 50 m is shrinking), **rasterise for geology**, class codes with a saved legend.
- **Master mask** = cells valid in all radiometric, magnetic and terrain layers.
- **Revised:** occurrences sit mostly on clastic sedimentary rock (83 %), not granite; earlier "radioactive granite" worry downgraded.

## 2026-11-21 - Phase 5
- **Positive = any uranium MRDS record (all dev_stat values) inside the footprint, one per 50 m cell.** 260 records -> 257 on valid cells -> 199 positive cells. Occurrence/Prospect kept; dropping them would leave a mostly-mine set.
- **dev_stat, score, is_producer kept as metadata, never filters.** Phase 8 runs a with/without-producers sensitivity test.
- **Unlabeled background, not negatives.** Cells within 2 km of a positive are marked excluded (code 3) and not sampled as background.
- **Blocks 15 km, 5 folds, 5 repeats, frozen to `data/splits/splits.csv`.** 20 km was rejected (two blocks held 61 % of positives); 5 km rejected (30 % cross-fold neighbours). 15 km: folds 47/40/38/37/37 positives.
- **Phase 8 must also run leave-one-district-out** on the two big clusters (the harshest, most honest test).

## 2026-11-21 - Phase 6
- **49 features in 6 groups** (radiometric 11, neighbourhood 11, magnetic 7, terrain 4, structure 2, geology 14), all computed from maps only, never from labels. Scaling and imputation are deferred to Phase 7 and fitted on training folds.
- **Stabilised log-ratios** log((a+1)/(b+1)) instead of raw ratios: defined where Th or K is 0, symmetric, tames skew.
- **Storage:** feature-major `float32` `.npy` over valid cells (49 x 3,452,181, 677 MB) plus `cell_index.npy` and `feature_catalog.json`, memory-mapped. PLAN.md said parquet; pyarrow is not installed and a 3.4 M-row table is simpler as an array. Revisit for the Docker/API phase.
- **scipy added** to requirements (distance transforms, window filters).
- **Faults** = SGMC lines whose description contains "fault" or "shear zone"; dikes are in the same file but excluded. Faults up to 20 km outside the survey count.
- **No feature selection yet.** Univariate AUCs are reported but not used to drop anything (selection happens inside CV in Phase 7/8, else it leaks).

## 2026-11-21 - Phase 7
- **Seven candidates, simplest first:** prevalence, geology rule, single-feature U, regularised logistic regression, random forest, extra trees, shallow gradient boosting (sklearn `HistGradientBoosting`; LightGBM not installed, no gain expected at this size).
- **Training protocol:** buffered spatial CV. Training cells within 2 km of any test-fold positive are removed (positives and background); training set = all remaining positives + 40,000 random unlabeled cells, identical for all models; class weights balance the imbalance. Every model scores every test cell, so out-of-fold maps are complete.
- **Fixed, regularised hyper-parameters (no tuning yet):** logreg C=0.05; trees depth 10, leaves >= 10, 200 trees; HGB depth 3, lr 0.05, 200 iterations. Tuning belongs to Phase 8 inside nested CV.
- **3 of 5 split repeats used** (they differ little, Phase 5). Results stored per model and repeat in `models/oof/<hash>/`; re-running resumes.
- **Phase 7 headline numbers are NOT final.** The evaluation here excludes the 2 km buffer around positives from the unlabeled cells. This inflates PR-AUC about 50x (see phase-07 record). Phase 8 must report the inclusive version as the headline.
- **Finalists for Phase 8:** logreg, rf, et (plus the baselines as references). hgb dropped for now (lowest ROC-AUC and recall among the learned models).

## 2026-11-21 - Phase 8
- **Gate G4 NOT met.** No learned model beats the single-uranium-feature baseline with a CI excluding 0 (all positives or non-producers). All beat prevalence and the geology rule.
- **Pre-registered shuffle test failed in the "safe" direction (0.21-0.31, below 0.5).** Replaced post hoc by a random-positive null (0.48-0.51). Recorded as a deviation.
- **Chosen candidate: logistic regression** (rule: highest mean of block-CV and leave-one-district-out recall@5 %; also the simplest). rf and et are within noise.
- **Tuning changed nothing:** logreg gain +0.016 recall (< 0.02 threshold), rf none. Phase 7 defaults stay.
- **Mine effect below the 0.02 threshold** (non-producer ROC-AUC changes by -0.012 to +0.009 when trained without producers). Non-producer numbers are still the ones to quote.
- **Product positioning if we continue:** a radiometric-uranium ranking with modest added value; no claim that the model understands geology.
- **Brier/calibration moved to Phase 9; precision/F-score at thresholds not reported** (thresholds are arbitrary and unlabeled cells are not true negatives); top-k lift and recall are reported instead.

## 2026-11-21 - Phase 9
- **Model uses only the neighbourhood group** (permutation drop in recall@5 % 0.51 of 0.61); no location-proxy feature passes the 0.03 rule; `mag_IGRF` has the largest sign-stable coefficient but a permutation drop of only 0.01 (watch item).
- **Calibration passes the pre-set rule but the Platt map fits badly in the tails** (3-6x too high in the lower half, 2.6x too low at the top 0.1 %). Phase 10 should use a binned/isotonic map and quote bin rates.
- **Uncertainty 'informative' result is withdrawn:** the rule is confounded by a ceiling effect (top-ranked cells cannot disagree much). Descriptive use only.
- **Misses are spatially clustered** (Moran's I 0.52, p 0.001): small districts fail, the two big districts work.
- **Roads/infrastructure not tested** (no layer). The raw uranium grid has 200 m flight-line stripes (peak 20x control); the score map is mostly free of them (5.4x, below the flag at 10).

## 2026-11-21 - Phase 10
- **Final model = Phase 8 choice refit on all data** (199 positives + 40,000 unlabeled outside the 2 km ring), default hyper-parameters.
- **Serve precomputed per-cell values;** API and app do not load features or the model. Reproducibility test ties the store to the model code path.
- **Report out-of-fold bin rates (labelled-positive density), not model probabilities;** all performance numbers are out-of-fold, the map is labelled in-sample.
- **Top drivers are feature groups, not single features** (storage and defensibility). Deviation from PLAN.md.
- ~~New red flag: straight-edged hot block in the east (14 to 33 step; survey-block levelling).~~ **Withdrawn 2026-11-21 (Phase 10b):** no straight step in raw U or the final map; the rectangle was a CV-block edge in the out-of-fold map and the 14-to-33 figure spanned a no-data notch. Remaining: edge notch near easting 344 km; offsets below about 10 % untested.

## Phase 10c - Web frontend
- **Custom Leaflet single-page site served by the existing FastAPI (one image); Streamlit stays as a fallback.**
- **Evidence, model drivers, textbook guide and cautions are shown as four separate blocks.** The model supplies no geological reasoning; the guide is labelled as general knowledge, unreviewed by a geologist.
- **Hot-spot polygons precomputed and reprojected (GeoJSON), not an image overlay** (UTM grid convergence would shift an image by kilometres).
- **Areas of interest = clusters of the top 5 %, ranked by top-1 % cell count then area;** each states whether known occurrences lie inside (partly in-sample) or not (candidate, uncheckable).
