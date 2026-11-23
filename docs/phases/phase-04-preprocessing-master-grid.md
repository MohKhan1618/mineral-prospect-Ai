# Phase 4 - Preprocessing and master grid

Status: done   Date: 2026-11-21   Gate G3: PASS (processed grids aligned and clean)

## 1. What we did
- Fixed the study area: the South Pass-Granite Mountains survey footprint. **Master grid = the survey grid** (EPSG:32613, 50 m, 1707 x 3986 cells).
- Collected the two remaining layers (Phase 2 leftovers): **terrain** (SRTM 1 arc-second tiles N42W110/109/108/107, public domain, AWS open terrain tiles) and
  **geology** (USGS State Geologic Map Compilation, Wyoming, CC0, shapefile + CSV from mrdata.usgs.gov). Both downloads are resumable, checksummed and in `MANIFEST.json`.
- `04_dem`: resampled terrain onto the master grid (**average** resampling because 30 m is shrinking to 50 m).
- `04_geology`: rasterised polygons onto the master grid: `geology_class.tif` (13 generalised lithology classes), `geology_unit.tif` (66 map units),
  `geology_legend.csv` (codes to names/ages). 0 = unmapped (none inside the survey).
- `04_master_mask`: 3,452,181 cells valid in every layer.
- `04_validate_alignment`: all 11 layers share shape, transform and CRS; no values outside the mask; no gaps inside it. 19 tests pass.

## 2. What it does
Input: cleaned grids (Phase 3), SRTM tiles, SGMC shapefile. Output: `data/processed/{dem,geology_class,geology_unit,master_mask}.tif` + cleaned grids in `data/interim/clean/`.
Everything now stacks cell for cell: one row of features per cell.

## 3. Why it was necessary
Layers come from different CRSs and resolutions. Stacking unaligned grids shifts pixels silently, so a feature would describe the wrong place and a model would learn
noise. This phase makes alignment a checked, tested property, not an assumption.

## 4. Concepts learned
- **Resampling:** average for continuous layers when shrinking cells, nearest/rasterise for categories (never interpolate class codes).
- **Master grid and mask:** one common grid and one validity mask for the whole project.
- **CRS vs resolution vs extent** are three separate things that must all match.
- **8 GB RAM:** each 3.45 M-cell float32 layer is about 14 MB, so a full stack fits in memory; we still write atomically and per layer.
- Geology link: lithology is the "source rock" clue, terrain controls erosion, drainage and exposure.

## 5. Challenges and fixes
| Challenge | Fix |
|---|---|
| USGS ScienceBase blocks scripts | Terrain from AWS open data, geology from `mrdata.usgs.gov` (reachable, no bot check) |
| Resampling choice | Average (shrinking), documented in decisions |
| A shell quoting error while editing the pipeline wrote nothing | Re-did the edit with proper file edits; verified by running |

## 6. Results
- `reports/phase4_alignment_report.json`: DEM 1,746 to 3,171 m (mean 2,126 m); geology 13 classes, 66 units, 0 % unmapped.
- Sanity check: DEM at the Atlantic City Iron Mine is 2,537 m (plausible for a hillside mine near the town; not checked against a survey).

### Geology vs known occurrences (class level)
| Class | share of area | share of positives | lift |
|---|---|---|---|
| Sedimentary, clastic | 65.6 % | 82.7 % | 1.26 |
| Igneous, intrusive | 10.7 % | 7.4 % | 0.69 |
| Unconsolidated | 10.4 % | 5.9 % | 0.57 |
| others | 13 % | 4 % | below 0.9 |

## 7. Decisions
Master grid is the survey grid; average resampling for terrain; geology as class codes plus unit codes (legend saved); mask = intersection of all layers.

## 8. Limitations and red flags
1. **🚩 My earlier "radioactive granite" worry is not supported.** Intrusive rocks (granite) hold fewer occurrences than their share of area (lift 0.69). 83 % of occurrences are on
   clastic sedimentary rock (sandstone), which fits sandstone-hosted (roll-front-type) uranium. So the radiometric signal is more likely "radioactive sandstone". But clastic
   rock covers 66 % of the area, so the class alone is weak (lift 1.26); unit-level geology (66 units) may say more.
2. **🚩 Geology is a map, not measurement**: 1:500,000-scale compilation, polygons are generalised; boundaries may be off by kilometres. Treat as a coarse clue.
3. **🚩 Wide, weak classes**: 13 classes, 3 hold almost all area. Risk of the model learning "clastic = positive".
4. **Terrain is SRTM (about 2000 data)**: elevation only; slope and roughness come in Phase 6. The `master_mask` includes DEM validity.
5. Faults (SGMC structure shapefile) not yet used: planned for Phase 6 (distance to faults).
6. Carried from earlier phases: 205 positives (about half mine records), optimistic bootstrap intervals, `_s` grids excluded.

## 9. How to reproduce
```powershell
.\.venv\Scripts\python.exe scriptsun_pipeline.py
```
