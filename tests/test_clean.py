import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from mpm.clean import clean_array, common_mask  # noqa: E402


def test_common_mask_requires_all_layers():
    a = np.array([[1.0, np.nan], [3.0, 4.0]])
    b = np.array([[1.0, 2.0], [np.nan, 4.0]])
    assert common_mask({"a": a, "b": b}).tolist() == [[True, False], [False, True]]


def test_radiometric_negatives_become_zero_and_spikes_are_capped():
    rng = np.random.default_rng(0)
    arr = rng.gamma(2.0, 5.0, size=(100, 100)).astype("float32")
    arr[0, 0] = -3.0
    arr[1, 1] = 5000.0
    mask = np.ones(arr.shape, bool)
    out, log = clean_array("U_FIN", arr, mask)
    assert out[0, 0] == 0.0 and log["n_negative_set_to_zero"] == 1
    assert out[1, 1] <= log["cap_high"] < 5000.0
    assert out.min() >= 0


def test_magnetic_is_centred_and_outside_mask_stays_nan():
    arr = np.full((10, 10), 52400.0, dtype="float32")
    arr[5, 5] = 80000.0
    mask = np.ones(arr.shape, bool)
    mask[0, 0] = False
    out, log = clean_array("RTP", arr, mask)
    assert np.isnan(out[0, 0])
    assert abs(float(np.nanmedian(out))) < 1e-3 and log["median_subtracted"] == 52400.0
