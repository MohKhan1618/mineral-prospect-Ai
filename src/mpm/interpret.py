"""Phase 9: interpretation, calibration, uncertainty and artefact checks for the chosen candidate (logreg).

Rules were written first: docs/phases/phase-09-decision-rule.md. Every stage writes one file and is safe to re-run.
Quantitative tables use repeat 0 (the frozen block folds) so that "hit" always means the same thing.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

import numpy as np
import pandas as pd
import rasterio
from scipy import ndimage as ndi
from scipy.fft import fftfreq, rfft2, rfftfreq
from scipy.signal.windows import hann
from scipy.spatial import cKDTree
from scipy.stats import rankdata, spearmanr
from sklearn.linear_model import LogisticRegression

from . import experiments as ex
from .evaluate import Ctx, bootstrap_counts, ci, fold_cells
from .labels import POSITIVE
from .models import make_model
from .runner import atomic_write
from .train import _load, make_fold_sets

log = logging.getLogger(__name__)
BIN_EDGES = [0.999, 0.99, 0.95, 0.90, 0.75, 0.50, 0.0]            # percentile lower edges, best bin first
BIN_NAMES = ["top 0.1%", "top 1%", "top 5%", "top 10%", "top 25%", "top 50%", "rest"]


def write_json(obj, path: Path) -> None:
    with atomic_write(path, "w") as fh:
        json.dump(obj, fh, indent=2, default=float)


# ---------- small tested helpers ----------
def fold_percentile(score: np.ndarray, fc: np.ndarray, n_folds: int) -> np.ndarray:
    """Percentile of each cell among the cells of its own fold (ties averaged); scores of different folds
    are not comparable, percentiles are."""
    out = np.full(score.size, np.nan)
    for f in range(n_folds):
        m = np.flatnonzero(fc == f)
        out[m] = (rankdata(score[m]) - 0.5) / m.size
    return out


def pct_of_positives(score: np.ndarray, is_pos: np.ndarray) -> np.ndarray:
    """Percentile of each positive among the unlabeled cells of the same sample."""
    un = np.sort(score[~is_pos])
    v = score[is_pos]
    return (np.searchsorted(un, v, "left") + np.searchsorted(un, v, "right")) / 2 / un.size


def morans_i(values: np.ndarray, xy: np.ndarray, k: int = 5, n_perm: int = 999, seed: int = 0) -> dict:
    """Moran's I with k-nearest-neighbour row-standardised weights and a permutation p-value (one-sided, I large)."""
    n = len(values)
    _, nn = cKDTree(xy).query(xy, k=k + 1)
    nn = nn[:, 1:]
    z = values - values.mean()
    den = (z ** 2).sum()

    def stat(zz):
        return float((zz * zz[nn].mean(axis=1)).sum() / den)

    obs = stat(z)
    rng = np.random.default_rng(seed)
    perm = np.array([stat(rng.permutation(z)) for _ in range(n_perm)])
    return {"I": obs, "expected_I": -1.0 / (n - 1), "p_one_sided": float((1 + (perm >= obs).sum()) / (n_perm + 1)), "n": n}


def stripe_ratio(arr: np.ndarray, cell_m: float, wl_m: tuple[float, float], n_sec: int = 36) -> dict:
    """Peak-to-median power over direction, within a wavelength band, of the 2-D spectrum of a map.
    NaN cells are set to the mean (no signal), a Hann window limits edge leakage."""
    a = np.where(np.isfinite(arr), arr, np.nan)
    a = np.nan_to_num(a - np.nanmean(a), nan=0.0).astype("float32")
    a *= np.outer(hann(a.shape[0]), hann(a.shape[1])).astype("float32")
    P = np.abs(rfft2(a)) ** 2
    ky, kx = fftfreq(a.shape[0])[:, None], rfftfreq(a.shape[1])[None, :]
    r = np.hypot(kx, ky)
    ang = np.arctan2(ky, kx) % np.pi
    band = (r >= cell_m / wl_m[1]) & (r <= cell_m / wl_m[0])
    sec = (ang / np.pi * n_sec).astype(int) % n_sec
    power = np.bincount(sec[band], P[band].astype("float64"), minlength=n_sec)
    return {"peak_to_median": float(power.max() / max(np.median(power), 1e-30)),
            "peak_direction_deg_from_x_axis": float((int(power.argmax()) + 0.5) * 180.0 / n_sec)}


