"""Phase 5a: turn MRDS uranium records into training labels on the master grid.

Design (agreed with the user, see docs/phases/phase-05-labels-splits.md):
- Positive = any uranium record (every dev_stat) inside the survey footprint, collapsed to ONE positive per
  50 m cell. Several records at one place (district centroids, claim groups) would otherwise be counted as
  several independent deposits.
- Everything else on the valid grid is UNLABELED, not negative. Cells within `buffer_m` of a positive are
  marked "excluded" so unlabeled background is never sampled right next to a known occurrence (which is
  probably mineralised too, and whose location is uncertain).
- dev_stat and score are kept as metadata (never as filters) so Phase 8 can test the mine-record effect.

Label raster codes: 0 = outside valid mask, 1 = unlabeled background, 2 = positive, 3 = excluded buffer.
"""
from __future__ import annotations

import json
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio

from .master_grid import write_uint16_tif
from .occurrences import load_uranium
from .runner import atomic_write

OUTSIDE, BACKGROUND, POSITIVE, EXCLUDED = 0, 1, 2, 3
# Highest first. A cell holding a producer record is a "producer cell".
STATUS_RANK = {"Producer": 4, "Past Producer": 3, "Prospect": 2, "Occurrence": 1, "Unknown": 0, "Plant": 0}


def disk_offsets(radius_cells: int) -> tuple[np.ndarray, np.ndarray]:
    """Row/col offsets of every cell whose centre is within radius_cells of the origin."""
    r = np.arange(-radius_cells, radius_cells + 1)
    dr, dc = np.meshgrid(r, r, indexing="ij")
    keep = dr**2 + dc**2 <= radius_cells**2
    return dr[keep], dc[keep]


def collapse_to_cells(records: pd.DataFrame, rows: np.ndarray, cols: np.ndarray, transform) -> pd.DataFrame:
    """One row per grid cell, keeping the strongest status and the best (lowest-letter) score."""
    d = records.copy()
    d["row"], d["col"] = rows, cols
    d["rank"] = d["dev_stat"].map(STATUS_RANK).fillna(0).astype(int)
    d["score"] = d["score"].fillna("Z")
    out = []
    for (r, c), g in d.groupby(["row", "col"]):
        top = g.sort_values("rank", ascending=False).iloc[0]
        x, y = transform @ (c + 0.5, r + 0.5)
        out.append({
            "row": int(r), "col": int(c), "x": float(x), "y": float(y),
            "n_records": len(g), "dev_stat": top["dev_stat"],
            "is_producer": bool(g["dev_stat"].isin(["Producer", "Past Producer"]).any()),
            "best_score": g["score"].min(), "dep_ids": ";".join(str(i) for i in g["dep_id"]),
            "site_name": top["site_name"],
        })
    return pd.DataFrame(out)


def build_label_raster(shape: tuple[int, int], mask: np.ndarray, pos_rows: np.ndarray, pos_cols: np.ndarray,
                       buffer_cells: int) -> np.ndarray:
    lab = np.where(mask, BACKGROUND, OUTSIDE).astype("uint8")
    dr, dc = disk_offsets(buffer_cells)
    for r, c in zip(pos_rows, pos_cols):
        rr, cc = r + dr, c + dc
        ok = (rr >= 0) & (rr < shape[0]) & (cc >= 0) & (cc < shape[1])
        rr, cc = rr[ok], cc[ok]
        sel = lab[rr, cc] == BACKGROUND
        lab[rr[sel], cc[sel]] = EXCLUDED
    lab[pos_rows, pos_cols] = POSITIVE
    return lab


def run_labels(mrds_csv: Path, footprint_shp: Path, mask_tif: Path, out_csv: Path, out_tif: Path,
               out_report: Path, buffer_m: float) -> dict:
    with rasterio.open(mask_tif) as r:
        mask = r.read(1).astype(bool)
        transform, profile, crs = r.transform, r.profile, r.crs
        cell = abs(transform.a)

    fp = gpd.read_file(footprint_shp).to_crs(4326).union_all()
    u = load_uranium(mrds_csv)
    score = pd.read_csv(mrds_csv, usecols=["dep_id", "score"], low_memory=False)
    u = u.merge(score, on="dep_id", how="left")
    g = gpd.GeoDataFrame(u, geometry=gpd.points_from_xy(u.longitude, u.latitude), crs=4326)
    g = g[g.within(fp)].to_crs(crs)
    inv = ~transform
    cols, rows = inv * (g.geometry.x.values, g.geometry.y.values)
    rows, cols = np.floor(rows).astype(int), np.floor(cols).astype(int)
    inside = (rows >= 0) & (rows < mask.shape[0]) & (cols >= 0) & (cols < mask.shape[1])
    on_valid = np.zeros(len(g), dtype=bool)
    on_valid[inside] = mask[rows[inside], cols[inside]]

    pos = collapse_to_cells(pd.DataFrame(g.drop(columns="geometry"))[on_valid], rows[on_valid], cols[on_valid], transform)
    lab = build_label_raster(mask.shape, mask, pos["row"].values, pos["col"].values, int(round(buffer_m / cell)))
    write_uint16_tif(out_tif, lab, profile)
    with atomic_write(out_csv, "w") as fh:
        pos.to_csv(fh, index=False)

    n_valid = int(mask.sum())
    rep = {
        "records_in_footprint": int(len(g)), "records_on_valid_cells": int(on_valid.sum()),
        "records_dropped_off_mask": int((~on_valid).sum()),
        "positive_cells": int(len(pos)), "cells_with_multiple_records": int((pos.n_records > 1).sum()),
        "producer_cells": int(pos.is_producer.sum()), "non_producer_cells": int((~pos.is_producer).sum()),
        "by_dev_stat": pos.dev_stat.value_counts().to_dict(), "by_best_score": pos.best_score.value_counts().to_dict(),
        "buffer_m": buffer_m, "valid_cells": n_valid,
        "excluded_cells": int((lab == EXCLUDED).sum()), "background_cells": int((lab == BACKGROUND).sum()),
        "prevalence_of_positives": len(pos) / n_valid,
    }
    with atomic_write(out_report, "w") as fh:
        json.dump(rep, fh, indent=2)
    return rep
