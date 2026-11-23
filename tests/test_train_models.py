import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from mpm.metrics import ranking_metrics, recall_at_frac  # noqa: E402
from mpm.models import Prep, make_model  # noqa: E402
from mpm.train import buffer_mask, make_fold_sets  # noqa: E402

NAMES = ["a", "b", "geo_is_sedimentary_clastic", "geo_is_rare", "str_dist_fault_m", "rad_U"]


def test_perfect_and_constant_scores():
    y = np.array([0] * 95 + [1] * 5)
    perfect = ranking_metrics(y, y.astype(float), fracs=(0.05,))
    assert perfect["roc_auc"] == 1.0 and perfect["pr_auc"] == 1.0
    assert perfect["recall_top5pct"] == 1.0 and perfect["lift_top5pct"] == 20.0
    const = ranking_metrics(y, np.zeros(100), fracs=(0.05,))
    assert const["roc_auc"] == 0.5 and abs(const["pr_auc"] - 0.05) < 1e-9


def test_constant_score_recall_is_about_chance():
    rng = np.random.default_rng(0)
    y = (rng.random(20000) < 0.01).astype(int)
    assert abs(recall_at_frac(y, np.zeros(y.size), 0.1, seed=123) - 0.1) < 0.05


def test_ranking_needs_both_classes():
    with pytest.raises(ValueError):
        ranking_metrics(np.zeros(10), np.arange(10.0))


def test_buffer_mask_radius():
    m = buffer_mask((21, 21), np.array([10]), np.array([10]), 3)
    assert m[10, 13] and not m[10, 14] and m.sum() == 29


def test_prep_fits_on_train_only_and_drops_rare_dummies():
    rng = np.random.default_rng(1)
    X = rng.normal(size=(1000, 6))
    X[:, 2] = (rng.random(1000) < 0.5).astype(float)
    X[:, 3] = 0.0
    X[:5, 3] = 1.0  # 0.5 % -> kept at the threshold? 5/1000 = 0.005
    X[:2, 3] = 0.0  # now 0.3 % -> dropped
    p = Prep(NAMES).fit(X)
    assert "geo_is_rare" not in p.kept_names and "geo_is_sedimentary_clastic" in p.kept_names
    T = p.transform(X)
    assert abs(T[:, 0].mean()) < 0.05
    big = X.copy()
    big[0, 0] = 1e9  # an extreme unseen value is clipped, not propagated
    assert np.abs(p.transform(big)).max() < 10


def test_every_model_fits_and_scores():
    rng = np.random.default_rng(2)
    X = rng.normal(size=(600, 6))
    X[:, 4] = np.abs(X[:, 4]) * 3000
    y = (X[:, 5] + rng.normal(size=600) * 0.5 > 1.5).astype(int)
    for name in ["prevalence", "rule_geology", "single_rad_U", "logreg", "rf", "et", "hgb"]:
        s = make_model(name, NAMES, 0).fit(X, y).score(X)
        assert s.shape == (600,) and np.isfinite(s).all()
    assert ranking_metrics(y, make_model("single_rad_U", NAMES, 0).score(X))["roc_auc"] > 0.9


def test_fold_sets_have_no_test_cells_in_training_and_respect_buffer():
    h = w = 40
    rows, cols = np.indices((h, w))
    rows, cols = rows.ravel(), cols.ravel()
    lab = np.ones(rows.size, dtype=int)
    fold_cell = (cols >= 20).astype(int)  # fold 1 = right half is the test set
    for r, c in [(10, 15), (10, 19), (10, 21), (30, 30)]:
        lab[r * w + c] = 2
    s = make_fold_sets(lab, fold_cell, 1, rows, cols, (h, w), radius_cells=3, n_bg=50, seed=0)
    assert not set(s["train"]) & set(s["test_all"])
    train_pos = {(rows[i], cols[i]) for i in s["train"] if lab[i] == 2}
    assert (10, 19) not in train_pos and (10, 15) in train_pos  # 2 cells from a test positive: dropped; 6: kept
    assert s["info"]["n_test_pos"] == 2 and s["info"]["n_train_bg"] == 50
    assert s["info"]["n_train_pos_removed_by_buffer"] == 1
