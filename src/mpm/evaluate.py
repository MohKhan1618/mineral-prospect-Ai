"""Phase 8: honest evaluation of the saved out-of-fold score maps.

Key ideas (rules fixed in docs/phases/phase-08-decision-rule.md):
- INCLUSIVE evaluation: the 2 km ring around positives counts as unlabeled, so the hardest look-alikes are scored.
- Each positive gets a PERCENTILE: the share of that fold's unlabeled cells scoring below it. Percentiles are
  comparable across folds (raw model scores are not), so they can be pooled and bootstrapped.
    ROC-AUC            = mean percentile of positives
    recall @ top p %   = share of positives with percentile >= 1 - p
- BLOCK bootstrap: whole 15 km blocks (with their positives) are resampled, so clustered positives are not
  treated as independent. Paired differences reuse the same resamples for both models.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
import rasterio

from .features import load_features
from .labels import BACKGROUND, EXCLUDED, POSITIVE
from .runner import atomic_write


@dataclass
class Ctx:
    X: np.ndarray            # (n_features, n_cells) memmap
    names: list[str]
    groups: dict[str, list[int]]   # feature group -> row indices in X
    rows: np.ndarray
    cols: np.ndarray
    lab: np.ndarray          # per valid cell: 1 background, 2 positive, 3 buffer ring
    blk: np.ndarray          # per valid cell: block id
    shape: tuple[int, int]
    radius: int              # buffer radius in cells
    is_prod: np.ndarray      # per valid cell: True where the cell holds a producer / past-producer record
    splits: pd.DataFrame
    n_folds: int
    cell_m: float
    xy: np.ndarray           # (n_cells, 2) cell-centre coordinates in metres


def load_context(features_dir: Path, labels_tif: Path, block_tif: Path, splits_csv: Path, positives_csv: Path,
                 buffer_m: float) -> Ctx:
    X, idx, names = load_features(features_dir)
    cat = json.load(open(Path(features_dir) / "feature_catalog.json", encoding="utf-8"))
    groups: dict[str, list[int]] = {}
    for i, c in enumerate(cat):
        groups.setdefault(c["group"], []).append(i)
    rows, cols = idx[0], idx[1]
    with rasterio.open(labels_tif) as r:
        labels, tr = r.read(1), r.transform
    with rasterio.open(block_tif) as r:
        blocks = r.read(1)
    pos = pd.read_csv(positives_csv)
    lab = labels[rows, cols]
    lookup = {(int(a), int(b)): i for i, (a, b) in enumerate(zip(rows, cols))}
    pi = np.array([lookup[(int(a), int(b))] for a, b in zip(pos.row, pos.col)])
    is_prod = np.zeros(rows.size, dtype=bool)
    is_prod[pi[pos.is_producer.values]] = True
    cell = abs(tr.a)
    xy = np.column_stack([tr.c + (cols + 0.5) * cell, tr.f - (rows + 0.5) * cell])
    sp = pd.read_csv(splits_csv)
    return Ctx(X, names, groups, rows, cols, lab, blocks[rows, cols], labels.shape, int(round(buffer_m / cell)),
               is_prod, sp, int(sp.fold.max()) + 1, cell, xy)


def fold_cells(ctx: Ctx, rep: int) -> np.ndarray:
    sp = ctx.splits[ctx.splits.repeat == rep]
    fob = np.full(int(ctx.blk.max()) + 1, -1, dtype=int)
    fob[sp.block_id.values] = sp.fold.values
    out = fob[ctx.blk]
    if (out < 0).any():
        raise ValueError("cells in a block without a fold")
    return out


# ---------- percentiles and block bootstrap ----------
def positive_percentiles(score: np.ndarray, lab: np.ndarray, fold_cell: np.ndarray, n_folds: int) -> pd.DataFrame:
    """For every positive: share of its fold's unlabeled (background + ring) cells it outscores (ties half)."""
    out = []
    for f in range(n_folds):
        t = fold_cell == f
        un = np.sort(score[t & ((lab == BACKGROUND) | (lab == EXCLUDED))].astype("float64"))
        pidx = np.flatnonzero(t & (lab == POSITIVE))
        v = score[pidx].astype("float64")
        lo, hi = np.searchsorted(un, v, "left"), np.searchsorted(un, v, "right")
        out.append(pd.DataFrame({"cell": pidx, "pct": (lo + hi) / 2 / un.size, "fold": f}))
    return pd.concat(out, ignore_index=True)


