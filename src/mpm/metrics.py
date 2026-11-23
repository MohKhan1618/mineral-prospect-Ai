"""Ranking metrics for mineral prospectivity.

The map is used to decide where to look first, so what matters is how well the score RANKS cells:
- ROC-AUC: chance a random positive outranks a random unlabeled cell. Insensitive to the huge class imbalance,
  so it can look good while the top of the ranking is poor.
- PR-AUC (average precision): rewards putting positives at the very top. A random ranking scores about the
  prevalence (here ~6e-5), so even small absolute values can be large multiples of chance.
- recall@top p%: share of positives found if only the top p% of cells are examined.
- lift@top p%: recall@top p% divided by p (1.0 = random, 20 at p=5% = found everything in the top 5%).
Unlabeled cells are not proven barren, so precision-type numbers are lower bounds.
"""
from __future__ import annotations

import numpy as np
from sklearn.metrics import average_precision_score, roc_auc_score


def _order(score: np.ndarray, seed: int = 0) -> np.ndarray:
    """Best-first order, ties broken at random (a constant score then behaves like a random ranking)."""
    rng = np.random.default_rng(seed)
    return np.lexsort((rng.random(score.size), -score))


def recall_at_frac(y: np.ndarray, score: np.ndarray, frac: float, seed: int = 0) -> float:
    n_top = max(1, int(np.ceil(frac * y.size)))
    return float(y[_order(score, seed)[:n_top]].sum() / y.sum())


def ranking_metrics(y: np.ndarray, score: np.ndarray, fracs=(0.01, 0.05), seed: int = 0) -> dict:
    y = np.asarray(y).astype(int)
    score = np.asarray(score, dtype="float64")
    if y.sum() == 0 or y.sum() == y.size:
        raise ValueError("need both positives and unlabeled cells to compute ranking metrics")
    out = {"n_eval": int(y.size), "n_pos": int(y.sum()), "prevalence": float(y.mean()),
           "roc_auc": float(roc_auc_score(y, score)), "pr_auc": float(average_precision_score(y, score))}
    out["pr_auc_over_prevalence"] = out["pr_auc"] / out["prevalence"]
    order = _order(score, seed)
    csum = np.cumsum(y[order])
    for f in fracs:
        n_top = max(1, int(np.ceil(f * y.size)))
        r = float(csum[n_top - 1] / y.sum())
        tag = f"{round(f * 100):d}pct"
        out[f"recall_top{tag}"] = r
        out[f"lift_top{tag}"] = r / f
    return out
