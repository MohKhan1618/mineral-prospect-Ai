"""Phase 5b: spatial block cross-validation folds, frozen to disk.

Why blocks: neighbouring cells look alike (spatial autocorrelation). A random split puts near-copies of
a training cell into the test set, so the score would measure memory of the neighbourhood, not skill.
Instead the map is cut into square blocks and whole blocks go to one fold.

Why repeats: with ~200 positives in few clusters, one block assignment can be lucky or unlucky. We make
several different assignments and report the spread of results.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import rasterio

from .labels import POSITIVE
from .master_grid import write_uint16_tif
from .runner import atomic_write


def block_id_raster(shape: tuple[int, int], block_cells: int) -> np.ndarray:
    """Block number per cell, starting at 1 (0 stays free for nodata)."""
    n_bc = -(-shape[1] // block_cells)
    rr, cc = np.indices(shape)
    return ((rr // block_cells) * n_bc + (cc // block_cells) + 1).astype("uint16")


def block_table(labels: np.ndarray, blocks: np.ndarray) -> pd.DataFrame:
    valid = labels > 0
    df = pd.DataFrame({"block_id": blocks[valid], "pos": (labels[valid] == POSITIVE)})
    t = df.groupby("block_id").agg(n_valid=("pos", "size"), n_pos=("pos", "sum")).reset_index()
    t["n_pos"] = t["n_pos"].astype(int)
    return t


def assign_folds(table: pd.DataFrame, n_folds: int, seed: int) -> pd.DataFrame:
    """Greedy balancing: blocks with the most positives first, each to the fold with the fewest positives.

    Random noise on the ordering gives a different (but still balanced) assignment per seed.
    Blocks without positives then even out the number of valid cells per fold.
    """
    rng = np.random.default_rng(seed)
    t = table.copy()
    t["key"] = t["n_pos"] + rng.uniform(0, 2, len(t))
    pos_blocks = t[t.n_pos > 0].sort_values("key", ascending=False)
    zero_blocks = t[t.n_pos == 0].sample(frac=1, random_state=int(rng.integers(1 << 31)))
    zero_blocks = zero_blocks.sort_values("n_valid", ascending=False)
    pos_load = np.zeros(n_folds)
    cell_load = np.zeros(n_folds)
    fold = {}
    for _, b in pos_blocks.iterrows():
        cand = np.flatnonzero(pos_load == pos_load.min())
        f = int(cand[np.argmin(cell_load[cand])])
        fold[int(b.block_id)] = f
        pos_load[f] += b.n_pos
        cell_load[f] += b.n_valid
    for _, b in zero_blocks.iterrows():
        f = int(np.argmin(cell_load))
        fold[int(b.block_id)] = f
        cell_load[f] += b.n_valid
    out = t[["block_id", "n_valid", "n_pos"]].copy()
    out["fold"] = out["block_id"].map(fold)
    return out


def cross_fold_neighbours(pos: pd.DataFrame, fold_of_pos: np.ndarray, radius_m: float) -> float:
    """Share of positives that have another positive from a DIFFERENT fold within radius_m (leakage risk)."""
    xy = pos[["x", "y"]].values
    d = np.hypot(xy[:, None, 0] - xy[None, :, 0], xy[:, None, 1] - xy[None, :, 1])
    diff = fold_of_pos[:, None] != fold_of_pos[None, :]
    return float(((d <= radius_m) & diff).any(axis=1).mean())


def run_splits(labels_tif: Path, positives_csv: Path, out_csv: Path, out_block_tif: Path, out_report: Path,
               block_m: float, n_folds: int, n_repeats: int, seed: int, buffer_m: float) -> dict:
    with rasterio.open(labels_tif) as r:
        labels = r.read(1)
        profile, cell = r.profile, abs(r.transform.a)
    block_cells = int(round(block_m / cell))
    blocks = block_id_raster(labels.shape, block_cells)
    table = block_table(labels, blocks)
    pos = pd.read_csv(positives_csv)
    pos["block_id"] = blocks[pos["row"].values, pos["col"].values]

    frames, per_repeat = [], []
    for rep in range(n_repeats):
        a = assign_folds(table, n_folds, seed + rep)
        a.insert(0, "repeat", rep)
        frames.append(a)
        fold_of_pos = pos["block_id"].map(dict(zip(a.block_id, a.fold))).values.astype(int)
        counts = np.bincount(fold_of_pos, minlength=n_folds)
        cells = a.groupby("fold").n_valid.sum().reindex(range(n_folds)).fillna(0)
        per_repeat.append({
            "repeat": rep, "positives_per_fold": counts.tolist(), "min_positives_in_a_fold": int(counts.min()),
            "valid_cells_per_fold": cells.astype(int).tolist(),
            "share_pos_with_cross_fold_neighbour_within_buffer": cross_fold_neighbours(pos, fold_of_pos, buffer_m),
        })
    splits = pd.concat(frames, ignore_index=True)
    write_uint16_tif(out_block_tif, np.where(labels > 0, blocks, 0), profile)
    with atomic_write(out_csv, "w") as fh:
        splits.to_csv(fh, index=False)
    rep_out = {
        "block_m": block_m, "block_cells": block_cells, "n_blocks_with_valid_cells": int(len(table)),
        "n_blocks_with_positives": int((table.n_pos > 0).sum()), "n_folds": n_folds, "n_repeats": n_repeats,
        "positives": int(len(pos)), "positives_per_block_top5": sorted(table.n_pos.tolist(), reverse=True)[:5],
        "per_repeat": per_repeat,
    }
    with atomic_write(out_report, "w") as fh:
        json.dump(rep_out, fh, indent=2)
    return rep_out
