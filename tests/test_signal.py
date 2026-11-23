import sys
from pathlib import Path

import numpy as np
import rasterio

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from mpm.signal import auc_vs_background, sample_cells  # noqa: E402


def test_auc_perfect_and_worst_and_chance():
    bg = np.sort(np.arange(100, dtype=float))
    assert auc_vs_background(np.array([1000.0]), bg) == 1.0
    assert auc_vs_background(np.array([-5.0]), bg) == 0.0
    rng = np.random.default_rng(0)
    big = np.sort(rng.normal(size=100000))
    assert abs(auc_vs_background(rng.normal(size=2000), big) - 0.5) < 0.03  # no signal -> about 0.5


def test_auc_ties_count_half():
    bg = np.sort(np.array([1.0, 1.0, 1.0, 1.0]))
    assert auc_vs_background(np.array([1.0]), bg) == 0.5


def test_sample_cells_nodata_and_outside():
    arr = np.array([[1.0, np.nan], [3.0, 4.0]], dtype="float32")
    tr = rasterio.Affine(50, 0, 0, 0, -50, 100)  # origin top-left (0, 100), 50 m cells
    v = sample_cells(arr, tr, [10, 60, 10, 500], [90, 90, 10, 10])
    assert v[0] == 1.0 and np.isnan(v[1]) and v[2] == 3.0 and np.isnan(v[3])
