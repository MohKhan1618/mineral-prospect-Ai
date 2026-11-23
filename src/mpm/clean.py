"""Phase 3: cleaning rules, derived from measurements in reports/phase3_grid_inventory.csv.

Rules (each justified by the numbers in docs/phases/phase-03-raw-validation-eda.md):
  R1  Common valid mask: keep only cells valid in ALL layers (about 800 edge cells dropped).
  R2  Radiometric counts cannot be negative (0.004 to 0.06 % of cells, counting noise): set to 0.
  R3  Winsorise every layer at its 0.1 / 99.9 percentile (computed on the common mask). Extreme cells are
      NOT isolated single-cell noise (none of the top cells are isolated), so they are capped, not deleted.
      Radiometric counts use only the upper cap (lower bound is 0 from R2).
  R4  Magnetics RTP and Mag_IGRF: subtract the median (remove the ~52,400 nT regional offset). A tilted plane
      explains only 0.4 % of the variance, so no detrending is applied.
  R5  The undocumented `_s` grids are not used.
Raw files are never modified; cleaned grids go to data/interim/clean/.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import numpy as np
import rasterio

from .grids import layer_path
from .runner import atomic_write

RADIOMETRIC = ["U_FIN", "TH_FIN", "K_FIN", "TC_FIN"]
MAGNETIC_CENTRED = ["RTP", "Mag_IGRF"]
MAGNETIC_OTHER = ["VD"]
LAYERS = RADIOMETRIC + MAGNETIC_CENTRED + MAGNETIC_OTHER
LOW_Q, HIGH_Q = 0.1, 99.9
NODATA = -999999.0


def clean_array(name: str, arr: np.ndarray, mask: np.ndarray) -> tuple[np.ndarray, dict]:
    """Apply R2-R4 to one layer. `arr` has NaN for no data; returns a NaN-outside-mask array and a log."""
    out = np.where(mask, arr, np.nan).astype("float32")
    v = out[mask]
    log: dict = {"n_cells": int(mask.sum())}
    if name in RADIOMETRIC:
        log["n_negative_set_to_zero"] = int((v < 0).sum())
        out = np.where(mask, np.maximum(out, 0), np.nan).astype("float32")
        v = out[mask]
        hi = float(np.percentile(v, HIGH_Q))
        log["cap_high"] = hi
        log["n_capped_high"] = int((v > hi).sum())
        out = np.where(mask, np.minimum(out, hi), np.nan).astype("float32")
    else:
        if name in MAGNETIC_CENTRED:
            med = float(np.median(v))
            log["median_subtracted"] = med
            out = (out - med).astype("float32")
            v = out[mask]
        lo, hi = (float(x) for x in np.percentile(v, [LOW_Q, HIGH_Q]))
        log.update(cap_low=lo, cap_high=hi, n_capped_low=int((v < lo).sum()), n_capped_high=int((v > hi).sum()))
        out = np.where(mask, np.clip(out, lo, hi), np.nan).astype("float32")
    return out, log


def common_mask(arrays: dict[str, np.ndarray]) -> np.ndarray:
    return np.logical_and.reduce([~np.isnan(a) for a in arrays.values()])


def write_float_tif(path: Path, arr: np.ndarray, profile: dict) -> None:
    """Atomic GeoTIFF write: temp file, then rename."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    prof = {**profile, "driver": "GTiff", "dtype": "float32", "count": 1, "nodata": NODATA,
            "compress": "deflate", "tiled": True, "blockxsize": 256, "blockysize": 256}
    prof.pop("photometric", None)
    with rasterio.open(tmp, "w", **prof) as dst:
        dst.write(np.where(np.isnan(arr), NODATA, arr).astype("float32"), 1)
    os.replace(tmp, path)


def run_cleaning(survey_dir: Path, out_dir: Path, report: Path) -> dict:
    raw, profile = {}, None
    for n in LAYERS:
        with rasterio.open(layer_path(survey_dir, n)) as r:
            raw[n] = r.read(1, masked=True).astype("float32").filled(np.nan)
            profile = r.profile
    mask = common_mask(raw)
    log = {"common_valid_cells": int(mask.sum()),
           "dropped_vs_each_layer": {n: int((~np.isnan(a)).sum() - mask.sum()) for n, a in raw.items()},
           "layers": {}}
    for n in LAYERS:
        cleaned, info = clean_array(n, raw[n], mask)
        write_float_tif(Path(out_dir) / f"{n}.tif", cleaned, profile)
        log["layers"][n] = info
    with atomic_write(report, "w") as fh:
        json.dump(log, fh, indent=2)
    return log
