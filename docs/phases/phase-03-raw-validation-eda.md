# Phase 3 - Raw validation and EDA

Status: done   Date: 2026-11-21   Gate: PASS (see gate review)

## 1. What we did so far
- Converted the Geosoft `.grd` grids to COG GeoTIFF Floating Point with the free Geosoft Viewer 2026.1 (user, by hand).
  Output: `radiometrics/CONVERTED/` (8 grids) and `magnetics/CONVERTED/` (3 grids).
- New stage `03_grid_inventory` (`src/mpm/grids.py`): opens all 11 grids, rejects anything that is not
  1-band float32, rejects grids that do not share shape/cell size/origin/CRS, writes
  `reports/phase3_grid_inventory.csv` and registers each file's SHA-256 in `data/raw/MANIFEST.json`.
- Read the contractor report to settle units and meaning (answers below).

## 2. Findings from the contractor report
- `U_FIN`, `TH_FIN`, `K_FIN`, `TC_FIN` are **counts per second**, fully corrected and microlevelled. They are NOT ppm.
  The ppm / % concentration channels exist only in the `.gdb` databases. Sensitivities (report Table 6-16):
  K 99.5 cps per %, U 10.4 cps per ppm, Th 6.2 cps per ppm, so eU ppm is about U_FIN / 10.4.
  Median U_FIN 15.8 cps is about 1.5 ppm eU.
- Cell size 50 m (report section 7.5), grid 1707 x 3986, EPSG:32613.
- `RTP` and `Mag_IGRF` are total-field values (median about 52,400 nT), regional field NOT removed. `VD` is nT/m, centred on zero.
- The `_s` grids are not mentioned in the report's deliverables list.

## 3. Concepts
- Counts vs concentration (instrument response vs estimated ground content); null (dummy) values; right-skewed
  distributions and what the tail means; histogram equalisation colours show rank, not size; UTM and projected CRS.

