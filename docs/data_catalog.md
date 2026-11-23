# Data catalog

Status key: have = downloaded and registered; planned = source identified, not downloaded; unverified = needs checking.

| Dataset | Use | Source | Format | License | Status |
|---|---|---|---|---|---|
| MRDS mineral records (uranium subset) | Positive labels | https://mrdata.usgs.gov/mrds/mrds-csv.zip (snapshot 2022-08-23) | CSV, 25.8 MB zip | USGS, verify on source page | have |
| Radiometrics eU/eTh/K + magnetics, South Pass-Granite Mtns (Earth MRI) | Features | USGS data release doi:10.5066/P13W5Y9W | Geosoft .grd (real values, needs conversion); GeoTIFFs are RGB pictures | USGS data release, verify | have (3.08 GB zip, report PDF, footprint); values not yet readable |
| Same, Shirley Mtns-Hartville | Backup region | doi:10.5066/P1C7TJKK | GeoTIFF | verify | planned |
| State Geologic Map Compilation (SGMC), Wyoming | Lithology, faults | https://mrdata.usgs.gov/geology/state/shp/WY.zip (doi:10.5066/F7WH2N65) | shapefile + CSV | CC0 1.0 | have |
| DEM: SRTM 1 arc-second tiles N42W107-N42W110 | Terrain | AWS open data terrain tiles (skadi) | .hgt, about 30 m | public domain (verify) | have |
| USMIN deposit database | Cross-check of occurrences | https://www.usgs.gov/centers/gggsc/science/usmin-mineral-deposit-database | not confirmed | verify | unverified |

Checksums and download dates for everything marked "have" are in `data/raw/MANIFEST.json`.