# ---------- 1. importance and attribution ----------
def importance(ctx: Ctx, rep: int, seed: int, n_perm: int, n_unl: int, out_imp: Path, out_coef: Path,
               out_attr: Path) -> None:
    fc = fold_cells(ctx, rep)
    rows_imp, rows_coef, rows_attr = [], [], []
    for f in range(ctx.n_folds):
        s = make_fold_sets(ctx.lab, fc, f, ctx.rows, ctx.cols, ctx.shape, ctx.radius, 40000, seed + 1000 * rep + f)
        tr = s["train"]
        m = make_model("logreg", ctx.names, seed + 1000 * rep + f).fit(_load(ctx.X, tr), (ctx.lab[tr] == POSITIVE).astype(int))
        prep, w, b = m.prep, m.est.coef_[0], float(m.est.intercept_[0])
        kept = list(prep.keep)
        test = fc == f
        pos = np.flatnonzero(test & (ctx.lab == POSITIVE))
        rng = np.random.default_rng(seed + 31 * f)
        unl = rng.choice(np.flatnonzero(test & (ctx.lab != POSITIVE) & (ctx.lab > 0)), n_unl, replace=False)
        ids = np.concatenate([pos, unl])
        is_pos = np.r_[np.ones(pos.size, bool), np.zeros(unl.size, bool)]
        Z = prep.transform(_load(ctx.X, ids))
        base = Z @ w + b

        def metrics(logit):
            p = pct_of_positives(logit, is_pos)
            return float(p.sum()), float((p >= 0.95).sum())

        configs = {f"group:{g}": [j for j, k in enumerate(kept) if k in set(ix)] for g, ix in ctx.groups.items()}
        configs.update({f"feature:{ctx.names[k]}": [j] for j, k in enumerate(kept)})
        s0, h0 = metrics(base)
        rows_imp.append({"config": "baseline", "perm": -1, "fold": f, "n_pos": pos.size, "sum_pct": s0, "hits5": h0})
        for name, cols in configs.items():
            if not cols:
                continue
            part = Z[:, cols] @ w[cols]
            for k in range(n_perm):
                perm = np.random.default_rng(seed + 7000 * (k + 1) + f).permutation(Z.shape[0])
                sp, hp = metrics(base - part + Z[perm][:, cols] @ w[cols])
                rows_imp.append({"config": name, "perm": k, "fold": f, "n_pos": pos.size, "sum_pct": sp, "hits5": hp})
        for j, k in enumerate(kept):
            rows_coef.append({"fold": f, "feature": ctx.names[k], "coef": float(w[j])})
        contrib = Z * w
        cp, cu = contrib[is_pos].mean(axis=0), contrib[~is_pos].mean(axis=0)
        for j, k in enumerate(kept):
            rows_attr.append({"fold": f, "feature": ctx.names[k], "n_pos": pos.size, "pos_contrib": float(cp[j]),
                              "unl_contrib": float(cu[j])})
        log.info("importance fold %d done", f)
    d = pd.DataFrame(rows_imp)
    base = d[d.config == "baseline"][["fold", "sum_pct", "hits5", "n_pos"]].set_index("fold")
    d = d[d.config != "baseline"].join(base, on="fold", rsuffix="_base")
    g = d.groupby(["config", "perm"]).agg(sum_pct=("sum_pct", "sum"), hits5=("hits5", "sum"), s0=("sum_pct_base", "sum"),
                                          h0=("hits5_base", "sum"), n=("n_pos", "sum")).reset_index()
    g["drop_roc_auc"], g["drop_recall5"] = (g.s0 - g.sum_pct) / g.n, (g.h0 - g.hits5) / g.n
    res = g.groupby("config").agg(base_roc_auc=("s0", lambda s: s.iloc[0]), drop_roc_auc=("drop_roc_auc", "mean"),
                                  drop_roc_auc_sd=("drop_roc_auc", "std"), drop_recall5=("drop_recall5", "mean"),
                                  drop_recall5_sd=("drop_recall5", "std"), n=("n", "first")).reset_index()
    res["base_roc_auc"] = res.base_roc_auc / res.n
    res["base_recall5"] = float(base.hits5.sum() / base.n_pos.sum())
    res["used"] = res.drop_recall5 >= 0.03
    ex.write_csv(res.sort_values("drop_recall5", ascending=False), out_imp)
    c = pd.DataFrame(rows_coef)
    cs = c.groupby("feature").coef.agg(["mean", "std", "count", lambda x: float((np.sign(x) == np.sign(x.mean())).mean())])
    cs.columns = ["coef_mean", "coef_sd", "n_folds", "sign_agreement"]
    ex.write_csv(cs.reset_index().sort_values("coef_mean", key=np.abs, ascending=False), out_coef)
    a = pd.DataFrame(rows_attr)
    a["w"] = a.n_pos
    a["group"] = a.feature.map({ctx.names[i]: gname for gname, ix in ctx.groups.items() for i in ix})
    a["diff"] = a.pos_contrib - a.unl_contrib
    byf = a.groupby(["fold", "group"]).agg(diff=("diff", "sum"), pos=("pos_contrib", "sum"), unl=("unl_contrib", "sum"),
                                           w=("w", "first")).reset_index()
    att = byf.groupby("group").apply(lambda x: pd.Series({"mean_positive_minus_typical_logit": np.average(x["diff"], weights=x.w),
                                                         "min_over_folds": x["diff"].min(), "max_over_folds": x["diff"].max()}),
                                     include_groups=False).reset_index()
    ex.write_csv(att.sort_values("mean_positive_minus_typical_logit", ascending=False), out_attr)


