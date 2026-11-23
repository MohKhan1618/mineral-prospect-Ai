"""Phase 6: feature engineering. Every feature is a pure function of the input maps, never of the labels,
so nothing here can leak positives into the model. (Scaling/imputation is fitted on training folds in Phase 7.)

Output layout (all in data/features/), over the valid cells of the master mask only:
  features.npy        float32, shape (n_features, n_valid_cells)   feature-major, one row per feature
  cell_index.npy      int32,   shape (2, n_valid_cells)            [row, col] of each valid cell
  feature_catalog.json name, group, geological meaning, for every feature (same order as features.npy)

Radiometric units are counts/sec (see grids.py). `EPS_CPS` is added to numerator and denominator of ratios
so they are defined where thorium or potassium is 0 (cleaning set negatives to 0).
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from rasterio import features as rfeatures
from rasterio.transform import Affine
from scipy import ndimage as ndi

from .clean import LAYERS as CLEAN_LAYERS
from .runner import atomic_write
from .signal import auc_vs_background

EPS_CPS = 1.0
WIN_1KM, WIN_5KM, WIN_TERRAIN = 21, 101, 5      # window sizes in 50 m cells
FAULT_PAD_CELLS = 400                            # faults up to 20 km outside the survey still count
FAULT_WORDS = ("fault", "shear zone")


# ---------- small numeric helpers (tested) ----------
def fill_nearest(a: np.ndarray) -> np.ndarray:
    """Replace NaN by the nearest valid value, so gradients near edges are not NaN."""
    bad = np.isnan(a)
    if not bad.any():
        return a
    idx = ndi.distance_transform_edt(bad, return_distances=False, return_indices=True)
    return a[tuple(idx)]


def masked_mean_std(a: np.ndarray, mask: np.ndarray, size: int) -> tuple[np.ndarray, np.ndarray]:
    """Mean and std over a size x size window, using only cells inside the mask."""
    m = mask.astype("float64")
    x = np.where(mask, a, 0.0).astype("float64")
    n = ndi.uniform_filter(m, size, mode="constant")
    s = ndi.uniform_filter(x, size, mode="constant")
    s2 = ndi.uniform_filter(x * x, size, mode="constant")
    with np.errstate(divide="ignore", invalid="ignore"):
        mean = s / n
        var = np.maximum(s2 / n - mean**2, 0.0)
    return mean.astype("float32"), np.sqrt(var).astype("float32")


def slope_degrees(dem: np.ndarray, cell_m: float) -> np.ndarray:
    gy, gx = np.gradient(fill_nearest(dem).astype("float64"), cell_m)
    return np.degrees(np.arctan(np.hypot(gx, gy))).astype("float32")


def horizontal_gradient(a: np.ndarray, cell_m: float) -> tuple[np.ndarray, np.ndarray]:
    gy, gx = np.gradient(fill_nearest(a).astype("float64"), cell_m)
    return gx, gy


def log_ratio(num: np.ndarray, den: np.ndarray, eps: float = EPS_CPS) -> np.ndarray:
    return np.log((num + eps) / (den + eps)).astype("float32")


def distance_to_lines(line_mask: np.ndarray, cell_m: float) -> np.ndarray:
    """Distance in metres from every cell to the nearest True cell."""
    return ndi.distance_transform_edt(~line_mask, sampling=cell_m).astype("float32")


def contact_mask(cls: np.ndarray) -> np.ndarray:
    """True on cells whose mapped class differs from the cell to the right or below (unmapped 0 ignored)."""
    c = cls.astype("int32")
    edge = np.zeros(c.shape, dtype=bool)
    d = (c[:, :-1] != c[:, 1:]) & (c[:, :-1] > 0) & (c[:, 1:] > 0)
    edge[:, :-1] |= d
    edge[:, 1:] |= d
    d = (c[:-1, :] != c[1:, :]) & (c[:-1, :] > 0) & (c[1:, :] > 0)
    edge[:-1, :] |= d
    edge[1:, :] |= d
    return edge


# ---------- IO ----------
def _read(path: Path) -> np.ndarray:
    with rasterio.open(path) as r:
        return r.read(1, masked=True).astype("float32").filled(np.nan)


def _fault_rasters(structure_shp: Path, transform: Affine, shape: tuple[int, int], crs, cell_m: float):
    pad = FAULT_PAD_CELLS
    pt = transform @ Affine.translation(-pad, -pad)
    pshape = (shape[0] + 2 * pad, shape[1] + 2 * pad)
    x0, y0 = pt @ (0, pshape[0])
    x1, y1 = pt @ (pshape[1], 0)
    g = gpd.read_file(structure_shp).to_crs(crs)
    g = g[g["DESCRIPT"].fillna("").str.lower().str.contains("|".join(FAULT_WORDS))]
    g = g.cx[x0:x1, y0:y1]
    burned = rfeatures.rasterize(((geom, 1) for geom in g.geometry), out_shape=pshape, transform=pt,
                                 fill=0, dtype="uint8", all_touched=True).astype(bool)
    dist = distance_to_lines(burned, cell_m)
    dens = ndi.uniform_filter(burned.astype("float64"), WIN_5KM, mode="constant")
    sl = (slice(pad, pad + shape[0]), slice(pad, pad + shape[1]))
    # fraction of cells on a fault line x (1000 m / cell_m) ~ km of fault per km2 (all_touched overstates a bit)
    return dist[sl], (dens[sl] * 1000.0 / cell_m).astype("float32"), int(len(g))


def build_features(clean_dir: Path, processed_dir: Path, structure_shp: Path, out_dir: Path) -> dict:
    clean_dir, processed_dir, out_dir = Path(clean_dir), Path(processed_dir), Path(out_dir)
    with rasterio.open(processed_dir / "master_mask.tif") as r:
        mask = r.read(1).astype(bool)
        transform, crs, cell = r.transform, r.crs, abs(r.transform.a)
    rows, cols = np.nonzero(mask)
    cat: list[dict] = []
    cols_data: list[np.ndarray] = []

    def add(name: str, group: str, meaning: str, arr: np.ndarray) -> None:
        cat.append({"name": name, "group": group, "meaning": meaning})
        cols_data.append(np.asarray(arr, dtype="float32")[rows, cols])

    L = {n: _read(clean_dir / f"{n}.tif") for n in CLEAN_LAYERS}
    u, th, k, tc = L["U_FIN"], L["TH_FIN"], L["K_FIN"], L["TC_FIN"]

    # radiometrics: levels, logs (tame the right skew), stabilised log-ratios (Th/K/U relative enrichment)
    for n, a, m in (("U", u, "equivalent uranium counts/s, top ~30-50 cm of ground"),
                    ("TH", th, "equivalent thorium counts/s"), ("K", k, "potassium counts/s"),
                    ("TC", tc, "total gamma counts/s, overall radioactivity")):
        add(f"rad_{n}", "radiometric", m, a)
        add(f"rad_log_{n}", "radiometric", f"log1p of {n}", np.log1p(a))
    add("rad_lr_U_TH", "radiometric", "log((U+1)/(Th+1)); uranium enriched relative to thorium", log_ratio(u, th))
    add("rad_lr_U_K", "radiometric", "log((U+1)/(K+1)); uranium relative to potassium", log_ratio(u, k))
    add("rad_lr_TH_K", "radiometric", "log((Th+1)/(K+1)); separates K-rich granite from Th-rich sediment", log_ratio(th, k))

    # neighbourhood statistics: local context beats a single noisy pixel (and survey data are 50 m cells)
    means5 = {}
    for n, a in (("U", u), ("TH", th), ("K", k)):
        m1, s1 = masked_mean_std(a, mask, WIN_1KM)
        m5, _ = masked_mean_std(a, mask, WIN_5KM)
        means5[n] = m5
        add(f"nbr_{n}_mean_1km", "neighbourhood", f"mean of {n} in 1 km window", m1)
        add(f"nbr_{n}_std_1km", "neighbourhood", f"std of {n} in 1 km window (local variability)", s1)
        add(f"nbr_{n}_mean_5km", "neighbourhood", f"mean of {n} in 5 km window (regional level)", m5)
    add("nbr_U_minus_5km", "neighbourhood", "U minus its 5 km mean: local anomaly against regional level", u - means5["U"])
    add("nbr_lr_U_TH_5km", "neighbourhood", "log-ratio of 5 km mean U to 5 km mean Th", log_ratio(means5["U"], means5["TH"]))

    # magnetics: depth/size of magnetic bodies, edges (faults, dikes, contacts)
    rtp, igrf, vd = L["RTP"], L["Mag_IGRF"], L["VD"]
    gx, gy = horizontal_gradient(rtp, cell)
    add("mag_RTP", "magnetic", "reduced-to-pole total field, median removed (nT)", rtp)
    add("mag_IGRF", "magnetic", "total field, median removed (nT); strongly overlaps RTP", igrf)
    add("mag_VD", "magnetic", "vertical derivative (nT/m): sharpens shallow sources", vd)
    add("mag_hgrad", "magnetic", "horizontal gradient of RTP (nT/m): magnetic edges", np.hypot(gx, gy))
    add("mag_analytic_signal", "magnetic", "sqrt(gx^2+gy^2+VD^2): source-position signal", np.sqrt(gx**2 + gy**2 + fill_nearest(vd) ** 2))
    m1, s1 = masked_mean_std(rtp, mask, WIN_1KM)
    m5, _ = masked_mean_std(rtp, mask, WIN_5KM)
    add("mag_RTP_std_1km", "magnetic", "local variability of RTP in 1 km window", s1)
    add("mag_RTP_mean_5km", "magnetic", "regional magnetic level, 5 km mean of RTP", m5)

    # terrain
    dem = _read(processed_dir / "dem.tif")
    dm = ~np.isnan(dem)
    add("ter_elev", "terrain", "elevation (m), SRTM averaged to 50 m", dem)
    add("ter_slope", "terrain", "slope in degrees: relief and weathering/erosion state", slope_degrees(dem, cell))
    _, sd = masked_mean_std(np.nan_to_num(dem), dm, WIN_TERRAIN)
    add("ter_roughness_250m", "terrain", "std of elevation in 250 m window", sd)
    mm, _ = masked_mean_std(np.nan_to_num(dem), dm, WIN_1KM)
    add("ter_tpi_1km", "terrain", "elevation minus 1 km mean: ridge (+) vs valley (-)", dem - mm)

    # structure
    dist, dens, n_faults = _fault_rasters(structure_shp, transform, mask.shape, crs, cell)
    add("str_dist_fault_m", "structure", "distance to nearest mapped fault or shear zone (m)", dist)
    add("str_fault_density", "structure", "mapped fault length per km2 in 5 km window (approx.)", dens)

    # geology
    with rasterio.open(processed_dir / "geology_class.tif") as r:
        gcls = r.read(1)
    legend = pd.read_csv(processed_dir / "geology_legend.csv")
    legend = legend[legend.kind == "class"]
    for _, row in legend.iterrows():
        nm = re.sub(r"\W+", "_", str(row["label"]).strip().lower()).strip("_")
        add(f"geo_is_{nm}", "geology", f"1 if mapped class is '{row['label']}'", (gcls == int(row["code"])).astype("float32"))
    add("geo_dist_contact_m", "geology", "distance to nearest boundary between mapped rock classes (m)",
        distance_to_lines(contact_mask(gcls), cell))

    X = np.vstack(cols_data)
    if not np.isfinite(X).all():
        bad = {cat[i]["name"]: int((~np.isfinite(X[i])).sum()) for i in range(len(cat)) if not np.isfinite(X[i]).all()}
        raise ValueError(f"non-finite feature values inside the mask: {bad}")

    out_dir.mkdir(parents=True, exist_ok=True)
    for name, arr in (("features.npy", X), ("cell_index.npy", np.vstack([rows, cols]).astype("int32"))):
        tmp = out_dir / (name + ".tmp")
        with open(tmp, "wb") as fh:
            np.save(fh, arr)
        os.replace(tmp, out_dir / name)
    with atomic_write(out_dir / "feature_catalog.json", "w") as fh:
        json.dump(cat, fh, indent=2)
    return {"n_features": len(cat), "n_cells": int(mask.sum()), "n_fault_lines_used": n_faults}


def load_features(features_dir: Path, mmap: bool = True):
    """(X[n_features, n_cells], cell_index[2, n_cells], names) - memory-mapped by default."""
    d = Path(features_dir)
    mode = "r" if mmap else None
    X = np.load(d / "features.npy", mmap_mode=mode)
    idx = np.load(d / "cell_index.npy", mmap_mode=mode)
    names = [c["name"] for c in json.load(open(d / "feature_catalog.json", encoding="utf-8"))]
    return X, idx, names


def feature_report(features_dir: Path, positives_csv: Path, out_report: Path, out_pairs: Path,
                   corr_threshold: float = 0.95, sample: int = 150_000, seed: int = 42) -> pd.DataFrame:
    """Per-feature summary, univariate AUC of each feature against all valid cells, and near-duplicate pairs."""
    X, idx, names = load_features(features_dir)
    cat = {c["name"]: c for c in json.load(open(Path(features_dir) / "feature_catalog.json", encoding="utf-8"))}
    pos = pd.read_csv(positives_csv)
    lookup = {(int(r), int(c)): i for i, (r, c) in enumerate(zip(idx[0], idx[1]))}
    pidx = np.array([lookup[(int(r), int(c))] for r, c in zip(pos.row, pos.col)])
    prod = pos.is_producer.values
    rows = []
    for i, n in enumerate(names):
        v = np.asarray(X[i], dtype="float64")
        bg = np.sort(v)
        pv = v[pidx]
        a = auc_vs_background(pv, bg)
        rows.append({"feature": n, "group": cat[n]["group"], "min": v.min(), "median": np.median(v), "max": v.max(),
                     "std": v.std(), "n_unique": int(np.unique(v[:200000]).size),
                     "auc_all": a, "auc_strength": max(a, 1 - a),
                     "auc_producers": auc_vs_background(pv[prod], bg), "auc_non_producers": auc_vs_background(pv[~prod], bg)})
    rep = pd.DataFrame(rows).sort_values("auc_strength", ascending=False).reset_index(drop=True)
    with atomic_write(out_report, "w") as fh:
        rep.to_csv(fh, index=False)

    rng = np.random.default_rng(seed)
    cols = np.sort(rng.choice(X.shape[1], size=min(sample, X.shape[1]), replace=False))
    S = np.asarray(X[:, cols], dtype="float64")
    keep = S.std(axis=1) > 0
    C = np.corrcoef(S[keep])
    kn = [n for n, k in zip(names, keep) if k]
    pairs = [{"a": kn[i], "b": kn[j], "pearson_r": C[i, j]} for i in range(len(kn)) for j in range(i + 1, len(kn))
             if abs(C[i, j]) >= corr_threshold]
    pdf = pd.DataFrame(pairs, columns=["a", "b", "pearson_r"]).sort_values("pearson_r", key=np.abs, ascending=False)
    with atomic_write(out_pairs, "w") as fh:
        pdf.to_csv(fh, index=False)
    return rep
