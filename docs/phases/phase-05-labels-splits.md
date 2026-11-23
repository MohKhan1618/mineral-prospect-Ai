# Phase 5 - Labels and spatial splits

Status: done   Date: 2026-11-21
Gate: positives per fold >= 20 in every fold of every repeat (PASS: smallest fold has 37); splits frozen to disk (PASS).

## 1. What we did
- User explored MRDS in Jupyter (`001-Understanding-Data.ipynb`): 304,632 rows worldwide, 46 columns, no bad coordinates, commodity strings hold lists, many records stacked on one coordinate.
- Built `src/mpm/labels.py`: MRDS uranium records in the footprint -> one positive per 50 m cell -> label raster `data/processed/labels.tif` (0 outside, 1 unlabeled background, 2 positive, 3 excluded buffer) and `data/processed/positives.csv`.
- Built `src/mpm/splits.py`: 15 km blocks, 5 folds, 5 repeats, saved as `data/splits/splits.csv` (repeat, block_id, fold) plus `data/splits/block_id.tif` for viewing in QGIS.
- Pipeline stages `05_labels`, `05_splits`; 6 new tests (25 pass in total).

## 2. What it does
Input: MRDS CSV, footprint, master mask. Output: which cells are positive, which are excluded, and a fixed fold for every block. Every later model reads these files and never makes its own split.

## 3. Why it was necessary
Labels define the question the model answers. Splits decide whether the final score is honest: neighbouring cells look alike, so a random split would leak and inflate every metric.

## 4. Concepts learned
- **Positive-unlabeled (PU)**: a missing record does not mean no uranium. Background is "unlabeled", never "negative".
- **Collapse to cells**: 260 records on 205 coordinates became 199 cells; stacked records at one place are one location, not several independent deposits.
- **Spatial block CV**: whole map blocks go to one fold. Geology link: two holes in one roll-front district are the same deposit; they must not be split between train and test.
- **Greedy balancing with noise**: biggest blocks first, each to the lightest fold; noise makes repeats differ.
- **Leakage proxy**: share of positives with a positive from another fold within 2 km.

## 5. Challenges faced and how we solved them
| Challenge | Impact | How we solved it |
|---|---|---|
| Your notebook looked global (Tasmania stack, 166 countries) | Confusion about wrong data | Not wrong: MRDS is worldwide; our code filters US + uranium + footprint |
| With 20 km blocks two blocks held 67 and 55 positives (61 %) | Folds 67/55/26/25/26; repeats nearly identical | Compared 5, 8, 10, 15, 20 km blocks; chose 15 km (see table) |
| 3 records fell on cells outside the master mask | 257 of 260 usable | Dropped, counted in the label report |

Block-size comparison (positives per fold; share of positives with a cross-fold neighbour within 2 km):
| Block | Folds | Cross-fold neighbours |
|---|---|---|
| 5 km | 40/40/40/40/39 | about 31 % |
| 8 km | 40/40/40/40/39 | about 39 % |
| 10 km | 47/38/38/38/38 | about 23 % |
| **15 km (chosen)** | **47/40/38/37/37** | **about 22 %** |
| 20 km | 67/55/26/26/25 | 17 % |

## 6. Results and evidence
- 260 records -> 257 on valid cells -> **199 positive cells**; 32 cells hold several records.
- By status: Past Producer 79, Occurrence 44, Prospect 34, Unknown 23, Producer 19. **98 producer cells, 101 non-producer.**
- By score: D 173, C 17, E 6, B 3.
- Prevalence 5.8e-5 (199 of 3,452,181 cells): a random model's PR-AUC is about 0.00006. Excluded buffer 360,961 cells; background 3,091,021.
- Positives per fold in every repeat: smallest fold 37 (gate: 20).

## 7. Decisions and trade-offs
See `docs/decisions.md`, Phase 5. Positive = any uranium record (all statuses); status and score kept as metadata; buffer 2 km; blocks 15 km.

## 8. Known limitations / open items
### 🚩 Red flags
1. **Two districts hold most positives.** Two clusters, centred near x 288 km, y 4,739 km and x 268 km, y 4,696 km (UTM 13N; probably the Gas Hills and Crooks Gap/Green Mountain uranium districts, to confirm in QGIS), hold 67 and 55 positives in 20 km blocks (61 % of all) and 47 and 40 in the chosen 15 km blocks. Two folds are therefore each dominated by one district. Cross-validation measures "can the model find a new district", and the result will be dominated by two test cases. Plan: Phase 8 also runs leave-one-district-out and reports it as the headline honest number.
2. **The five repeats are not independent.** Large blocks are forced into the same folds, so repeats differ only slightly (folds identical in size to ±1). Repeat spread will understate uncertainty. Report it as such.
3. **Leakage is reduced, not removed.** About 22 % of positives have a positive from another fold within 2 km (block edges cut through clusters). Phase 8 should drop training cells within the buffer of test positives.
4. **Half the positives are mine records** (98 of 199). Mine disturbance is visible to radiometrics; the model may learn "looks like a mine". Phase 8 runs a without-producers test.
5. **Poor label position.** 173 of 199 cells are score D; the MRDS metadata calls positional accuracy "highly variable". Some positives may be in the wrong 50 m cell. I could not find the meaning of the score letters in `mrds.met` (to confirm before interview use).
6. **Positives are not independent deposits.** 199 cells are far fewer than 199 independent samples; confidence intervals will be optimistic.
7. **Unlabeled background contains undiscovered or unrecorded uranium.** Metrics computed on it (precision especially) are lower bounds; lift and recall are more trustworthy than precision.

## 9. How to reproduce
```powershell
.\.venv\Scripts\python.exe scripts\run_pipeline.py
```
Outputs: `data/processed/labels.tif`, `data/processed/positives.csv`, `data/splits/splits.csv`, `data/splits/block_id.tif`, `reports/phase5_label_report.json`, `reports/phase5_split_report.json`.