## 4. Challenges
| Challenge | How solved |
|---|---|
| `.grd` unreadable by GDAL | Geosoft Viewer export to COG float GeoTIFF |
| Export saved to a different folder than requested | Kept it, pipeline points there |
| File named Mag_IRGF (typo) | Renamed to Mag_IGRF |
| Assumed ppm (my error, and user's median 17 contradicted it) | Report says counts/sec |
| Earlier I said Mag_IGRF had the regional field removed (my error) | Values show it has not |

## 5. Results
`reports/phase3_grid_inventory.csv`: all 11 layers aligned, 3,452,988 valid cells (50.75 % of the rectangle) in radiometrics.

## 6. Known limitations / open items
### Red flags
1. **`_s` grids undocumented**, values -0.7..1.0 (look normalised). Excluded from use until explained.
2. **U_FIN export vs Viewer: bulk agrees, extreme tail unresolved (downgraded).** The Viewer's Colour Tool on the exported TIF
   (39 equal-count bins, user screenshots 2026-11-21) matches the script: first bin edge 7.413 is the 2.2 % quantile (script) vs
   2.56 % expected; 36.558 is the 97.5 % quantile (97.4 % expected); histogram axis end 55.687 is the 99.7th percentile. Min -8.917
   (Viewer) vs -8.886 (script) differ by 0.03. Only the maximum is unreconciled: the .grd screen showed 1564, the TIF has max 872
   (2 cells above 800 of 3.45 million). Treated as a spike either way; clipped later. Optional close-out: Linear distribution on the TIF.
3. **Negative values in every radiometric grid** (physically impossible; noise). Needs a cleaning rule.
4. **Regional field still in RTP / Mag_IGRF**. Needs removal or a high-pass step before scale-sensitive models.
5. **Extreme spikes**: U max 872 cps (about 84 ppm), TC max 16,243, magnetics +28,000 nT. Real or cultural? Check location.
6. **Valid cell counts differ slightly** between magnetics (3,452,996 / VD 3,453,349) and radiometrics (3,452,988). Use cells valid in all layers.
7. Gamma rays see only the top 30-50 cm; buried uranium is invisible.
Plus the Phase 2 flags (188 positives, mine records dominate, deposit type missing).

### Signal check (stage `03_signal_check`, `reports/phase3_signal_check.csv`)
205 unique uranium locations inside the real footprint (not 188: the earlier ad hoc check used the Phase 1 box and missed 17 east of -107.4);
202 fall on valid cells (85 past producers + 14 producers = about 99 mine records). Single-layer AUC vs all surveyed cells
(0.5 = no signal), bootstrap 95 % interval, producers vs non-producers:

| Layer | AUC all | 95 % CI | AUC producers | AUC non-producers |
|---|---|---|---|---|
| TC_FIN | 0.842 | 0.810-0.870 | 0.901 | 0.787 |
| U_FIN | 0.835 | 0.802-0.866 | 0.882 | 0.791 |
| TH_FIN | 0.813 | 0.783-0.840 | 0.867 | 0.763 |
| U/K | 0.780 | 0.742-0.819 | 0.824 | 0.740 |
| K_FIN | 0.745 | 0.707-0.779 | 0.819 | 0.677 |
| U/TH | 0.601 | 0.558-0.647 | 0.676 | 0.532 |
| Mag_IGRF | 0.596 | 0.567-0.624 | 0.588 | 0.603 |
| VD | 0.587 | 0.557-0.620 | 0.584 | 0.591 |
| RTP | 0.549 | 0.523-0.575 | 0.560 | 0.539 |

Reading: radiometrics carry real signal; the magnetics are weak alone. Total count and thorium separate occurrences as well as uranium does, and
U/Th is weak, so occurrences sit on generally radioactive (probably granitic, Th-rich) ground rather than on uranium-enriched-relative-to-thorium ground.

### Red flags from the signal check
8. **(Revised in Phase 4, see there.) Signal may be generic radioactivity, not uranium specifically** (TC and Th AUC >= U; U/Th only 0.60). Model must be tested on non-mine, spatially held-out data.
9. **Producers score higher than other occurrences** (0.88 vs 0.79 for U): mine disturbance or higher-grade sites may inflate the signal; labels must be tested with and without mine records.
10. **Bootstrap intervals are optimistic**: occurrences cluster. Real uncertainty comes from spatial cross-validation (Phase 5/8).
11. **Whole-survey background**: high AUC may partly reflect that occurrences lie in one part of the survey (regional trend). Spatial CV will test this.

### Cleaning rules (stage `03_clean`, `src/mpm/clean.py`, log `reports/phase3_cleaning_log.json`, output `data/interim/clean/`)
Each rule comes from a measurement:
| Rule | Evidence | Action |
|---|---|---|
| R1 common valid mask | 3,452,181 cells valid in all 7 layers; 807 radiometric and 815-1,168 magnetic cells are valid only in some | keep only the common cells |
| R2 negative counts | only 0.047 % (U), 0.056 % (Th), 0.004 % (K, TC) of cells; impossible physically | set to 0 |
| R3 spikes | top cells are NOT isolated (0 of 346 cells above the 99.99th percentile of U are single-cell noise); they are connected clusters | cap (winsorise) at the 99.9th percentile, do not delete (U cap 70.8 cps) |
| R4 magnetic regional offset | median 52,383 nT; a tilted plane explains only 0.4 % of variance | subtract the median, no detrending |
| R5 `_s` grids | undocumented | not used |
Verification: the signal-check AUC is identical before and after cleaning for all 7 layers (ranks are preserved), so the cleaning did not
change the information, only the scale and outliers. 16 unit tests pass.

Red flag 4 (regional field) is downgraded: it is a constant offset, not a trend.
Red flag 5 refined: the largest magnetic anomaly is one compact block (2,121 cells above 60,000 nT, about 4.6 x 2.8 km). Its location and cause (Precambrian iron
formation near the old South Pass / Atlantic City iron workings? or cultural) are not yet checked; to do with QGIS.

### Magnetic anomaly resolved
Centre -108.736, 42.553; MRDS has the **Atlantic City Iron Mine** (42.541, -108.745, past producer) and **Atlantic City Ore Operations Plant** within about 1.5 km.
So it is an iron-formation / iron-mine anomaly (real geology and mining). Uranium inside it is low (median 9 cps vs 15.8). Kept, capped by R3.

## Gate review (Claude, 2026-11-21)
| Gate condition | Result |
|---|---|
| All needed layers readable by code, one grid, checksummed | PASS (11 layers, `03_grid_inventory`, manifest) |
| Units and meaning of each layer known from the source | PASS for 7 layers; `_s` grids unexplained and excluded |
| Layers carry some signal against known occurrences | PASS (radiometrics AUC 0.75 to 0.84) |
| Cleaning rules defined, justified by evidence, implemented, tested | PASS (R1 to R5, 16 tests) |
| Inspection documented with honest attribution | PASS, see `docs/data_inspection_journal.md` (MRDS and QGIS items are marked TO DO for the user) |
Carried forward: positives are thin (205) and mine-heavy; signal may be generic radioactivity; `_s` grids; CI optimism (clustering).
**Phase 3 closed. Proceed to Phase 4 (master grid / preprocessing).**

## 7. How to reproduce
```powershell
.\.venv\Scripts\python.exe scripts\run_pipeline.py
```
Needs the manual Geosoft Viewer exports in the two `CONVERTED` folders.
