# Phase 2 - Data collection

Status: in progress (survey data in hand, real values not yet readable)   Date: 2026-11-20
Gate: raw files present and checksummed (PASS); usable numeric layers readable by code (OPEN, see red flags).

## 1. What we did
- Downloaded the USGS Earth MRI airborne radiometric + magnetic survey for South Pass-Granite Mountains, WY
  (doi:10.5066/P13W5Y9W): contractor deliverables zip (3.08 GB), contractor report PDF, footprint zip.
  Downloaded by the user in a browser because scripts get HTTP 403 / a bot check from USGS.
- Extracted the zips with Windows Explorer (Python cannot read their compression, see challenges).
- Registered the three files with SHA-256 checksums in `data/raw/MANIFEST.json` (stage `02_register_south_pass`).
- Replaced the extraction stage with `02_verify_south_pass_files`, which checks that the 8 radiometric grids,
  3 magnetic grids, their `.xml` metadata, the survey JSON and the 4 footprint shapefile parts exist and are
  non-empty, then writes `_EXTRACT_VERIFIED.json` with file sizes.
- Re-counted positives inside the real footprint polygon (see red flags).

## 2. What it does
Input: manual downloads in `data/raw/radiometrics_magnetics/south_pass/`. Output: a verified, checksummed raw
data folder. Everything downstream reads from here and never modifies it.

## 3. Why it was necessary
No model is better than its data. This phase fixes exactly which files the project stands on and proves they
arrived intact, so a crash or a re-download can never silently change the inputs.

## 4. Concepts learned
- **Raster vs vector vs table**: grids of values (radiometrics), shapes (footprint), rows (MRDS).
- **Shapefile = several files** (.shp .shx .dbf .prj); one alone is unusable.
- **Picture vs data**: a GeoTIFF can be a coloured image (3 bands of 0-255) rather than measurements.
  Geology link: a colour map of uranium counts is not the counts.
- **Provenance + checksum**: where a file came from and a fingerprint proving it is unchanged.

## 5. Challenges faced and how we solved them
| Challenge | Impact | How we solved it |
|---|---|---|
| USGS ScienceBase / usgs.gov return 403 and a bot check to scripts | Could not automate download | Did not bypass the check; user downloaded in their own browser; files then registered by checksum |
| Zips use Deflate64 compression; Python `zipfile` raises NotImplementedError; `zipfile-deflate64` needs a C compiler | Automated extraction impossible | User extracted with Explorer; pipeline now verifies files instead of extracting |
| Extraction landed beside the zips, not in `extracted/`, and 37 members (shapefiles, report PDF copy) were skipped | Old stage would never pass | Stage rewritten to check only the files we need |
| I (Claude) assumed the "GEOTIFFS" folder held data layers from file names alone | Wrong plan until opened | Inspected: they are 3-band uint8 RGB pictures. Lesson: open before you trust |

## 6. Results and evidence
- Pipeline run: `02_verify_south_pass_files` DONE; 7 unit tests pass.
- Survey CRS EPSG:32613 (UTM 13N); grid extent lon -109.158 to -106.703, lat 42.010 to 42.839 (from `.grd.xml`).
- Footprint: 1 polygon, about 8,703 km2.

## 7. Decisions and trade-offs
- Use the Geosoft `.grd` grids as the data source, NOT the contractor GeoTIFFs (pictures). Needs conversion.
- Skip the 2.9 GB `.gdb` databases (flight-line data) for now; revisit only if grid conversion fails.
- Verify rather than extract in code.

## 8. Known limitations / open items
### 🚩 Red flags
1. **Positive count was inflated (535 vs about 205).** [Corrected in Phase 3: the true count is 205; the first check used a box that cut off the east of the survey, giving 188.] The Phase 1 gate used an approximate box that extends beyond
   the survey. Only 188 unique uranium locations fall inside the real footprint (84 past producer, 14 producer,
   43 occurrence, 28 prospect, 19 unknown). Still above the gate of 100, but the margin is thin: with 5 spatial
   folds that is about 37 positives per fold on average, and clustering will make some folds much lower.
   Recommendation: treat this as the true count from now on; plan Phase 5 around it (fewer folds or larger
   blocks, repeated CV, report wide confidence intervals).
2. **Mine records dominate the positives.** 98 of 188 are producers or past producers. Their coordinates sit on
   mine workings, and mining disturbs the surface that radiometrics measure. The model may learn "looks like a
   mine" rather than "looks like favourable geology". To be tested in Phase 5/8.
3. **Deposit type is almost entirely missing.** 185 of 188 `dep_type` values are empty, so we cannot separate
   roll-front from other types. One label will mix different mineral systems.
4. **The `.grd` real-value grids cannot be opened by GDAL/rasterio.** Until converted, we have no usable
   radiometric or magnetic numbers. This blocks Phase 3 onward.
5. **Size mismatch to understand.** A `.grd` uranium grid is about 12 MB while the RGB picture of the same area
   is about 168 MB. Geosoft grids can be compressed, but we must confirm the grid's true cell size and
   dimensions before trusting it.
6. **Survey and MRDS dates differ.** Survey flown 2023; MRDS frozen 2022. Newer discoveries are absent.
7. **Licence terms not yet confirmed** on the source page for either dataset.

Other open items: DEM source, SGMC geology download (also bot-protected), optional USMIN cross-check, a proper
pipeline stage that saves the in-footprint positive count (currently computed ad hoc, saved here only).

## 9. How to reproduce
```powershell
.\.venv\Scripts\python.exe scripts\run_pipeline.py
```
The manual downloads and Explorer extraction must be present first (see section 1).
