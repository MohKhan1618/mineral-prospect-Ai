import json
import sys
from pathlib import Path

import numpy as np
import pytest
from pyproj import Transformer

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from fastapi.testclient import TestClient  # noqa: E402

from mpm.api import create_app  # noqa: E402
from mpm.serve import Store  # noqa: E402

A, C, F = 50.0, 159850.0, 4744400.0
BINS = [{"bin": n, "observed_rate": r, "obs_lo": r / 2, "obs_hi": r * 2, "lift_vs_prevalence": r / 6e-5}
        for n, r in zip(["top 0.1%", "top 1%", "top 5%", "top 10%", "top 25%", "top 50%", "rest"],
                        [5e-3, 2e-3, 2e-4, 1e-4, 4e-5, 2e-5, 1e-5])]


def _fake_dir(tmp_path, n=60):
    rng = np.random.default_rng(0)
    rows, cols = np.meshgrid(np.arange(n), np.arange(n), indexing="ij")
    rows, cols = rows.ravel()[::2], cols.ravel()[::2]          # checkerboard-ish: some cells invalid
    m = rows.size
    pct = ((np.argsort(np.argsort(rng.normal(size=m))) + 0.5) / m).astype("float32")
    np.savez_compressed(tmp_path / "serving.npz", rows=rows.astype("int32"), cols=cols.astype("int32"),
                        logit=rng.normal(size=m).astype("float32"), pct=pct, unc=rng.uniform(0, 0.2, m).astype("float32"),
                        contrib=rng.normal(size=(m, 6)).astype("float16"), edge_km=rng.uniform(0, 5, m).astype("float16"),
                        cover=rng.uniform(size=m) < 0.1, shape=np.array([n, n]), transform=np.array([A, 0, C, 0, -A, F]),
                        crs=np.array("EPSG:32613"), group_order=np.array(["neighbourhood", "radiometric", "magnetic", "terrain",
                                                                          "structure", "geology"]),
                        group_mean=np.zeros(6), pos_cell_row=np.array([2, 10], "int32"), pos_cell_col=np.array([2, 10], "int32"),
                        pos_is_producer=np.array([True, False]))
    json.dump({"calibration_bins_out_of_fold_phase9": BINS, "created_utc": "x", "model": "m", "n_train_positives": 1,
               "n_train_background": 1, "features_used": 1, "versions": {}, "out_of_fold_performance_inclusive_phase8": [],
               "gate_G4_met": False, "limitations": ["l"], "wording_rule": "w"}, open(tmp_path / "metadata.json", "w"))
    return tmp_path, rows, cols


def _lonlat(row, col):
    return Transformer.from_crs("EPSG:32613", "EPSG:4326", always_xy=True).transform(C + (col + 0.5) * A, F - (row + 0.5) * A)


def test_point_roundtrip_and_fields(tmp_path):
    d, rows, cols = _fake_dir(tmp_path)
    s = Store(d)
    lon, lat = _lonlat(rows[5], cols[5])
    out = s.point(lon, lat)
    assert out["percentile"] == pytest.approx(float(s.pct[5]))
    assert out["bin"] == s.bins[s.bin_index(out["percentile"])]["bin"]
    assert abs(out["cell_centre"]["lon"] - lon) < 1e-9 and abs(out["cell_centre"]["lat"] - lat) < 1e-9
    assert len(out["top_drivers"]) == 3
    assert "NOT the probability of a deposit" in out["disclaimer"]


def test_bins_follow_percentile_edges(tmp_path):
    s = Store(_fake_dir(tmp_path)[0])
    assert [s.bin_index(p) for p in (0.9995, 0.995, 0.97, 0.92, 0.8, 0.6, 0.1)] == [0, 1, 2, 3, 4, 5, 6]


def test_outside_and_invalid_cells_return_none(tmp_path):
    d, rows, cols = _fake_dir(tmp_path)
    s = Store(d)
    assert s.point(0.0, 0.0) is None
    all_valid = set(zip(rows.tolist(), cols.tolist()))
    free = next((a, b) for a in range(60) for b in range(60) if (a, b) not in all_valid)
    assert s.point(*_lonlat(*free)) is None


def test_bbox_summary_counts_cells_and_known_positives(tmp_path):
    d, rows, cols = _fake_dir(tmp_path)
    s = Store(d)
    lo1, la1 = _lonlat(30, 0)      # lower-left-ish
    lo2, la2 = _lonlat(0, 30)
    out = s.bbox(min(lo1, lo2), min(la1, la2), max(lo1, lo2), max(la1, la2), top_n=5)
    assert 0 < out["n_cells"] <= 30 * 30 and len(out["top_cells"]) == 5
    assert out["top_cells"][0]["percentile"] >= out["top_cells"][-1]["percentile"]
    assert out["known_occurrence_cells_inside"] >= 1
    assert s.bbox(10.0, 10.0, 11.0, 11.0) is None


def test_api_endpoints_and_validation(tmp_path):
    d, rows, cols = _fake_dir(tmp_path)
    c = TestClient(create_app(d))
    assert c.get("/health").json() == {"status": "ok"}
    assert c.get("/model-info").json()["gate_G4_met"] is False
    lon, lat = _lonlat(rows[3], cols[3])
    r = c.post("/predict/point", json={"lon": lon, "lat": lat})
    assert r.status_code == 200 and 0 <= r.json()["percentile"] <= 1
    assert c.post("/predict/point", json={"lon": 0, "lat": 0}).status_code == 404
    assert c.post("/predict/point", json={"lon": 500, "lat": 0}).status_code == 422
    assert c.post("/predict/bbox", json={"min_lon": 1, "min_lat": 1, "max_lon": 0, "max_lat": 2}).status_code == 422
    assert c.post("/predict/bbox", json={"min_lon": 10, "min_lat": 10, "max_lon": 11, "max_lat": 11}).status_code == 404


def test_api_reports_missing_model(tmp_path):
    c = TestClient(create_app(tmp_path))
    assert c.get("/health").json() == {"status": "model_missing"}
    assert c.post("/predict/point", json={"lon": -108, "lat": 42.5}).status_code == 503


# ---- reproducibility against the real artefacts (skipped when they are not built) ----
FINAL = ROOT / "models" / "final"


@pytest.mark.skipif(not (FINAL / "serving.npz").exists() or not (ROOT / "data/features/features.npy").exists(),
                    reason="final model not built")
def test_saved_model_reproduces_serving_scores_and_reloads_identically():
    import joblib

    from mpm.features import load_features
    from mpm.train import _load

    X, idx, names = load_features(ROOT / "data" / "features")
    s = Store(FINAL)
    ids = np.sort(np.random.default_rng(3).choice(X.shape[1], 3000, replace=False))
    m1, m2 = joblib.load(FINAL / "logreg_final.joblib"), joblib.load(FINAL / "logreg_final.joblib")
    z = m1.prep.transform(_load(X, ids))
    logit = z @ m1.est.coef_[0] + m1.est.intercept_[0]
    assert np.allclose(logit, s.logit[ids], atol=1e-4)                       # serving store == model code path
    p1, p2 = m1.score(_load(X, ids)), m2.score(_load(X, ids))
    assert np.array_equal(p1, p2)                                           # reload is bit-identical
    assert np.allclose(1 / (1 + np.exp(-logit)), p1, atol=1e-6)             # logit and probability agree
    assert np.all(np.diff(s.pct[np.argsort(s.logit)][::5000]) >= 0)         # percentile is monotone in the score
    assert s.rows.size == X.shape[1] and 0 < s.pct.min() and s.pct.max() < 1
