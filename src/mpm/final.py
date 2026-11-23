"""Phase 10: refit the chosen model (logistic regression) on ALL data and build the serving artefacts.

Outputs in models/final/:
  logreg_final.joblib   the fitted model (preprocessor + classifier) - identical code path to training
  serving.npz           everything the API/app need, so neither needs the 677 MB feature file:
                        per-cell final score (logit), within-map percentile, Phase 9 disagreement, per-group linear
                        contributions, distance to survey edge, cover flag, grid geometry, known positives
  metadata.json         what was trained on, with which inputs, honest (out-of-fold) metrics, limitations

Honesty rules (see docs/phases/phase-10-final-model.md):
  * the final model has seen every positive, so its map is IN-SAMPLE at the known positives; every performance number
    quoted anywhere comes from the out-of-fold Phase 8 evaluation, never from this map;
  * calibration comes from the Phase 9 out-of-fold bins and is a labelled-positive density, not a deposit probability.
"""
from __future__ import annotations

import json
import logging
import platform
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import rasterio
import sklearn
from scipy import ndimage as ndi
from scipy.stats import rankdata

from .evaluate import Ctx
from .labels import BACKGROUND, POSITIVE
from .models import make_model
from .runner import atomic_write, file_hash
from .train import CHUNK, _load

log = logging.getLogger(__name__)
GROUP_ORDER = ["neighbourhood", "radiometric", "magnetic", "terrain", "structure", "geology"]
COVER_FEATURES = ["geo_is_unconsolidated_undifferentiated", "geo_is_unconsolidated_and_sedimentary_undifferentiated"]
LIMITATIONS = [
    "Ranks cells by the local radiometric uranium neighbourhood; adds modest value over the raw uranium count (gate G4 not met).",
    "Calibrated values are the labelled-positive density from out-of-fold bins, a lower bound on true prospectivity, never a deposit probability.",
    "Trained on 199 occurrence cells, half of them mine records, mostly in two districts; transfer to other geology or surveys is untested.",
    "Small districts are predicted poorly (e.g. a 13-occurrence district: recall in the top 5 % about 0.15).",
    "Radiometrics see only the top 30-50 cm: mineralisation under cover is invisible. Roads and infrastructure were not tested.",
    "The map is in-sample at the known occurrences; quoted performance is out-of-fold only.",
]


def fit_final(ctx: Ctx, seed: int, n_bg: int):
    rng = np.random.default_rng(seed)
    pos = np.flatnonzero(ctx.lab == POSITIVE)
    bg = rng.choice(np.flatnonzero(ctx.lab == BACKGROUND), n_bg, replace=False)
    tr = np.sort(np.concatenate([pos, bg]))
    y = (ctx.lab[tr] == POSITIVE).astype(int)
    m = make_model("logreg", ctx.names, seed).fit(_load(ctx.X, tr), y)
    return m, int(y.sum()), int(y.size - y.sum())


def score_all(ctx: Ctx, model) -> tuple[np.ndarray, np.ndarray]:
    """Per-cell logit and per-group linear contributions (float16), in the order of GROUP_ORDER."""
    w = model.est.coef_[0]
    b = float(model.est.intercept_[0])
    kept = list(model.prep.keep)
    cols_of = [[j for j, k in enumerate(kept) if k in set(ctx.groups[g])] for g in GROUP_ORDER]
    n = ctx.rows.size
    logit = np.empty(n, dtype="float32")
    contrib = np.empty((n, len(GROUP_ORDER)), dtype="float16")
    for i in range(0, n, CHUNK):
        ids = np.arange(i, min(i + CHUNK, n))
        Z = model.prep.transform(_load(ctx.X, ids))
        logit[ids] = Z @ w + b
        for g, cols in enumerate(cols_of):
            contrib[ids, g] = Z[:, cols] @ w[cols]
    return logit, contrib


