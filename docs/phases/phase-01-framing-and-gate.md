# Phase 1 - Framing, region selection, positive-count gate

Status: done (region shortlisted; exact survey extents to confirm in Phase 2)   Date: 2026-11-20
Gate G1: >=100 unique positives in the area, >=20 per spatial fold - PASSED for two of three areas (fold-level check happens in Phase 5).

## 1. What we did
- Wrote the framing: ranking task, sparse positives are the central risk.
- Built a resumable downloader (`src/mpm/download.py`) with manifest and checksums.
- Downloaded MRDS (25.8 MB, `data/raw/occurrences/mrds-csv.zip`) and registered it in `data/raw/MANIFEST.json`.
- Wrote `src/mpm/occurrences.py`: unzip, filter to US uranium records, count positives per candidate area.
- Added pipeline stages `01_download_mrds`, `01_unzip_mrds`, `01_positive_count`; output `reports/phase1_positive_count.csv`.
- Added the three candidate areas to `config/config.yaml`.

## 2. What it does
Turns the raw MRDS table (304,632 records worldwide) into a count of uranium occurrences inside each candidate survey area, and checks them against the gate in the config.

## 3. Why it was necessary
With few positives, model scores are noisy no matter how good the algorithm is. Checking the count first decides whether a region can support the project at all, before we spend time downloading and processing rasters.

## 4. Concepts learned
- **Positive / unlabeled data:** a mapped occurrence is a confirmed positive; everywhere else is *unlabeled*, not proven barren.
- **Class imbalance and prevalence:** with many cells and few positives, accuracy is meaningless; later metrics are judged against the prevalence baseline.
- **Unique locations vs records:** MRDS has several records at the same coordinates; counting records would overstate the positives (see challenges).
- **Geology link:** the occurrence points are the "answer key" the model learns from; the radiometric, magnetic and geologic layers are the clues from the mind map.

## 5. Challenges faced and how we solved them
| Challenge | Impact | How we solved it |
|-----------|--------|------------------|
| USGS ScienceBase / usgs.gov returned 403 to scripts | Cannot automate the radiometric/magnetic downloads from the script | Found that `mrdata.usgs.gov` is reachable and used it for occurrences; radiometrics deferred to Phase 2 (in-app browser or manual download) |
| Duplicate coordinates (e.g. 304 duplicates among 2,437 Wyoming uranium records) | Inflated positive counts, near-identical training rows | Gate counts unique locations; positives will be de-duplicated in Phase 5 |
| Survey boundaries not known exactly | Counts depend on the box | Used clearly labeled approximate boxes in config; must be replaced with real extents in Phase 2 |
| "Uranium" appears as any of three commodity columns | By-product sites mixed with primary uranium sites | Kept all for now (more positives); a primary-commodity sensitivity test is planned for Phase 5 |

## 6. Results and evidence
Wyoming: 2,437 uranium records in MRDS (1,193 occurrences, 612 past producers, 301 prospects, 97 producers, 234 unknown).

| Area (approximate box) | Records | Unique locations | Past/current producers | Gate |
|---|---|---|---|---|
| South Pass - Granite Mtns | 696 | 535 | 315 | pass |
| Shirley Mtns - Hartville | 234 | 220 | 43 | pass |
| Sierra Madre - Medicine Bow | 96 | 94 | 17 | fail (<100) |

Full numbers: `reports/phase1_positive_count.csv`. All 7 tests still pass.

## 7. Decisions and trade-offs
- **Primary candidate: South Pass - Granite Mountains** (most positives; contains the Gas Hills area, a historic uranium district - to be confirmed against the survey extent). Backup: Shirley Mountains - Hartville.
- Sierra Madre - Medicine Bow dropped for the pilot (94 positives < gate).
- Source of occurrences: MRDS (frozen 2022 snapshot), not USMIN, because MRDS is directly downloadable and has many more uranium points. USMIN to be checked as a quality cross-check.

## 8. Known limitations / open items
- Boxes are approximate; the real survey footprints must replace them in Phase 2 and the count re-run.
- MRDS positional accuracy and age are unknown; some points may sit on mine offices or be rounded.
- Positives from a historic mining district are spatially clustered, so spatial-fold balance (>=20 per fold) must be checked in Phase 5 and may force fewer, larger blocks.
- Problem statement and metrics written here in brief; the formal metric definitions are fixed in Phase 8 before test results are seen.

## 9. How to reproduce
```powershell
.\.venv\Scripts\Activate.ps1
python scripts/run_pipeline.py
type reports\phase1_positive_count.csv
```
