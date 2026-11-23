"""Phase 8 stage functions (each writes one CSV/JSON and is safe to re-run)."""
from __future__ import annotations

import json
import logging
from pathlib import Path

import numpy as np
import pandas as pd

from . import experiments as ex
from .evaluate import Ctx, evaluate_saved_models, fold_cells, load_context
from .labels import POSITIVE
from .metrics import ranking_metrics
from .runner import atomic_write

log = logging.getLogger(__name__)
BASELINES = ["prevalence", "rule_geology", "single_rad_U"]
LEARNED = ["logreg", "rf", "et", "hgb"]
FAST_RF = {"n_estimators": 100}   # forests in ablation / learning curve use 100 trees to keep run time sane


def latest_oof_dir(models_dir: Path) -> Path:
    dirs = [d for d in (Path(models_dir) / "oof").iterdir() if d.is_dir() and any(d.glob("*.npy"))]
    if not dirs:
        raise FileNotFoundError("no out-of-fold scores found; run stage 07_train first")
    return max(dirs, key=lambda d: d.stat().st_mtime)


def eval_inclusive(ctx: Ctx, models_dir: Path, tcfg: dict, ecfg: dict, out_ci: Path, out_pairs: Path,
                   out_folds: Path) -> None:
    d = latest_oof_dir(models_dir)
    reps = tcfg["repeats"]
    evaluate_saved_models(ctx, d, tcfg["models"], reps, BASELINES, out_ci, out_pairs, ecfg["n_boot"], ecfg["seed"])
    rows = []
    for rep in range(reps):
        fc = fold_cells(ctx, rep)
        for m in tcfg["models"]:
            s = np.load(d / f"{m}_r{rep}.npy")
            for f in range(ctx.n_folds):
                ids = np.flatnonzero(fc == f)
                rows.append({"model": m, "repeat": rep, "fold": f, **ex.inclusive_metrics(ctx, ids, s[ids], ecfg["seed"])})
    ex.write_csv(pd.DataFrame(rows), out_folds)


def lodo(ctx: Ctx, ecfg: dict, out: Path) -> None:
    ex.write_csv(ex.run_lodo(ctx, ["prevalence", "rule_geology", "single_rad_U", "logreg", "rf", "et"],
                             ecfg["district_link_m"], ecfg["min_district_pos"], 40000, ecfg["seed"]), out)


def noproducer(ctx: Ctx, ecfg: dict, out: Path) -> None:
    rows = []
    for m in ["logreg", "rf", "et"]:
        for drop in (False, True):
            rows += ex.run_folds(ctx, 0, m, drop_producers=drop, seed=ecfg["seed"],
                                 tag={"trained_on": "no_producers" if drop else "all_positives"})
    ex.write_csv(pd.DataFrame(rows), out)


def ablation(ctx: Ctx, ecfg: dict, out: Path) -> None:
    allg = sorted(ctx.groups)
    cfgs = [("full", list(range(len(ctx.names))))]
    for g in allg:
        cfgs.append((f"drop_{g}", [i for gg, ix in ctx.groups.items() if gg != g for i in ix]))
    for g in allg:
        cfgs.append((f"only_{g}", list(ctx.groups[g])))
    rows = []
    for m in ["logreg", "rf"]:
        for label, cols in cfgs:
            rows += ex.run_folds(ctx, 0, m, cols=cols, params=FAST_RF if m == "rf" else None, seed=ecfg["seed"],
                                 tag={"config": label, "n_features": len(cols)})
            log.info("ablation %s %s done", m, label)
    ex.write_csv(pd.DataFrame(rows), out)


def learning_curve(ctx: Ctx, ecfg: dict, out: Path) -> None:
    rows = []
    for m in ["logreg", "rf"]:
        for fr in ecfg["learning_fracs"]:
            rows += ex.run_folds(ctx, 0, m, frac=fr, params=FAST_RF if m == "rf" else None, seed=ecfg["seed"],
                                 tag={"train_fraction": fr})
    ex.write_csv(pd.DataFrame(rows), out)