def build_serving(ctx: Ctx, model, labels_tif: Path, master_mask: Path, unc_tif: Path, positives_csv: Path,
                  out_npz: Path) -> dict:
    logit, contrib = score_all(ctx, model)
    pct = ((rankdata(logit) - 0.5) / logit.size).astype("float32")
    with rasterio.open(unc_tif) as r:
        unc = r.read(1)[ctx.rows, ctx.cols].astype("float32")
    with rasterio.open(master_mask) as r:
        mask = r.read(1) > 0
    edge_km = (ndi.distance_transform_edt(mask) * ctx.cell_m / 1000.0)[ctx.rows, ctx.cols].astype("float16")
    cover = np.zeros(ctx.rows.size, bool)
    for nme in COVER_FEATURES:
        cover |= np.asarray(ctx.X[ctx.names.index(nme), :]) > 0.5
    with rasterio.open(labels_tif) as r:
        tr, crs = r.transform, r.crs.to_string()
    pos = pd.read_csv(positives_csv)
    arrays = dict(rows=ctx.rows.astype("int32"), cols=ctx.cols.astype("int32"), logit=logit, pct=pct, unc=unc,
                  contrib=contrib, edge_km=edge_km, cover=cover, shape=np.array(ctx.shape),
                  transform=np.array(tr)[:6], crs=np.array(crs), group_order=np.array(GROUP_ORDER),
                  group_mean=contrib.astype("float64").mean(axis=0),
                  pos_cell_row=ctx.rows[ctx.lab == POSITIVE].astype("int32"),
                  pos_cell_col=ctx.cols[ctx.lab == POSITIVE].astype("int32"),
                  pos_is_producer=ctx.is_prod[ctx.lab == POSITIVE])
    with atomic_write(out_npz, "wb") as fh:
        np.savez_compressed(fh, **arrays)
    return {"n_cells": int(logit.size), "n_positives_in_map": int(len(pos))}


def run_final(ctx: Ctx, features_dir: Path, labels_tif: Path, master_mask: Path, unc_tif: Path, positives_csv: Path,
              reports: Path, input_files: list[Path], out_dir: Path, seed: int, n_bg: int) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    model, n_pos, n_neg = fit_final(ctx, seed, n_bg)
    with atomic_write(out_dir / "logreg_final.joblib", "wb") as fh:
        joblib.dump(model, fh)
    info = build_serving(ctx, model, labels_tif, master_mask, unc_tif, positives_csv, out_dir / "serving.npz")
    ci = pd.read_csv(reports / "phase8_cv_inclusive_ci.csv")
    ci = ci[ci.model.isin(["logreg", "single_rad_U"])].to_dict("records")
    bins = pd.read_csv(reports / "phase9_calibration_bins.csv").to_dict("records")
    names = [ctx.names[k] for k in model.prep.keep]
    coef = dict(zip(names, map(float, model.est.coef_[0])))
    meta = {"created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "model": "logistic regression (C=0.05, balanced)",
            "seed": seed, "n_train_positives": n_pos, "n_train_background": n_neg,
            "features_total": len(ctx.names), "features_used": len(names), "features_dropped_rare": sorted(set(ctx.names) - set(names)),
            "intercept": float(model.est.intercept_[0]), "coefficients_standardised": coef,
            "versions": {"python": platform.python_version(), "sklearn": sklearn.__version__, "numpy": np.__version__},
            "input_hashes": {p.name: file_hash(p) for p in input_files},
            "out_of_fold_performance_inclusive_phase8": ci,
            "calibration_bins_out_of_fold_phase9": bins,
            "gate_G4_met": False, "limitations": LIMITATIONS,
            "wording_rule": "values are relative rankings and labelled-positive densities, not probabilities of a deposit",
            **info}
    with atomic_write(out_dir / "metadata.json", "w") as fh:
        json.dump(meta, fh, indent=2)
    log.info("final model fitted on %d positives and %d background cells", n_pos, n_neg)
    return meta
