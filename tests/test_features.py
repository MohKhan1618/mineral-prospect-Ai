import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from mpm.features import (contact_mask, distance_to_lines, fill_nearest, log_ratio, masked_mean_std,  # noqa: E402
                          slope_degrees)


def test_fill_nearest_replaces_nan_only():
    a = np.array([[1.0, np.nan], [3.0, 4.0]])
    out = fill_nearest(a)
    assert np.isfinite(out).all() and out[0, 0] == 1.0 and out[1, 1] == 4.0


def test_masked_mean_ignores_cells_outside_mask():
    a = np.full((9, 9), 10.0)
    mask = np.ones((9, 9), dtype=bool)
    a[0, :] = 1000.0
    mask[0, :] = False  # huge values are outside the mask and must not leak into the mean
    mean, std = masked_mean_std(a, mask, 5)
    assert np.allclose(mean[mask], 10.0) and np.allclose(std[mask], 0.0, atol=1e-3)


def test_slope_of_plane_is_known():
    # rises 50 m per 50 m cell eastwards -> 45 degrees
    dem = np.tile(np.arange(10) * 50.0, (10, 1))
    assert np.allclose(slope_degrees(dem, 50.0), 45.0, atol=1e-3)
    assert np.allclose(slope_degrees(np.full((6, 6), 100.0), 50.0), 0.0)


def test_log_ratio_defined_at_zero_denominator_and_symmetric():
    a, b = np.array([0.0, 5.0]), np.array([0.0, 0.0])
    r = log_ratio(a, b)
    assert np.isfinite(r).all() and r[0] == 0.0
    assert np.allclose(log_ratio(a, b), -log_ratio(b, a))


def test_distance_to_lines_in_metres():
    m = np.zeros((5, 5), dtype=bool)
    m[2, 0] = True
    d = distance_to_lines(m, 50.0)
    assert d[2, 0] == 0 and d[2, 3] == 150.0


def test_contact_mask_ignores_unmapped():
    cls = np.array([[1, 1, 2, 2], [1, 1, 2, 0], [0, 0, 0, 0]])
    c = contact_mask(cls)
    assert c[0, 1] and c[0, 2] and not c[0, 0]
    assert not c[2].any() and not c[1, 3]  # boundary against unmapped 0 is not a contact
