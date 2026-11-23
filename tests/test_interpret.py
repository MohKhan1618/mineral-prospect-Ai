import sys
from pathlib import Path

import numpy as np  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from mpm.interpret import fold_percentile, morans_i, pct_of_positives, stripe_ratio


def test_fold_percentile_is_within_fold():
    score = np.array([10.0, 20, 30, 1, 2, 3])
    fc = np.array([0, 0, 0, 1, 1, 1])
    p = fold_percentile(score, fc, 2)
    # each fold ranks independently, so the best cell of both folds gets the same percentile
    assert p[2] == p[5] and p[0] == p[3]
    assert np.allclose(p[:3], [1 / 6, 0.5, 5 / 6])


def test_pct_of_positives_exact():
    score = np.array([5.0, 0.0, 1.0, 2.0, 3.0, 4.0])
    is_pos = np.array([True, False, False, False, False, False])
    # positive scores 5; 5 unlabeled cells all lower -> percentile 1.0
    assert pct_of_positives(score, is_pos)[0] == 1.0
    score[0] = 2.0   # ties with one unlabeled cell: 2 below, 1 tied -> (2 + 3) / 2 / 5
    assert pct_of_positives(score, is_pos)[0] == 0.5


def test_morans_i_detects_clustering_and_randomness():
    rng = np.random.default_rng(0)
    xy = rng.uniform(0, 100, (300, 2))
    clustered = xy[:, 0] / 100.0 + rng.normal(0, 0.02, 300)       # smooth trend in space
    assert morans_i(clustered, xy, 5, 199, 1)["I"] > 0.8
    r = morans_i(rng.uniform(size=300), xy, 5, 199, 1)
    assert abs(r["I"]) < 0.15 and r["p_one_sided"] > 0.05


def test_stripe_ratio_finds_planted_200m_lines_and_not_noise():
    rng = np.random.default_rng(0)
    noise = rng.normal(size=(256, 512)).astype("float32")
    x = np.arange(512)
    stripes = noise + 2.0 * np.sin(2 * np.pi * x / 4.0)[None, :]      # 200 m period at 50 m cells, lines along y
    assert stripe_ratio(stripes, 50.0, (150, 260))["peak_to_median"] > 50
    assert stripe_ratio(noise, 50.0, (150, 260))["peak_to_median"] < 5
    out = stripe_ratio(stripes, 50.0, (150, 260))
    assert out["peak_direction_deg_from_x_axis"] < 10 or out["peak_direction_deg_from_x_axis"] > 170   # wave vector along x


def test_stripe_ratio_ignores_nan_cells():
    rng = np.random.default_rng(1)
    a = rng.normal(size=(128, 256)).astype("float32")
    a[:, :60] = np.nan
    assert np.isfinite(stripe_ratio(a, 50.0, (150, 260))["peak_to_median"])