# ---------- 2. calibration ----------
def calibration(ctx: Ctx, oof_file: Path, rep: int, seed: int, n_unl: int, n_boot: int, out_bins: Path, out_json: Path) -> None:
    fc = fold_cells(ctx, rep)
    s = np.clip(np.load(oof_file).astype("float64"), 1e-9, 1 - 1e-9)
    z = np.log(s / (1 - s))
    z = (z - z.mean()) / z.std()
    y = (ctx.lab == POSITIVE).astype(float)
    rng = np.random.default_rng(seed)
    unl_all = np.flatnonzero(y == 0)
    samp = rng.choice(unl_all, n_unl, replace=False)
    w_unl = unl_all.size / n_unl
    p = np.empty(z.size)
    p0 = np.empty(z.size)
    for f in range(ctx.n_folds):
        ptr = np.flatnonzero((y == 1) & (fc != f))
        utr = samp[fc[samp] != f]
        lr = LogisticRegression(C=1e6, max_iter=2000).fit(
            z[np.r_[ptr, utr]].reshape(-1, 1), np.r_[np.ones(ptr.size), np.zeros(utr.size)],
            sample_weight=np.r_[np.ones(ptr.size), np.full(utr.size, w_unl)])
        te = fc == f
        p[te] = lr.predict_proba(z[te].reshape(-1, 1))[:, 1]
        p0[te] = ptr.size / (ptr.size + unl_all.size * (fc[unl_all] != f).mean())   # prevalence among training cells
    brier, brier0 = float(np.mean((p - y) ** 2)), float(np.mean((p0 - y) ** 2))
    pct = fold_percentile(z, fc, ctx.n_folds)
    binid = sum((pct < e).astype(int) for e in BIN_EDGES[:-1])   # 0 = top 0.1 % ... 6 = rest
    df = pd.DataFrame({"block": ctx.blk, "bin": binid, "y": y, "p": p})
    g = df.groupby(["block", "bin"]).agg(n=("y", "size"), pos=("y", "sum"), psum=("p", "sum")).reset_index()
    blocks = np.unique(ctx.blk)
    counts = bootstrap_counts(len(blocks), n_boot, seed)
    rows = []
    for b in range(7):
        gb = g[g.bin == b].set_index("block").reindex(blocks).fillna(0.0)
        n, pos, ps = gb.n.values, gb.pos.values, gb.psum.values
        den = counts @ n
        rate_b = np.where(den > 0, (counts @ pos) / np.maximum(den, 1), np.nan)
        lo, hi = ci(rate_b)
        rows.append({"bin": BIN_NAMES[b], "n_cells": int(n.sum()), "n_pos": int(pos.sum()),
                     "observed_rate": float(pos.sum() / n.sum()), "obs_lo": lo, "obs_hi": hi,
                     "mean_calibrated_p": float(ps.sum() / n.sum()), "lift_vs_prevalence": float(pos.sum() / n.sum() / y.mean())})
    bins = pd.DataFrame(rows)
    ex.write_csv(bins, out_bins)
    rates = bins.observed_rate.values            # best bin first -> should be decreasing
    ordered = int(sum(rates[i] > rates[i + 1] for i in range(6)))
    allfit = LogisticRegression(C=1e6, max_iter=2000).fit(
        z[np.r_[np.flatnonzero(y == 1), samp]].reshape(-1, 1), np.r_[np.ones(int(y.sum())), np.zeros(samp.size)],
        sample_weight=np.r_[np.ones(int(y.sum())), np.full(samp.size, w_unl)])
    write_json({"brier": brier, "brier_constant_prevalence": brier0, "brier_skill_score": float(1 - brier / brier0),
                "prevalence": float(y.mean()), "adjacent_bin_pairs_in_order_of_6": ordered,
                "calibration_pass": bool(brier < brier0 and ordered >= 5),
                "platt_all_data": {"slope": float(allfit.coef_[0, 0]), "intercept": float(allfit.intercept_[0]),
                                   "z_mean": float(np.log(s / (1 - s)).mean()), "z_sd": float(np.log(s / (1 - s)).std())},
                "note": "calibrated value = P(cell is a LABELLED positive); lower bound on true prospectivity"}, out_json)


