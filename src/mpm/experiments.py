"""Phase 8 experiments. All use the same buffered spatial protocol as Phase 7 (train.make_fold_sets) and the
INCLUSIVE evaluation (buffer ring counted as unlabeled), reported for all positives and for non-producers only.

  run_folds     one model under spatial CV, with switches: feature subset, drop producers from training,
                shuffled training labels, fraction of training data, hyper-parameter overrides
  run_lodo      leave-one-district-out: hold out one whole uranium district (plus a 12 km surround)
  run_tuning    nested CV: pick hyper-parameters by inner spatial CV on the outer-training blocks only
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.cluster.hierarchy import fcluster, linkage
from sklearn.metrics import roc_auc_score

from .evaluate import Ctx, fold_cells
from .labels import POSITIVE
from .metrics import ranking_metrics
from .models import make_model
from .runner import atomic_write
from .splits import assign_folds
from .train import CHUNK, _load, buffer_mask, make_fold_sets

log = logging.getLogger(__name__)
KEEP = ["roc_auc", "pr_auc", "recall_top1pct", "recall_top5pct", "lift_top5pct"]


def _score(model, X, ids, cols):
    return np.concatenate([model.score(_load(X, ids[i:i + CHUNK])[:, cols]) for i in range(0, ids.size, CHUNK)])


def inclusive_metrics(ctx: Ctx, ids: np.ndarray, score: np.ndarray, seed: int = 42) -> dict:
    """Metrics on cells `ids` (positives vs everything else incl. ring); and again without producer positives."""
    y = (ctx.lab[ids] == POSITIVE).astype(int)
    out = {}
    if 0 < y.sum() < y.size:
        m = ranking_metrics(y, score, seed=seed)
        out.update({f"incl_{k}": m[k] for k in KEEP}); out["n_pos"] = m["n_pos"]; out["n_eval"] = m["n_eval"]
    keep = ~ctx.is_prod[ids]
    y2 = y[keep]
    if 0 < y2.sum() < y2.size:
        m = ranking_metrics(y2, score[keep], seed=seed)
        out.update({f"nonprod_{k}": m[k] for k in KEEP}); out["n_pos_nonprod"] = m["n_pos"]
    return out


def run_folds(ctx: Ctx, rep: int, model_name: str, *, params: dict | None = None, cols: list[int] | None = None,
              drop_producers: bool = False, shuffle: bool = False, frac: float = 1.0, n_bg: int = 40000,
              seed: int = 42, tag: dict | None = None) -> list[dict]:
    cols = list(range(len(ctx.names))) if cols is None else sorted(cols)
    names = [ctx.names[i] for i in cols]
    fc = fold_cells(ctx, rep)
    rows = []
    for f in range(ctx.n_folds):
        s = make_fold_sets(ctx.lab, fc, f, ctx.rows, ctx.cols, ctx.shape, ctx.radius, n_bg, seed + 1000 * rep + f)
        tr = s["train"]
        if drop_producers:
            tr = tr[~ctx.is_prod[tr]]
        rng = np.random.default_rng(seed + 77 + f)
        if frac < 1.0:
            tr = np.sort(rng.choice(tr, int(len(tr) * frac), replace=False))
        ytr = (ctx.lab[tr] == POSITIVE).astype(int)
        if shuffle:
            ytr = rng.permutation(ytr)
        Xtr = _load(ctx.X, tr)[:, cols]
        m = make_model(model_name, names, seed + 1000 * rep + f, params).fit(Xtr, ytr)
        train_auc = float(roc_auc_score(ytr, m.score(Xtr))) if 0 < ytr.sum() < ytr.size else np.nan
        ids = s["test_all"]
        rows.append({"model": model_name, "repeat": rep, "fold": f, "n_train_pos": int(ytr.sum()),
                     "train_auc": train_auc, **(tag or {}), **inclusive_metrics(ctx, ids, _score(m, ctx.X, ids, cols), seed)})
    return rows


# ---------- leave-one-district-out ----------
def district_clusters(ctx: Ctx, link_m: float) -> tuple[np.ndarray, np.ndarray]:
    pos = np.flatnonzero(ctx.lab == POSITIVE)
    cl = fcluster(linkage(ctx.xy[pos], "single"), link_m, "distance")
    return pos, cl


def run_lodo(ctx: Ctx, model_names: list[str], link_m: float, min_pos: int, n_bg: int, seed: int) -> pd.DataFrame:
    pos, cl = district_clusters(ctx, link_m)
    rows = []
    for c in np.unique(cl):
        P = pos[cl == c]
        if len(P) < min_pos:
            continue
        region = buffer_mask(ctx.shape, ctx.rows[P], ctx.cols[P], int(round(link_m / ctx.cell_m)))[ctx.rows, ctx.cols]
        ok = ~region
        pool = np.flatnonzero(ok & (ctx.lab == 1))
        rng = np.random.default_rng(seed + int(c))
        tr = np.sort(np.concatenate([np.flatnonzero(ok & (ctx.lab == POSITIVE)), rng.choice(pool, n_bg, replace=False)]))
        ids = np.flatnonzero(region)
        ytr = (ctx.lab[tr] == POSITIVE).astype(int)
        Xtr = _load(ctx.X, tr)
        cx, cy = ctx.xy[P].mean(axis=0)
        for name in model_names:
            m = make_model(name, ctx.names, seed + int(c)).fit(Xtr, ytr)
            sc = _score(m, ctx.X, ids, list(range(len(ctx.names))))
            rows.append({"district": int(c), "n_district_pos": len(P), "n_district_producers": int(ctx.is_prod[P].sum()),
                         "centre_x": cx, "centre_y": cy, "n_region_cells": int(ids.size), "n_train_pos": int(ytr.sum()),
                         "model": name, **inclusive_metrics(ctx, ids, sc, seed)})
            log.info("LODO district %d model %s roc %.3f", c, name, rows[-1].get("incl_roc_auc", np.nan))
    return pd.DataFrame(rows)


# ---------- nested tuning ----------
GRIDS = {
    "logreg": [{"C": 0.005}, {"C": 0.05}, {"C": 0.5}],
    "rf": [{"max_depth": 5, "min_samples_leaf": 50}, {"max_depth": 8, "min_samples_leaf": 20},
           {"max_depth": 10, "min_samples_leaf": 10}, {"max_depth": 14, "min_samples_leaf": 5}],
}
DEFAULT_IDX = {"logreg": 1, "rf": 2}  # entry in GRIDS equal to the Phase 7 default


def _inner_scores(ctx: Ctx, model_name: str, params: dict, lab_m: np.ndarray, inner_fc: np.ndarray, n_inner: int,
                  n_bg: int, seed: int, eval_bg: int) -> dict:
    rec, auc = [], []
    for j in range(n_inner):
        s = make_fold_sets(lab_m, inner_fc, j, ctx.rows, ctx.cols, ctx.shape, ctx.radius, n_bg, seed + j)
        tr = s["train"]
        ytr = (lab_m[tr] == POSITIVE).astype(int)
        m = make_model(model_name, ctx.names, seed + j, {**params, **({"n_estimators": 100} if "max_depth" in params else {})})
        m.fit(_load(ctx.X, tr), ytr)
        ids = s["test_all"]
        pos, unl = ids[lab_m[ids] == POSITIVE], ids[lab_m[ids] != POSITIVE]
        rng = np.random.default_rng(seed + 31 * j)
        ev = np.concatenate([pos, rng.choice(unl, min(eval_bg, unl.size), replace=False)])
        if pos.size == 0:
            continue
        mm = ranking_metrics((lab_m[ev] == POSITIVE).astype(int), _score(m, ctx.X, ev, list(range(len(ctx.names)))))
        rec.append(mm["recall_top5pct"]); auc.append(mm["roc_auc"])
    return {"inner_recall5": float(np.mean(rec)), "inner_auc": float(np.mean(auc))}


def run_tuning(ctx: Ctx, rep: int, model_name: str, n_inner: int = 4, n_bg_inner: int = 20000, eval_bg: int = 100000,
               seed: int = 42, tie: float = 0.005) -> tuple[pd.DataFrame, pd.DataFrame]:
    grid, fc = GRIDS[model_name], fold_cells(ctx, rep)
    inner_rows, outer_rows = [], []
    for f in range(ctx.n_folds):
        out_test = fc == f
        lab_m = np.where(out_test, 0, ctx.lab)
        d = pd.DataFrame({"b": ctx.blk[~out_test], "p": (ctx.lab[~out_test] == POSITIVE)})
        tab = d.groupby("b").agg(n_valid=("p", "size"), n_pos=("p", "sum")).reset_index().rename(columns={"b": "block_id"})
        tab["n_pos"] = tab["n_pos"].astype(int)
        a = assign_folds(tab, n_inner, seed + f)
        fob = np.full(int(ctx.blk.max()) + 1, -1)
        fob[a.block_id.values] = a.fold.values
        inner_fc = fob[ctx.blk]
        res = []
        for gi, p in enumerate(grid):
            r = _inner_scores(ctx, model_name, p, lab_m, inner_fc, n_inner, n_bg_inner, seed + 100 * f, eval_bg)
            res.append(r); inner_rows.append({"model": model_name, "outer_fold": f, "config": gi, "params": json.dumps(p), **r})
        best = max(r["inner_recall5"] for r in res)
        # simplest (earliest) config whose recall is within `tie` of the best
        chosen = next(i for i, r in enumerate(res) if r["inner_recall5"] >= best - tie)
        for label, gi in (("tuned", chosen), ("default", DEFAULT_IDX[model_name])):
            only = run_folds_single(ctx, rep, model_name, f, grid[gi], seed)
            outer_rows.append({"model": model_name, "outer_fold": f, "which": label, "config": gi,
                               "params": json.dumps(grid[gi]), **only})
        log.info("tuning %s outer fold %d chose config %d", model_name, f, chosen)
    return pd.DataFrame(inner_rows), pd.DataFrame(outer_rows)


def run_folds_single(ctx: Ctx, rep: int, model_name: str, fold: int, params: dict, seed: int) -> dict:
    fc = fold_cells(ctx, rep)
    s = make_fold_sets(ctx.lab, fc, fold, ctx.rows, ctx.cols, ctx.shape, ctx.radius, 40000, seed + 1000 * rep + fold)
    tr = s["train"]
    m = make_model(model_name, ctx.names, seed + 1000 * rep + fold, params)
    m.fit(_load(ctx.X, tr), (ctx.lab[tr] == POSITIVE).astype(int))
    ids = s["test_all"]
    return inclusive_metrics(ctx, ids, _score(m, ctx.X, ids, list(range(len(ctx.names)))), seed)


def write_csv(df: pd.DataFrame, path: Path) -> None:
    with atomic_write(path, "w") as fh:
        df.to_csv(fh, index=False)
