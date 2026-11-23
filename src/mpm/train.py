"""Phase 7: train every candidate under buffered spatial block cross-validation.

For each (repeat, fold):
  test cells      = all valid cells in the blocks assigned to that fold
  training pool   = valid cells in the other blocks, MINUS cells within `buffer_m` of any test positive
                    (so a training cell cannot be a near-copy of a test positive: the leakage flagged in Phase 5)
  training set    = every pool positive + `background_sample` random unlabeled pool cells (same sample for all
                    models, so they are compared on identical data)
  evaluation      = test positives vs test unlabeled cells (the excluded 2 km buffer around positives is not scored
                    as "negative", see labels.py)
Every model scores EVERY test cell, so the out-of-fold score map is complete: scores[cell] always comes from a
model that never saw that cell's block.

Resumable: one file per (model, repeat) in out_dir/<config hash>/; finished ones are skipped on re-run.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from pathlib import Path

import numpy as np
import pandas as pd
import rasterio
from sklearn.metrics import roc_auc_score

from .features import load_features
from .labels import BACKGROUND, POSITIVE, disk_offsets
from .metrics import ranking_metrics
from .models import make_model
from .runner import atomic_write, file_hash

log = logging.getLogger(__name__)
CHUNK = 200_000


def buffer_mask(shape: tuple[int, int], rows: np.ndarray, cols: np.ndarray, radius_cells: int) -> np.ndarray:
    """True within radius_cells of any given cell."""
    out = np.zeros(shape, dtype=bool)
    dr, dc = disk_offsets(radius_cells)
    for r, c in zip(rows, cols):
        rr, cc = r + dr, c + dc
        ok = (rr >= 0) & (rr < shape[0]) & (cc >= 0) & (cc < shape[1])
        out[rr[ok], cc[ok]] = True
    return out


def make_fold_sets(lab: np.ndarray, fold_cell: np.ndarray, f: int, rows: np.ndarray, cols: np.ndarray,
                   shape: tuple[int, int], radius_cells: int, n_bg: int, seed: int) -> dict:
    is_pos, is_bg = lab == POSITIVE, lab == BACKGROUND
    test = fold_cell == f
    tp = np.flatnonzero(test & is_pos)
    near = buffer_mask(shape, rows[tp], cols[tp], radius_cells)[rows, cols]
    ok = (~test) & (~near) & (lab > 0)
    pos_tr = np.flatnonzero(ok & is_pos)
    pool = np.flatnonzero(ok & is_bg)
    rng = np.random.default_rng(seed)
    bg_tr = rng.choice(pool, size=min(n_bg, pool.size), replace=False)
    tr = np.sort(np.concatenate([pos_tr, bg_tr]))
    return {"train": tr, "test_all": np.flatnonzero(test), "eval": np.flatnonzero(test & (is_pos | is_bg)),
            "info": {"fold": f, "n_train_pos": int(pos_tr.size), "n_train_bg": int(bg_tr.size),
                     "n_test_pos": int(tp.size),
                     "n_train_pos_removed_by_buffer": int((((~test) & near) & is_pos).sum()),
                     "n_train_cells_removed_by_buffer": int((((~test) & near) & (lab > 0)).sum())}}


def _load(X: np.ndarray, ids: np.ndarray) -> np.ndarray:
    return np.ascontiguousarray(np.asarray(X[:, ids]).T)


def _save_npy(path: Path, arr: np.ndarray) -> None:
    with atomic_write(path, "wb") as fh:
        np.save(fh, arr)


def run_training(features_dir: Path, labels_tif: Path, block_tif: Path, splits_csv: Path, out_dir: Path,
                 report_csv: Path, summary_csv: Path, tcfg: dict, buffer_m: float, seed: int) -> pd.DataFrame:
    X, idx, names = load_features(features_dir)
    rows, cols = idx[0], idx[1]
    with rasterio.open(labels_tif) as r:
        labels = r.read(1)
        radius = int(round(buffer_m / abs(r.transform.a)))
    with rasterio.open(block_tif) as r:
        blocks = r.read(1)
    lab, blk = labels[rows, cols], blocks[rows, cols]
    splits = pd.read_csv(splits_csv)
    n_folds = int(splits.fold.max()) + 1
    h = hashlib.sha1(json.dumps({"t": tcfg, "buf": buffer_m, "seed": seed, "splits": file_hash(splits_csv),
                                 "n_feat": len(names)}, sort_keys=True).encode()).hexdigest()[:10]
    unit_dir = Path(out_dir) / h
    unit_dir.mkdir(parents=True, exist_ok=True)
    fracs = tuple(tcfg["top_fracs"])
    all_rows = []

    for rep in range(tcfg["repeats"]):
        sp = splits[splits.repeat == rep]
        fold_of_block = np.full(int(blocks.max()) + 1, -1, dtype=int)
        fold_of_block[sp.block_id.values] = sp.fold.values
        fold_cell = fold_of_block[blk]
        if (fold_cell < 0).any():
            raise ValueError("some valid cells are in a block with no fold")
        sets = [make_fold_sets(lab, fold_cell, f, rows, cols, labels.shape, radius, tcfg["background_sample"],
                               seed + 1000 * rep + f) for f in range(n_folds)]
        for model_name in tcfg["models"]:
            stem = unit_dir / f"{model_name}_r{rep}"
            if stem.with_suffix(".npy").exists() and stem.with_suffix(".json").exists():
                all_rows += json.load(open(stem.with_suffix(".json")))["rows"]
                log.info("skip  %s repeat %d (done)", model_name, rep)
                continue
            t0 = time.time()
            oof = np.full(X.shape[1], np.nan, dtype="float32")
            unit_rows = []
            for f, s in enumerate(sets):
                m = make_model(model_name, names, seed + 1000 * rep + f)
                Xtr = _load(X, s["train"])
                ytr = (lab[s["train"]] == POSITIVE).astype(int)
                m.fit(Xtr, ytr)
                train_auc = float(roc_auc_score(ytr, m.score(Xtr)))
                ids = s["test_all"]
                oof[ids] = np.concatenate([m.score(_load(X, ids[i:i + CHUNK])) for i in range(0, ids.size, CHUNK)])
                ev = s["eval"]
                met = ranking_metrics((lab[ev] == POSITIVE).astype(int), oof[ev], fracs, seed=seed)
                unit_rows.append({"model": model_name, "repeat": rep, **s["info"], "train_auc": train_auc, **met})
            _save_npy(stem.with_suffix(".npy"), oof)
            with atomic_write(stem.with_suffix(".json"), "w") as fh:
                json.dump({"seconds": time.time() - t0, "rows": unit_rows}, fh, default=float)
            all_rows += unit_rows
            log.info("done  %s repeat %d in %.0fs (mean roc %.3f)", model_name, rep, time.time() - t0,
                     np.mean([r["roc_auc"] for r in unit_rows]))

    df = pd.DataFrame(all_rows)
    with atomic_write(report_csv, "w") as fh:
        df.to_csv(fh, index=False)
    keep = ["roc_auc", "pr_auc", "pr_auc_over_prevalence", "recall_top1pct", "recall_top5pct", "lift_top5pct", "train_auc"]
    g = df.groupby("model", sort=False)[keep]
    summ = pd.concat({"mean": g.mean(), "std": g.std()}, axis=1)
    summ.columns = [f"{b}_{a}" for a, b in summ.columns]
    summ = summ.reset_index()
    summ.insert(1, "n_fold_runs", df.groupby("model", sort=False).size().values)
    with atomic_write(summary_csv, "w") as fh:
        summ.to_csv(fh, index=False)
    return summ