# ---------- 3. maps and uncertainty ----------
def _write_map(path: Path, template: Path, ctx: Ctx, values: np.ndarray) -> None:
    with rasterio.open(template) as r:
        prof = r.profile
    arr = np.full(ctx.shape, np.nan, dtype="float32")
    arr[ctx.rows, ctx.cols] = values
    prof.update(dtype="float32", nodata=np.nan, compress="deflate", count=1)
    path.parent.mkdir(parents=True, exist_ok=True)
    with atomic_write(path, "wb") as fh:
        with rasterio.MemoryFile() as mf:
            with mf.open(**prof) as dst:
                dst.write(arr, 1)
            fh.write(mf.read())


def maps_and_uncertainty(ctx: Ctx, oof_dir: Path, repeats: int, template: Path, out_dir: Path, out_json: Path,
                         out_tercile: Path) -> None:
    fcs = [fold_cells(ctx, r) for r in range(repeats)]
    pct = lambda m, r: fold_percentile(np.load(oof_dir / f"{m}_r{r}.npy").astype("float64"), fcs[r], ctx.n_folds)  # noqa: E731
    lr = [pct("logreg", r) for r in range(repeats)]
    fam = np.vstack([lr[0]] + [pct(m, 0) for m in ("rf", "et", "hgb")])
    unc_a, unc_b = fam.std(axis=0), np.vstack(lr).std(axis=0)
    unc = (unc_a + unc_b) / 2
    mean_score = np.vstack(lr).mean(axis=0)
    _write_map(out_dir / "score_percentile_oof_logreg.tif", template, ctx, mean_score.astype("float32"))
    _write_map(out_dir / "uncertainty_disagreement.tif", template, ctx, unc.astype("float32"))
    isp = ctx.lab == POSITIVE
    up, sp_ = unc[isp], lr[0][isp]
    cut = np.quantile(up, [1 / 3, 2 / 3])
    terc = np.digitize(up, cut)
    tab = pd.DataFrame({"tercile": ["lowest uncertainty", "middle", "highest uncertainty"],
                        "n_pos": [int((terc == t).sum()) for t in range(3)],
                        "mean_percentile": [float(sp_[terc == t].mean()) for t in range(3)],
                        "recall_top5": [float((sp_[terc == t] >= 0.95).mean()) for t in range(3)],
                        "mean_uncertainty": [float(up[terc == t].mean()) for t in range(3)]})
    ex.write_csv(tab, out_tercile)
    sub = np.random.default_rng(0).choice(unc.size, 300000, replace=False)
    gap = float(tab.recall_top5.iloc[0] - tab.recall_top5.iloc[2])
    write_json({"uncertainty_mean": float(unc.mean()), "uncertainty_p95": float(np.quantile(unc, 0.95)),
                "uncertainty_family_mean": float(unc_a.mean()), "uncertainty_repeat_mean": float(unc_b.mean()),
                "spearman_uncertainty_vs_score": float(spearmanr(unc[sub], mean_score[sub])[0]),
                "mean_uncertainty_top5pct_cells": float(unc[lr[0] >= 0.95].mean()),
                "recall5_gap_low_minus_high_uncertainty": gap, "informative_by_rule": bool(gap >= 0.10)}, out_json)


