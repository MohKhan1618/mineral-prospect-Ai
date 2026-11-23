# Model card - uranium prospectivity pilot (South Pass - Granite Mountains, Wyoming)

Version 0.1, 2026-11-21. Artefacts: `models/final/` (`logreg_final.joblib`, `serving.npz`, `metadata.json`).

## What it is
A regularised logistic regression (C = 0.05, balanced class weights) on 44 of 49 engineered features (5 rare rock-class dummies dropped by the preprocessor). It scores every 50 m cell of the airborne-survey footprint by how much its surroundings resemble the surroundings of known uranium occurrence cells.

**In one sentence:** it ranks areas by their local radiometric uranium context; it does not understand geology and it does not predict deposits.

## Intended use
Teaching and portfolio pilot: showing a leak-free, spatially validated prospectivity workflow, and a cheap first-pass ranking of where to look at the radiometric data more closely. Not for investment, drilling or land decisions.

## Training data
- 199 occurrence cells (USGS MRDS uranium records collapsed to 50 m cells; 98 are producer or past-producer cells) as positives. Everything else is unlabeled, not negative (positive-unlabeled setting).
- 40,000 randomly sampled unlabeled cells outside a 2 km ring around positives.
- Features: airborne gamma-ray and magnetic grids (USGS South Pass survey, 200 m flight lines), SRTM terrain, USGS state geologic map, mapped faults.

## Performance (out-of-fold only; spatial block CV, 15 km blocks, 2 km ring counted as unlabeled)
| | Logistic regression | Raw uranium count alone | Chance |
|---|---|---|---|
| ROC-AUC, all 199 positives | 0.86 [0.72, 0.92] | 0.83 [0.70, 0.90] | 0.50 |
| Recall in the best-scored 5 % of cells, all | 0.61 [0.33, 0.76] | 0.53 [0.28, 0.67] | 0.05 |
| Recall in the best 5 %, 101 non-producers | 0.43 [0.23, 0.60] | 0.43 [0.25, 0.56] | 0.05 |
Intervals are 95 % block-bootstrap and still optimistic (positives sit in two districts). **The model does not beat the raw uranium count with confidence (gate G4 not met).** It clearly beats a hand-made geology rule (+0.16 ROC-AUC).
Per district (leave-one-district-out, recall in the best 5 %): district 7 0.70, district 8 0.61, small district 1 (13 occurrences) 0.08.

## Calibration
Out-of-fold observed rate of occurrence cells per cell by score-percentile bin: top 0.1 % 5.5e-3 (95x the average cell), top 1 % 2.3e-3 (40x), top 5 % 2.2e-4 (3.9x), top 10 % 1.8x, top 25 % 0.77x, top 50 % 0.32x, rest 0.21x. These are **labelled-positive densities, a lower bound on prospectivity**, because unlabeled cells include undiscovered deposits. They are not probabilities of a deposit. The API returns these bin rates, not the raw model output.

## Known limitations and failure modes
1. Relies almost entirely on the neighbourhood-uranium features (shuffling them cuts recall in the top 5 % from 0.61 to about 0.10). Geology, terrain, magnetic and structure features add nothing measurable.
2. Predictions fail regionally: positives outside the two big districts are ranked poorly (Moran's I of misses 0.52).
3. Half the training positives are mines; mine disturbance may leak into the neighbourhood features (no material effect found, but the test is weak).
4. Positional error of occurrence points (most MRDS scores are D) is likely; the model prefers high surroundings and lower values at the cell itself.
5. Raw uranium grid has 200 m flight-line stripes; the score map is mostly free of them (peak 5.4x vs 20x in the raw grid) but no levelling was done.
6. Edge and cover: 17 % of occurrences are within 1 km of the survey edge (6 % of area). Unconsolidated cover (10 % of area) hides bedrock from gamma-ray sensing.
7. **Survey blocks and edges:** the report's six sub-blocks were checked (Phase 10b); no straight step between blocks was found in the raw uranium grid or the final map, but offsets under about 10 % could not be detected. Predictions next to the survey's no-data notch (easting about 344 km, northing 4677-4694 km) and other edges rest on fewer valid neighbours and are less reliable.
8. `mag_IGRF` (a smooth regional field) has the largest coefficient; it may act as a location proxy. Not tested by refit.
9. Roads, pipelines and towns were not tested. Transfer to another geology or survey is untested.
10. The final map is in-sample at the 199 occurrences. Uncertainty (disagreement between models and splits) is descriptive; it ignores data and label error and is not a validated error bar.

## Ethical and practical notes
Public data only. The occurrence points are public USGS records. No claim of resource or reserve is made.

## Reproduce
`.\.venv\Scripts\python.exe scripts\run_pipeline.py` rebuilds everything (idempotent). Inputs are fingerprinted in `models/final/metadata.json`.
