"""Phase 3: does any single layer separate known uranium occurrences from the background?

For one layer we ask: if we pick a known occurrence and a random surveyed cell, how often is the
occurrence's value the higher one? That probability is the ROC-AUC of using the raw layer as a score
(0.5 = no signal, 1.0 = perfect, below 0.5 = occurrences sit on LOWER values).

Caveats built into the numbers (read them as such):
- Background cells are "unlabeled", not proven barren (positive-unlabeled setting).
- Occurrences cluster, so the bootstrap interval is too narrow; treat it as optimistic.
- Each point is matched to the nearest 50 m cell; MRDS coordinates can be off by more than that.
"""
from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio

from .grids import layer_path
from .occurrences import load_uranium
from .runner import atomic_write

BASE_LAYERS = ["U_FIN", "TH_FIN", "K_FIN", "TC_FIN", "RTP", "Mag_IGRF", "VD"]
MIN_DENOM_CPS = 1.0  # ratios are only defined where the denominator is clearly positive
PRODUCER_STATUS = ["Producer", "Past Producer"]


def positives_in_footprint(mrds_csv: Path, footprint_shp: Path) -> gpd.GeoDataFrame:
    """Unique uranium locations inside the survey footprint, in the survey CRS (EPSG:32613)."""
    fp = gpd.read_file(footprint_shp).to_crs(4326).union_all()
    u = load_uranium(mrds_csv).drop_duplicates(["latitude", "longitude"])
    g = gpd.GeoDataFrame(u, geometry=gpd.points_from_xy(u.longitude, u.latitude), crs=4326)
    return g[g.within(fp)].to_crs(32613).reset_index(drop=True)


def read_layer(path: Path) -> tuple[np.ndarray, rasterio.Affine]:
    """Return a float32 array with NaN where the grid has no data."""
    with rasterio.open(path) as r:
        a = r.read(1, masked=True).astype("float32").filled(np.nan)
        return a, r.transform


def sample_cells(arr: np.ndarray, transform: rasterio.Affine, xs, ys) -> np.ndarray:
    """Nearest-cell value at each coordinate, NaN if outside the grid or on a no-data cell."""
    inv = ~transform
    cols, rows = inv * (np.asarray(xs), np.asarray(ys))
    cols = np.floor(cols).astype(int)
    rows = np.floor(rows).astype(int)
    ok = (rows >= 0) & (rows < arr.shape[0]) & (cols >= 0) & (cols < arr.shape[1])
    out = np.full(len(rows), np.nan, dtype="float64")
    out[ok] = arr[rows[ok], cols[ok]]
    return out


def auc_vs_background(pos: np.ndarray, background_sorted: np.ndarray) -> float:
    """P(background < positive) + 0.5 P(tie): the mean percentile of positives in the background."""
    pos = pos[~np.isnan(pos)]
    lo = np.searchsorted(background_sorted, pos, side="left")
    hi = np.searchsorted(background_sorted, pos, side="right")
    return float(np.mean((lo + hi) / 2 / background_sorted.size))


def bootstrap_ci(pos: np.ndarray, background_sorted: np.ndarray, n: int = 1000, seed: int = 42):
    pos = pos[~np.isnan(pos)]
    rng = np.random.default_rng(seed)
    vals = [auc_vs_background(rng.choice(pos, size=pos.size, replace=True), background_sorted) for _ in range(n)]
    return float(np.percentile(vals, 2.5)), float(np.percentile(vals, 97.5))


def _layer_arrays(survey_dir: Path) -> tuple[dict[str, np.ndarray], rasterio.Affine]:
    arrays: dict[str, np.ndarray] = {}
    transform = None
    for name in BASE_LAYERS:
        arrays[name], transform = read_layer(layer_path(survey_dir, name))
    u, th, k = arrays["U_FIN"], arrays["TH_FIN"], arrays["K_FIN"]
    with np.errstate(divide="ignore", invalid="ignore"):
        arrays["U_over_TH"] = np.where(th > MIN_DENOM_CPS, u / th, np.nan).astype("float32")
        arrays["U_over_K"] = np.where(k > MIN_DENOM_CPS, u / k, np.nan).astype("float32")
    return arrays, transform


def signal_table(survey_dir: Path, pos: gpd.GeoDataFrame) -> pd.DataFrame:
    arrays, transform = _layer_arrays(survey_dir)
    xs, ys = pos.geometry.x.values, pos.geometry.y.values
    is_prod = pos.dev_stat.isin(PRODUCER_STATUS).values
    rows = []
    for name, arr in arrays.items():
        bg = np.sort(arr[~np.isnan(arr)].astype("float64"))
        v = sample_cells(arr, transform, xs, ys)
        ok = ~np.isnan(v)
        row = {
            "layer": name, "n_positives_total": len(pos), "n_positives_on_valid_cell": int(ok.sum()),
            "median_positives": float(np.nanmedian(v)), "median_background": float(np.median(bg)),
            "auc_all": auc_vs_background(v, bg),
        }
        row["auc_ci_low"], row["auc_ci_high"] = bootstrap_ci(v, bg)
        for tag, mask in (("producers", is_prod), ("non_producers", ~is_prod)):
            vv = v[mask]
            row[f"n_{tag}"] = int((~np.isnan(vv)).sum())
            row[f"auc_{tag}"] = auc_vs_background(vv, bg) if (~np.isnan(vv)).sum() else np.nan
        rows.append(row)
    return pd.DataFrame(rows).sort_values("auc_all", ascending=False).reset_index(drop=True)


def write_table(df: pd.DataFrame, out: Path) -> None:
    with atomic_write(out, "w") as fh:
        df.to_csv(fh, index=False)