# ---------- 4. artefact and bias checks ----------
def artifacts(ctx: Ctx, rep: int, oof_file: Path, master_mask: Path, oof_dir: Path, repeats: int, out_edge: Path,
              out_cover: Path, out_spec: Path, out_resid: Path, out_worst: Path, out_districts: Path, link_m: float,
              seed: int) -> None:
    fc = fold_cells(ctx, rep)
    pct = fold_percentile(np.load(oof_file).astype("float64"), fc, ctx.n_folds)
    isp = ctx.lab == POSITIVE
    top = pct >= 0.95
    # survey edge
    with rasterio.open(master_mask) as r:
        mask = r.read(1) > 0
    dist_km = (ndi.distance_transform_edt(mask) * ctx.cell_m / 1000.0)[ctx.rows, ctx.cols]
    edges = [0, 1, 2, 5, 10, np.inf]
    lab_e = ["0-1 km", "1-2 km", "2-5 km", "5-10 km", "10+ km"]
    ebin = np.digitize(dist_km, edges[1:-1])
    rows = [{"distance_to_edge": lab_e[b], "area_share": float((ebin == b).mean()), "mean_percentile": float(pct[ebin == b].mean()),
             "top5_share_of_cells": float(top[ebin == b].mean()), "n_pos": int((isp & (ebin == b)).sum()),
             "positive_share": float((isp & (ebin == b)).sum() / isp.sum())} for b in range(5)]
    edge = pd.DataFrame(rows)
    ex.write_csv(edge, out_edge)
    inner = float(pct[ebin >= 1].mean())
    e0 = edge.iloc[0]
    ratio = e0.top5_share_of_cells / 0.05
    edge_flag = bool(abs(e0.mean_percentile - inner) > 0.05 or ratio > 2 or ratio < 0.5)
    # cover
    cov_names = ["geo_is_unconsolidated_undifferentiated", "geo_is_unconsolidated_and_sedimentary_undifferentiated"]
    cover = np.zeros(pct.size, bool)
    for n in cov_names:
        cover |= np.asarray(ctx.X[ctx.names.index(n), :]) > 0.5
    crow = []
    for lab_, m in (("cover (unconsolidated)", cover), ("not cover", ~cover)):
        crow.append({"class": lab_, "area_share": float(m.mean()), "n_pos": int((isp & m).sum()),
                     "positive_share": float((isp & m).sum() / isp.sum()), "top5_share_of_cells": float(top[m].mean()),
                     "positive_recall_top5": float(top[isp & m].mean()) if (isp & m).any() else np.nan,
                     "mean_percentile_of_positives": float(pct[isp & m].mean()) if (isp & m).any() else np.nan})
    ex.write_csv(pd.DataFrame(crow), out_cover)
    # flight-line stripes: map and raw log-uranium grid, target band and a control band
    def to_grid(v):
        g = np.full(ctx.shape, np.nan, dtype="float32")
        g[ctx.rows, ctx.cols] = v
        return g
    mean_map = to_grid(np.vstack([fold_percentile(np.load(oof_dir / f"logreg_r{r}.npy").astype("float64"), fold_cells(ctx, r),
                                                  ctx.n_folds) for r in range(repeats)]).mean(axis=0))
    raw_u = to_grid(np.asarray(ctx.X[ctx.names.index("rad_log_U"), :]))
    spec = {}
    for nm, g in (("score_map", mean_map), ("raw_log_uranium", raw_u)):
        spec[nm] = {"flight_line_band_150_260m": stripe_ratio(g, ctx.cell_m, (150, 260)),
                    "control_band_400_700m": stripe_ratio(g, ctx.cell_m, (400, 700))}
    spec["flag_stripes_in_score_map"] = bool(spec["score_map"]["flight_line_band_150_260m"]["peak_to_median"] > 10)
    write_json(spec, out_spec)
    # residual structure
    pp = pct[isp]
    xy = ctx.xy[isp]
    mi = morans_i(pp, xy, 5, 999, seed)
    cl = ex.district_clusters(ctx, link_m)
    dist_of = dict(zip(cl[0], cl[1]))
    pos_ids = np.flatnonzero(isp)
    dd = pd.DataFrame({"cell": pos_ids, "district": [int(dist_of[c]) for c in pos_ids], "pct": pp,
                       "is_producer": ctx.is_prod[pos_ids], "x": xy[:, 0], "y": xy[:, 1],
                       "rad_U": np.asarray(ctx.X[ctx.names.index("rad_U"), pos_ids]),
                       "nbr_U_mean_1km": np.asarray(ctx.X[ctx.names.index("nbr_U_mean_1km"), pos_ids])})
    ex.write_csv(dd.sort_values("pct").head(15), out_worst)
    big = dd.groupby("district").agg(n_pos=("pct", "size"), n_producers=("is_producer", "sum"), mean_percentile=("pct", "mean"),
                                     median_percentile=("pct", "median"), recall_top5=("pct", lambda v: float((v >= 0.95).mean())),
                                     share_below_median=("pct", lambda v: float((v < 0.5).mean()))).reset_index()
    ex.write_csv(big.sort_values("n_pos", ascending=False), out_districts)
    write_json({"moran": mi, "positives_below_50th_percentile": int((pp < 0.5).sum()), "n_pos": int(pp.size),
                "share_below_50th": float((pp < 0.5).mean()), "edge_flag": edge_flag,
                "edge_zone_top5_over_expected": float(ratio), "edge_mean_pct_minus_interior": float(e0.mean_percentile - inner),
                "cover_area_share": float(cover.mean())}, out_resid)


