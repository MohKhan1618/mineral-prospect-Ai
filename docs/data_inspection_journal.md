# Data inspection journal (Phase 3)

Honest attribution is the point of this file. Every line says **who** did it and **with which tool**, so you can say in an interview exactly
what you did yourself and what the pipeline or Claude did. Do not claim more than the "You" lines. Items marked **TO DO (you)** are
things to do in the learning pass so the journal becomes fully yours.

## Who did what
| Step | Tool | Who |
|---|---|---|
| Downloaded the survey zip, report PDF, footprint, extracted with Explorer | Browser, Explorer | You |
| Opened `U_FIN.grd`, hovered values, read the Colour Tool histogram and bin table | Geosoft Viewer 2026.1 | You |
| Exported the 11 grids to COG float GeoTIFF | Geosoft Viewer (Copy/Convert Grid) | You |
| Re-opened the exported `U_FIN.tif`, read its Colour Tool histogram | Geosoft Viewer | You |
| Read the contractor report for units and sensitivities | `pdftotext`, grep | Claude (you should re-read the cited sections) |
| Grid statistics, alignment, signal check, cleaning | Python (rasterio, numpy, geopandas), stages `03_*` | Claude, as code in this repo |
| Inspect MRDS in Jupyter; footprint + MRDS overlay in QGIS | Jupyter, QGIS | **TO DO (you)** |

## Ten questions for each dataset
### 1. MRDS occurrences (`data/raw/occurrences/mrds.csv`)
- **What:** USGS Mineral Resources Data System; 304,632 rows, one per mineral record worldwide; frozen snapshot 2022-08-23.
- **Used for:** positive labels (records naming uranium in commod1/2/3, US only, with coordinates).
- **Valid / sufficient:** 205 unique uranium locations inside the survey footprint (202 on valid grid cells). Enough to try, thin for
  spatial cross-validation (about 40 per fold). Duplicate coordinates exist, so unique locations are counted.
- **What could mislead:** positives are "known occurrences", not proven ore; background is unlabeled, not barren. About 99 records are
  producers / past producers (mine sites). Deposit type is almost entirely empty, so mixed mineral systems share one label. Coordinates may be off.
- **Decision:** use as positives with the above caveats; test with and without mine records.
- **TO DO (you):** open it in Jupyter, run `df.shape`, `df.columns`, read `mrds.met`, filter to uranium, count unique coordinates.

### 2. Survey footprint (`Footprint_...shp`)
- **What:** one polygon, EPSG:32613, 8,703 km2; the outline of the flown area (six blocks A01-A06).
- **Used for:** deciding which points can be used at all (outside it there is no data).
- **TO DO (you):** open it in QGIS together with the MRDS points; see which points fall outside.

### 3. Contractor GeoTIFFs (`GEOTIFFS/`)
- **What:** 3-band uint8 RGB pictures, no nodata. They are colour maps for printing, not measurements.
- **Decision:** discarded. Learned by opening them, not from the file names.

### 4. Radiometric grids (`U_FIN`, `TH_FIN`, `K_FIN`, `TC_FIN`)
- **What:** airborne gamma-ray spectrometry; fully corrected counts per second (report, section on grids); sensitivities U 10.4 cps/ppm,
  Th 6.2 cps/ppm, K 99.5 cps/%; 50 m cells, EPSG:32613, 1707 x 3986 cells, about 50.75 % of the rectangle is data.
- **Range (U_FIN):** min -8.9, median 15.8, p99 43.8, p99.9 70.8, max 872; right-skewed. Median is about 1.5 ppm eU.
- **Nulls:** dummy value outside the survey outline; stored as -999999 in the TIF.
- **Outliers:** 0.05 % negative values (noise); the high tail is clustered, not isolated cells.
- **Limitations:** sees only the top 30-50 cm; wet soil and water lower counts; 200 m flight lines; leveling between blocks.
- **You saw:** the map, the colour scale equalised by rank (so colours mean rank, not size), the hover values, the histogram spike with a long right tail.

### 5. Smoothed grids (`*_s`)
- Values -0.7 to 1.0, not in the report. Excluded until explained. **TO DO (you):** ask the data authors or find the metadata.

### 6. Magnetic grids (`RTP`, `Mag_IGRF`, `VD`)
- **What:** `RTP` and `Mag_IGRF` are total field in nT (median about 52,400 nT, the Earth's field, not removed); `VD` is the vertical
  derivative in nT/m, centred on zero.
- **Outliers:** one compact block of 2,121 cells above 60,000 nT centred at about -108.736, 42.553. MRDS lists the Atlantic City Iron Mine
  and ore plant within 1.5 km, so this is an iron-formation / iron-mine anomaly (real geology plus mining), and its uranium is low (median 9 cps vs 15.8).
- **Signal:** weak alone (AUC 0.55 to 0.60).

## Findings that matter for the model
1. Radiometrics separate known occurrences from background (AUC 0.75 to 0.84); magnetics weakly.
2. Total count and thorium work as well as uranium, and U/Th is weak: the signal may be "radioactive granite", not uranium specifically.
3. Mine records score higher than other occurrences.
4. The data is sufficient for a ranking pilot, not for a discovery claim.