def shuffle_test(ctx: Ctx, ecfg: dict, out: Path) -> None:
    rows = []
    for m in ["logreg", "rf", "et"]:
        for k in range(ecfg["n_shuffles"]):
            rows += ex.run_folds(ctx, 0, m, shuffle=True, seed=ecfg["seed"] + 5000 * (k + 1), tag={"shuffle_seed": k})
    ex.write_csv(pd.DataFrame(rows), out)


def tuning(ctx: Ctx, ecfg: dict, out_inner: Path, out_outer: Path) -> None:
    ins, outs = [], []
    for m in ["logreg", "rf"]:
        i, o = ex.run_tuning(ctx, 0, m, seed=ecfg["seed"])
        ins.append(i); outs.append(o)
    ex.write_csv(pd.concat(ins, ignore_index=True), out_inner)
    ex.write_csv(pd.concat(outs, ignore_index=True), out_outer)


def g4_summary(reports: Path, out: Path) -> dict:
    """Apply the gate defined in docs/phases/phase-08-decision-rule.md to the saved result files."""
    pairs = pd.read_csv(reports / "phase8_paired_vs_baselines.csv")
    shuf = pd.read_csv(reports / "phase8_shuffle_test.csv")
    lodo_df = pd.read_csv(reports / "phase8_lodo.csv")
    res: dict = {}
    for m in LEARNED:
        verdict: dict = {}
        for subset in ("all", "non_producers"):
            p = pairs[(pairs.model == m) & (pairs.positives == subset)]
            beats = {b: bool(p[p.baseline == b].lo.gt(0).all() and len(p[p.baseline == b]) == 2) for b in BASELINES}
            verdict[f"beats_baselines_{subset}"] = beats
        sh = shuf[shuf.model == m].incl_roc_auc.mean() if m in set(shuf.model) else np.nan
        verdict["shuffle_mean_roc_auc"] = None if np.isnan(sh) else float(sh)
        verdict["shuffle_ok"] = bool(0.45 <= sh <= 0.55) if not np.isnan(sh) else None
        pm = lodo_df.pivot(index="district", columns="model", values="incl_recall_top5pct")
        if m in pm.columns:
            wins = (pm[m] > pm["single_rad_U"]).mean()
            verdict["lodo_share_districts_beating_U_recall5"] = float(wins)
            verdict["lodo_ok"] = bool(wins >= 0.5)
        else:
            verdict["lodo_ok"] = None
        verdict["G4_pass_all_positives"] = bool(all(verdict["beats_baselines_all"].values()) and verdict["shuffle_ok"] and verdict["lodo_ok"])
        verdict["G4_pass_non_producers"] = bool(all(verdict["beats_baselines_non_producers"].values()) and verdict["shuffle_ok"] and verdict["lodo_ok"])
        res[m] = verdict
    with atomic_write(out, "w") as fh:
        json.dump(res, fh, indent=2)
    return res


def null_random_positives(ctx: Ctx, ecfg: dict, out: Path) -> None:
    """Post-hoc replacement for the label-shuffle test (see docs/phases/phase-08-*.md).

    Shuffling training labels is biased below 0.5 here: true positives live in the sparse high-uranium tail of
    feature space, where a model fitted to noise often outputs exactly 0. A cleaner leakage check plants the SAME
    number of positives at uniformly random valid cells (typical feature values, no real signal) and runs the
    identical pipeline. Honest pipeline -> ROC-AUC about 0.5.
    """
    from dataclasses import replace
    rows = []
    n = int((ctx.lab == POSITIVE).sum())
    for k in range(ecfg["n_shuffles"]):
        rng = np.random.default_rng(ecfg["seed"] + 9000 + k)
        lab = np.where(ctx.lab > 0, 1, 0)
        lab[rng.choice(np.flatnonzero(lab == 1), n, replace=False)] = POSITIVE
        c2 = replace(ctx, lab=lab, is_prod=np.zeros_like(ctx.is_prod))
        for m in ["logreg", "rf", "et"]:
            rows += ex.run_folds(c2, 0, m, seed=ecfg["seed"] + 100 * k, tag={"null_seed": k})
    ex.write_csv(pd.DataFrame(rows), out)