# ---------- 5. summary of the pre-set rules ----------
def g9_summary(reports: Path, out: Path) -> dict:
    imp = pd.read_csv(reports / "phase9_importance.csv")
    grp = imp[imp.config.str.startswith("group:")].set_index("config")
    proxies = [f"feature:{n}" for n in ("mag_IGRF", "ter_elev", "mag_RTP_mean_5km")]
    proxy_used = {p.split(":")[1]: bool(imp.set_index("config").loc[p, "drop_recall5"] >= 0.03) if p in set(imp.config) else None
                  for p in proxies}
    cal = json.load(open(reports / "phase9_calibration.json"))
    unc = json.load(open(reports / "phase9_uncertainty.json"))
    spec = json.load(open(reports / "phase9_spectrum.json"))
    res = json.load(open(reports / "phase9_residuals.json"))
    out_d = {"groups_used_drop_recall5_ge_0.03": [g.split(":")[1] for g in grp.index[grp.drop_recall5 >= 0.03]],
             "group_drops": {g.split(":")[1]: float(v) for g, v in grp.drop_recall5.items()},
             "possible_location_proxy_used": proxy_used,
             "calibration_pass": cal["calibration_pass"], "brier_skill_score": cal["brier_skill_score"],
             "uncertainty_informative": unc["informative_by_rule"],
             "survey_edge_flag": res["edge_flag"], "stripe_flag_score_map": spec["flag_stripes_in_score_map"],
             "stripe_ratio_score_map": spec["score_map"]["flight_line_band_150_260m"]["peak_to_median"],
             "stripe_ratio_raw_uranium": spec["raw_log_uranium"]["flight_line_band_150_260m"]["peak_to_median"],
             "moran_I_of_positive_percentiles": res["moran"]["I"], "moran_p": res["moran"]["p_one_sided"],
             "roads_tested": False}
    write_json(out_d, out)
    return out_d
