# Phase 6 - Feature engineering and transformation

Status: done   Date: 2026-11-21
Gate: every feature finite on every valid cell (PASS, checked in code); features reproducible from one command (PASS); no feature uses labels (PASS by construction).

## 1. What we did
- Built `src/mpm/features.py` and stages `06_features`, `06_feature_report`; 6 new tests (31 in total).
- Produced **49 features** over the 3,452,181 valid cells, saved to `data/features/` (`features.npy` 677 MB, `cell_index.npy`, `feature_catalog.json` with each feature's group and geological meaning).
- Wrote `reports/phase6_feature_report.csv` (summary and univariate AUC of each feature against all valid cells, split by producers and non-producers) and `reports/phase6_correlated_pairs.csv`.
- Added `scipy` to requirements; tidied the `__import__` hacks in `run_pipeline.py`.

## 2. What it does
Turns the aligned maps into the table a model can learn from. One column per cell, one row per feature. Later phases pick cells by index (positives, sampled background, a test fold) and read only those columns from the memory-mapped file.

## 3. Why it was necessary
A model sees numbers, not geology. Features encode what a geologist looks for: uranium relative to thorium and potassium, local context around a pixel, magnetic edges, faults as fluid pathways, rock type as host, relief as erosion and weathering state.

## 4. Features and their geological meaning
| Group (count) | Features | Why it matters |
|---|---|---|
| Radiometric (11) | U, Th, K, TC counts/s; log1p of each; log-ratios U/Th, U/K, Th/K | Radiometric uranium is the direct signal; ratios show enrichment relative to the thorium and potassium that ordinary rock carries |
| Neighbourhood (11) | mean and std in a 1 km window and mean in a 5 km window for U, Th, K; U minus its 5 km mean; U/Th log-ratio of 5 km means | One 50 m pixel is noisy; roll-front systems extend over hundreds of metres; local anomaly against regional level |
| Magnetic (7) | RTP, Mag_IGRF, vertical derivative, horizontal gradient, analytic signal, local std, 5 km mean | Magnetic bodies and edges mark faults, dikes, iron-rich rocks; reduced magnetite in altered sandstone is a known sign |
| Terrain (4) | elevation, slope, roughness (250 m), TPI (1 km) | Erosion and weathering state, where oxidised fluids and sediments accumulate |
| Structure (2) | distance to fault or shear zone, fault density in 5 km | Faults are pathways for uranium-bearing fluids |
| Geology (14) | 13 one-hot rock classes, distance to nearest contact between classes | Host rock (clastic sandstone), and contacts where chemistry changes |

## 5. Concepts learned
- **Feature engineering = encoding domain knowledge as numbers.** Ratios, neighbours, edges.
- **Stabilised log-ratio**: adding 1 count/s to both parts keeps the ratio defined at 0 and makes it symmetric.
- **Neighbourhood statistics use only cells inside the mask** (otherwise outside-survey zeros would drag means down at the edges).
- **No leakage by construction**: nothing here looks at labels; fitting scalers is deferred to training folds.
- **Univariate AUC is a screening tool, not evidence**: see red flag 1.

## 6. Challenges faced and how we solved them
| Challenge | Impact | How we solved it |
|---|---|---|
| scipy not installed (earlier phases avoided it) | no distance transforms or fast window filters | Installed scipy, added to requirements |
| Gradients and slopes are NaN beside no-data cells | NaN features at survey edges | `fill_nearest` fills only for the derivative, the mask still decides which cells count |
| Raw ratios undefined where Th or K is 0 | NaN or infinite features | stabilised log-ratio with +1 |
| Faults outside the survey influence cells near its edge | edge cells would look far from faults | rasterised faults on a grid padded by 20 km |
| pyarrow missing (plan said parquet) | cannot write parquet | memory-mapped `.npy` instead (see decisions) |

## 7. Results and evidence
- 49 features, all finite on all 3,452,181 cells.
- Strongest single features against all cells (AUC): nbr_U_std_1km 0.89, nbr_U_mean_1km 0.88, nbr_U_mean_5km 0.86, rad_TC 0.84, rad_U 0.83, Th and K layers 0.75-0.83, fault distance 0.68 (lower is better), roughness 0.64, slope 0.64.
- Weak or none: elevation 0.51, TPI 0.50, RTP 0.55, most geology dummies about 0.50.
- Positives sit closer to faults (median 1.45 km) than the average cell (2.84 km).
- Only two pairs correlate above 0.95: rad_K with rad_log_K (0.96) and slope with roughness (0.95).
- Clastic sedimentary rock covers 2.26 M cells and holds 164 of 199 positives.

## 8. Known limitations / open items
### 🚩 Red flags
1. **The strongest features may be proxies for "which district am I in".** Two uranium districts hold most positives. 5 km means and local standard deviations describe regional radiometric level, so a model can score high by recognising those two districts. The univariate AUCs above are also optimistic for the same reason: positives are clustered, so the 199 points are not 199 independent tests. Phase 8's leave-one-district-out test is the real check; expect lower numbers than here.
2. **Local variability of uranium (nbr_U_std_1km) is the top feature and is higher for producers (0.94) than non-producers (0.84).** Mine pits, waste dumps and roads create sharp radiometric contrasts. The model may be detecting mining disturbance, not geology. Test without producers in Phase 8; keep a with/without comparison of the neighbourhood features.
3. **Radiometric levels overlap strongly** (U, TC, Th, K are all high for positives). Total count is not uranium-specific. rad_lr_U_TH, which targets uranium specifically, is weak (0.58 overall, 0.51 for non-producers). The earlier Phase 3 doubt about generic radioactivity remains.
4. **Five of 13 geology classes have no positives and few cells** (e.g. metamorphic gneiss has 66 cells). They give logistic regression near-constant columns. Phase 7 should merge rare classes using training data only.
5. **Fault data are a state-scale compilation** (SGMC, about 1:500,000 scale), so fault distances are approximate and dikes are excluded. The fault signal (0.68) may partly reflect that the faulted Wind River basin margin hosts the districts.
6. **49 features for 199 positives**, and many are near-copies at different scales. Overfitting risk is high; Phase 7 should favour regularised models and compare feature groups (ablation) in Phase 8.
7. **Magnetic anomaly near Atlantic City iron mine** is a strong outlier; magnetic features are unreliable there.

## 9. How to reproduce
```powershell
.\.venv\Scripts\python.exe scripts\run_pipeline.py
```
Load in code: `from mpm.features import load_features; X, cell_index, names = load_features("data/features")`.