def group_stats(pct: pd.DataFrame, blk: np.ndarray, keep: np.ndarray | None = None) -> pd.DataFrame:
    """Per block: number of positives, sum of percentiles, hits in the top 1 % and top 5 %."""
    d = pct if keep is None else pct[keep]
    g = pd.DataFrame({"block": blk[d.cell.values], "pct": d.pct.values})
    g["h1"], g["h5"] = (g.pct >= 0.99).astype(float), (g.pct >= 0.95).astype(float)
    return g.groupby("block").agg(n=("pct", "size"), s=("pct", "sum"), h1=("h1", "sum"), h5=("h5", "sum"))


def point_estimates(gs: pd.DataFrame) -> dict:
    n = gs.n.sum()
    return {"n_pos": int(n), "roc_auc": float(gs.s.sum() / n), "recall_top1pct": float(gs.h1.sum() / n),
            "recall_top5pct": float(gs.h5.sum() / n)}


def bootstrap_counts(n_groups: int, n_boot: int, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return rng.multinomial(n_groups, np.full(n_groups, 1.0 / n_groups), size=n_boot).astype("float64")


def boot_metrics(gs: pd.DataFrame, counts: np.ndarray) -> dict[str, np.ndarray]:
    n = counts @ gs.n.values.astype("float64")
    ok = n > 0
    res = {}
    for k, col in (("roc_auc", "s"), ("recall_top1pct", "h1"), ("recall_top5pct", "h5")):
        v = np.full(counts.shape[0], np.nan)
        v[ok] = (counts @ gs[col].values.astype("float64"))[ok] / n[ok]
        res[k] = v
    return res


def ci(v: np.ndarray) -> tuple[float, float]:
    return float(np.nanpercentile(v, 2.5)), float(np.nanpercentile(v, 97.5))


def pooled_group_stats(ctx: Ctx, oof_files: list[Path], fold_cells_list: list[np.ndarray], nonproducers: bool,
                       blocks_index: pd.Index) -> pd.DataFrame:
    """Average the per-block stats over repeats (each repeat has its own folds), on a common block index."""
    acc = None
    for f, fc in zip(oof_files, fold_cells_list):
        pct = positive_percentiles(np.load(f), ctx.lab, fc, ctx.n_folds)
        keep = ~ctx.is_prod[pct.cell.values] if nonproducers else None
        gs = group_stats(pct, ctx.blk, keep).reindex(blocks_index).fillna(0.0)
        acc = gs if acc is None else acc + gs
    return acc / len(oof_files)


def evaluate_saved_models(ctx: Ctx, oof_dir: Path, models: list[str], repeats: int, baselines: list[str],
                          out_ci: Path, out_pairs: Path, n_boot: int = 2000, seed: int = 42) -> tuple[pd.DataFrame, pd.DataFrame]:
    fcs = [fold_cells(ctx, r) for r in range(repeats)]
    pos_blocks = pd.Index(np.unique(ctx.blk[ctx.lab == POSITIVE]))
    rows_ci, rows_pairs = [], []
    stats: dict[tuple[str, bool], pd.DataFrame] = {}
    for m in models:
        files = [oof_dir / f"{m}_r{r}.npy" for r in range(repeats)]
        for nonprod in (False, True):
            stats[(m, nonprod)] = pooled_group_stats(ctx, files, fcs, nonprod, pos_blocks)
    counts_all = bootstrap_counts(len(pos_blocks), n_boot, seed)
    for (m, nonprod), gs in stats.items():
        gs_n = gs[gs.n > 0]
        est = point_estimates(gs)
        b = boot_metrics(gs, counts_all)
        row = {"model": m, "positives": "non_producers" if nonprod else "all", **est}
        for k in ("roc_auc", "recall_top1pct", "recall_top5pct"):
            row[f"{k}_lo"], row[f"{k}_hi"] = ci(b[k])
        rows_ci.append(row)
    for m in models:
        for base in baselines:
            if m == base:
                continue
            for nonprod in (False, True):
                a, c = stats[(m, nonprod)], stats[(base, nonprod)]
                ba, bc = boot_metrics(a, counts_all), boot_metrics(c, counts_all)
                pa, pc = point_estimates(a), point_estimates(c)
                for k in ("roc_auc", "recall_top5pct"):
                    d = ba[k] - bc[k]
                    lo, hi = ci(d)
                    rows_pairs.append({"model": m, "baseline": base,
                                       "positives": "non_producers" if nonprod else "all", "metric": k,
                                       "diff": pa[k] - pc[k], "lo": lo, "hi": hi, "excludes_zero_above": bool(lo > 0)})
    df_ci, df_pairs = pd.DataFrame(rows_ci), pd.DataFrame(rows_pairs)
    with atomic_write(out_ci, "w") as fh:
        df_ci.to_csv(fh, index=False)
    with atomic_write(out_pairs, "w") as fh:
        df_pairs.to_csv(fh, index=False)
    return df_ci, df_pairs
