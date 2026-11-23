import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from mpm.evaluate import (bootstrap_counts, boot_metrics, ci, group_stats, point_estimates,  # noqa: E402
                          positive_percentiles)


def _toy():
    # one fold, 100 cells: cells 0-4 positives (lab 2), cell 5 ring (3), rest background (1)
    lab = np.ones(100, dtype=int)
    lab[:5] = 2
    lab[5] = 3
    return lab, np.zeros(100, dtype=int)


def test_perfect_scores_give_percentile_one():
    lab, fc = _toy()
    score = np.where(lab == 2, 10.0, np.random.default_rng(0).random(100))
    p = positive_percentiles(score, lab, fc, 1)
    assert (p.pct == 1.0).all()


def test_ring_cells_count_as_unlabeled_and_hurt_the_score():
    lab, fc = _toy()
    score = np.where(lab == 2, 1.0, 0.0)
    score[5] = 5.0  # the ring cell outranks every positive
    p = positive_percentiles(score, lab, fc, 1)
    assert np.allclose(p.pct, 94 / 95)  # beats the 94 background cells, loses to the ring cell


def test_constant_score_gives_half():
    lab, fc = _toy()
    assert np.allclose(positive_percentiles(np.zeros(100), lab, fc, 1).pct, 0.5)


def test_group_stats_and_estimates():
    pct = pd.DataFrame({"cell": [0, 1, 2, 3], "pct": [1.0, 0.99, 0.96, 0.5], "fold": 0})
    blk = np.array([1, 1, 2, 2])
    gs = group_stats(pct, blk)
    est = point_estimates(gs)
    assert est["n_pos"] == 4 and abs(est["roc_auc"] - np.mean([1.0, 0.99, 0.96, 0.5])) < 1e-12
    assert est["recall_top1pct"] == 0.5 and est["recall_top5pct"] == 0.75


def test_bootstrap_ci_brackets_estimate_and_is_reproducible():
    rng = np.random.default_rng(3)
    pct = pd.DataFrame({"cell": np.arange(60), "pct": rng.uniform(0.6, 1.0, 60), "fold": 0})
    blk = np.repeat(np.arange(12), 5)
    gs = group_stats(pct, blk)
    c1, c2 = bootstrap_counts(len(gs), 500, 1), bootstrap_counts(len(gs), 500, 1)
    assert np.array_equal(c1, c2) and (c1.sum(axis=1) == len(gs)).all()
    lo, hi = ci(boot_metrics(gs, c1)["roc_auc"])
    assert lo < point_estimates(gs)["roc_auc"] < hi


def test_paired_difference_of_identical_models_is_zero():
    pct = pd.DataFrame({"cell": np.arange(20), "pct": np.linspace(0.5, 1, 20), "fold": 0})
    gs = group_stats(pct, np.repeat(np.arange(4), 5))
    counts = bootstrap_counts(len(gs), 200, 0)
    d = boot_metrics(gs, counts)["roc_auc"] - boot_metrics(gs, counts)["roc_auc"]
    assert np.allclose(d, 0)
