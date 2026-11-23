"""Phase 4: the master grid and alignment of every layer onto it.

Master grid = the survey grid itself (EPSG:32613, 50 m cells, 1707 x 3986). Radiometric and magnetic layers
are already on it (cleaned in Phase 3). Terrain and geology come in other CRSs/resolutions and are resampled
onto it:
  * terrain (continuous, 30 m -> 50 m, shrinking): AVERAGE resampling (bilinear would skip cells when shrinking)
  * geology (categorical polygons): rasterised to class codes, no interpolation, 0 = unmapped
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from rasterio import features
from rasterio.warp import Resampling, reproject

from .ancillary import SRTM_TILES, srtm_hgt_path
from .clean import LAYERS as CLEAN_LAYERS, write_float_tif
from .runner import atomic_write

SRTM_VOID = -32768


def master_profile(clean_dir: Path) -> dict:
    with rasterio.open(Path(clean_dir) / "U_FIN.tif") as r:
        return r.profile


def write_uint16_tif(path: Path, arr: np.ndarray, profile: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    prof = {**profile, "driver": "GTiff", "dtype": "uint16", "count": 1, "nodata": 0, "compress": "deflate",
            "tiled": True, "blockxsize": 256, "blockysize": 256}
    with rasterio.open(tmp, "w", **prof) as dst:
        dst.write(arr.astype("uint16"), 1)
    os.replace(tmp, path)


def build_dem(raw: Path, clean_dir: Path, out: Path) -> None:
    prof = master_profile(clean_dir)
    dst = np.full((prof["height"], prof["width"]), np.nan, dtype="float32")
    for n in SRTM_TILES:
        tmp = np.full_like(dst, np.nan)
        with rasterio.open(srtm_hgt_path(raw, n)) as src:
            reproject(rasterio.band(src, 1), tmp, src_transform=src.transform, src_crs="EPSG:4326",
                      src_nodata=SRTM_VOID, dst_transform=prof["transform"], dst_crs=prof["crs"],
                      dst_nodata=np.nan, resampling=Resampling.average)
        dst = np.where(np.isnan(dst), tmp, dst)
    write_float_tif(out, dst, prof)


def build_geology(sgmc_dir: Path, clean_dir: Path, out_class: Path, out_unit: Path, legend_csv: Path) -> None:
    prof = master_profile(clean_dir)
    b = rasterio.transform.array_bounds(prof["height"], prof["width"], prof["transform"])  # west, south, east, north
    g = gpd.read_file(Path(sgmc_dir) / "WY_geol_poly.shp").to_crs(prof["crs"])
    g = g.cx[b[0]:b[2], b[1]:b[3]].copy()
    units = pd.read_csv(Path(sgmc_dir) / "WY_units.csv", encoding="latin1").set_index("unit_link")
    g["GENERALIZE"] = g["GENERALIZE"].fillna("Unknown")
    cls_code = {n: i + 1 for i, n in enumerate(sorted(g["GENERALIZE"].unique()))}
    unit_code = {n: i + 1 for i, n in enumerate(sorted(g["UNIT_LINK"].unique()))}
    for col, mapping, src_col, path in (("cls", cls_code, "GENERALIZE", out_class), ("unit", unit_code, "UNIT_LINK", out_unit)):
        shapes = ((geom, mapping[v]) for geom, v in zip(g.geometry, g[src_col]))
        arr = features.rasterize(shapes, out_shape=(prof["height"], prof["width"]), transform=prof["transform"],
                                 fill=0, dtype="uint16")
        write_uint16_tif(path, arr, prof)
    rows = [{"kind": "class", "code": c, "label": n} for n, c in cls_code.items()]
    for n, c in unit_code.items():
        r = units.loc[n] if n in units.index else None
        rows.append({"kind": "unit", "code": c, "label": n,
                     "unit_name": None if r is None else r["unit_name"],
                     "unit_age": None if r is None else r["unit_age"],
                     "rocktype1": None if r is None else r["rocktype1"]})
    with atomic_write(legend_csv, "w") as fh:
        pd.DataFrame(rows).to_csv(fh, index=False)


def build_master_mask(clean_dir: Path, dem_tif: Path, out: Path) -> int:
    """1 where every radiometric/magnetic layer AND the DEM are valid, else 0."""
    mask = None
    for n in CLEAN_LAYERS + ["DEM"]:
        p = Path(dem_tif) if n == "DEM" else Path(clean_dir) / f"{n}.tif"
        with rasterio.open(p) as r:
            ok = ~r.read(1, masked=True).mask
        mask = ok if mask is None else mask & ok
    write_uint16_tif(out, mask.astype("uint16"), master_profile(clean_dir))
    return int(mask.sum())


def validate_alignment(paths: list[Path]) -> pd.DataFrame:
    """Every layer must share shape, transform and CRS, or stacking would silently shift pixels."""
    rows = []
    for p in paths:
        with rasterio.open(p) as r:
            rows.append({"layer": Path(p).stem, "shape": (r.height, r.width),
                         "transform": tuple(r.transform)[:6], "epsg": r.crs.to_epsg()})
    df = pd.DataFrame(rows)
    for k in ("shape", "transform", "epsg"):
        if df[k].astype(str).nunique() != 1:
            raise ValueError(f"layers are not aligned on '{k}':\n{df[['layer', k]]}")
    return df


def validation_report(processed_dir: Path, clean_dir: Path, report: Path) -> dict:
    processed_dir, clean_dir = Path(processed_dir), Path(clean_dir)
    cat = ("geology_class", "geology_unit")
    paths = [clean_dir / f"{n}.tif" for n in CLEAN_LAYERS] + [
        processed_dir / f for f in ("dem.tif", "geology_class.tif", "geology_unit.tif", "master_mask.tif")]
    validate_alignment(paths)
    with rasterio.open(processed_dir / "master_mask.tif") as r:
        mask = r.read(1).astype(bool)
    out: dict = {"aligned_layers": [p.stem for p in paths], "mask_cells": int(mask.sum()), "layers": {}}
    for p in paths[:-1]:
        with rasterio.open(p) as r:
            a = r.read(1, masked=True)
        if p.stem in cat:
            raw = a.data[mask]
            out["layers"][p.stem] = {"unmapped_fraction_inside_mask": float((raw == 0).mean()),
                                     "n_distinct_codes_inside_mask": int(len(np.unique(raw[raw > 0])))}
            continue
        vals = a.filled(np.nan).astype("float64")
        inside = vals[mask]
        out["layers"][p.stem] = {"nan_inside_mask": int(np.isnan(inside).sum()),
                                 "valid_outside_mask": int((~np.isnan(vals[~mask])).sum()),
                                 "min": float(np.nanmin(inside)), "max": float(np.nanmax(inside)),
                                 "mean": float(np.nanmean(inside))}
    bad = {k: v for k, v in out["layers"].items() if v.get("nan_inside_mask")}
    if bad:
        raise ValueError(f"layers have missing values inside the master mask: {bad}")
    with atomic_write(report, "w") as fh:
        json.dump(out, fh, indent=2)
    return out
