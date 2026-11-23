"""Run the pipeline. Safe to re-run any time: finished stages are skipped.

Usage:
    python scripts/run_pipeline.py            # run what is not done yet
    python scripts/run_pipeline.py --force    # re-run everything
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from mpm.config import get_paths, load_config, set_seed, setup_logging  # noqa: E402
from mpm.runner import Stage, atomic_write, run_pipeline  # noqa: E402
from mpm import frontend_data as fd  # noqa: E402


def build_stages(cfg: dict) -> list[Stage]:
    paths = get_paths(cfg)
    smoke_out = paths.reports / "phase0_smoke.txt"

    def smoke() -> None:
        with atomic_write(smoke_out, "w") as fh:
            fh.write("pipeline runner works\n")

    from mpm.download import download, register
    from mpm.occurrences import count_positives, load_uranium, unzip_mrds, write_report

    mrds_url = "https://mrdata.usgs.gov/mrds/mrds-csv.zip"
    mrds_zip = paths.raw / "occurrences" / "mrds-csv.zip"
    mrds_csv = paths.raw / "occurrences" / "mrds.csv"
    gate_report = paths.reports / "phase1_positive_count.csv"

    def dl_mrds() -> None:
        p = download(mrds_url, mrds_zip)
        register(paths.raw / "MANIFEST.json", "mrds_csv", mrds_url, p,
                 "USGS public domain (verify on source page)", "MRDS, last modified 2022-08-23")

    def gate() -> None:
        u = load_uranium(mrds_csv)
        areas = {k: tuple(v) for k, v in cfg["candidate_areas"].items()}
        res = count_positives(u, areas, cfg["gate"]["min_positives_total"])
        write_report(res, gate_report)

    from mpm.ingest import verify_extracted

    sp = paths.raw / "radiometrics_magnetics" / "south_pass"
    deliv_zip = next(iter(sp.glob("ContractorsDeliverables_*.zip")), sp / "MISSING_deliverables.zip")
    foot_zip = next(iter(sp.glob("Footprint_*.zip")), sp / "MISSING_footprint.zip")
    report_pdf = next(iter(sp.glob("ContractorsReport_*.pdf")), sp / "MISSING_report.pdf")
    ready_flag = sp / "_EXTRACT_VERIFIED.json"

    def check_south_pass() -> None:
        verify_extracted(sp, ready_flag)

    def register_south_pass() -> None:
        from mpm.download import register
        for nm, f in [("south_pass_deliverables_zip", deliv_zip), ("south_pass_report_pdf", report_pdf),
                      ("south_pass_footprint_zip", foot_zip)]:
            register(paths.raw / "MANIFEST.json", nm, "https://doi.org/10.5066/P13W5Y9W", f,
                     "USGS data release (public; verify terms on source page)", "manual browser download 2026-11-20")

    from mpm.grids import all_layer_paths, build_inventory, layer_path, write_inventory
    grid_report = paths.reports / "phase3_grid_inventory.csv"

    def grid_inventory() -> None:
        df = build_inventory(sp)
        write_inventory(df, grid_report)
        for p in all_layer_paths(sp):
            register(paths.raw / "MANIFEST.json", f"grid_{p.stem}", "https://doi.org/10.5066/P13W5Y9W", p,
                     "USGS data release (verify terms)", "exported from Geosoft .grd with Geosoft Viewer 2026.1, COG float GeoTIFF")

    from mpm.signal import positives_in_footprint, signal_table, write_table
    from mpm.ingest import SURVEY
    foot_shp = sp / f"Footprint_{SURVEY}" / f"Footprint_{SURVEY}.shp"
    signal_report = paths.reports / "phase3_signal_check.csv"

    def signal_check() -> None:
        pos = positives_in_footprint(mrds_csv, foot_shp)
        write_table(signal_table(sp, pos), signal_report)

    from mpm.clean import LAYERS as CLEAN_LAYERS, run_cleaning
    clean_dir = paths.interim / "clean"
    clean_report = paths.reports / "phase3_cleaning_log.json"

    def clean() -> None:
        run_cleaning(sp, clean_dir, clean_report)

    from mpm import ancillary as anc
    manifest = paths.raw / "MANIFEST.json"
    sgmc_zip = paths.raw / "geology" / "WY.zip"
    sgmc_dir = paths.raw / "geology" / "WY"

    from mpm import master_grid as mg
    proc = paths.processed
    srtm_hgts = [anc.srtm_hgt_path(paths.raw, n) for n in anc.SRTM_TILES]
    clean_tifs = [clean_dir / f"{n}.tif" for n in CLEAN_LAYERS]
    sgmc_inputs = [sgmc_dir / "WY_geol_poly.shp", sgmc_dir / "WY_geol_poly.dbf",
                   sgmc_dir / "WY_geol_poly.shx", sgmc_dir / "WY_units.csv"]
    val_report = paths.reports / "phase4_alignment_report.json"

    from mpm.labels import run_labels
    from mpm.splits import run_splits
    pos_csv = proc / "positives.csv"
    label_tif = proc / "labels.tif"
    label_report = paths.reports / "phase5_label_report.json"
    splits_csv = paths.splits / "splits.csv"
    block_tif = paths.splits / "block_id.tif"
    splits_report = paths.reports / "phase5_split_report.json"
    lab_cfg, spl_cfg = cfg["labels"], cfg["splits"]

    from mpm.features import build_features, feature_report
    feat_dir = paths.features
    structure_shp = sgmc_dir / "WY_structure.shp"
    feat_outputs = [feat_dir / n for n in ("features.npy", "cell_index.npy", "feature_catalog.json")]
    feat_report = paths.reports / "phase6_feature_report.csv"
    feat_pairs = paths.reports / "phase6_correlated_pairs.csv"
    feat_inputs = (clean_tifs + [proc / n for n in ("dem.tif", "geology_class.tif", "master_mask.tif", "geology_legend.csv")]
                   + [structure_shp, sgmc_dir / "WY_structure.dbf"])

    from mpm.train import run_training
    t_cfg = cfg["training"]
    cmp_csv = paths.reports / "phase7_model_runs.csv"
    summ_csv = paths.reports / "phase7_model_summary.csv"

    def train() -> None:
        run_training(feat_dir, label_tif, block_tif, splits_csv, paths.models / "oof", cmp_csv, summ_csv,
                     t_cfg, lab_cfg["buffer_m"], cfg["project"]["seed"])

    from mpm import phase8 as p8
    from mpm.evaluate import load_context
    e_cfg = cfg["evaluation"]
    R = paths.reports
    r8 = {k: R / f"phase8_{k}.csv" for k in ("cv_inclusive_ci", "paired_vs_baselines", "cv_inclusive_folds", "lodo",
                                             "no_producers", "ablation", "learning_curve", "shuffle_test",
                                             "tuning_inner", "tuning_outer", "null_random_positives")}
    g4_json = R / "phase8_g4.json"
    p8_in = feat_outputs + [label_tif, block_tif, splits_csv, pos_csv]

    from mpm import final as fin
    from mpm import interpret as ip
    final_dir = paths.models / "final"
    i_cfg = cfg["interpretation"]
    seed0 = cfg["project"]["seed"]
    r9 = {k: R / f"phase9_{k}" for k in ("importance.csv", "coefficients.csv", "attribution.csv", "calibration_bins.csv",
                                         "calibration.json", "uncertainty.json", "uncertainty_terciles.csv", "edge.csv",
                                         "cover.csv", "spectrum.json", "residuals.json", "worst_positives.csv",
                                         "districts.csv", "summary.json")}
    map_dir = R / "maps"
    map_files = [map_dir / "score_percentile_oof_logreg.tif", map_dir / "uncertainty_disagreement.tif"]
    mm_tif = proc / "master_mask.tif"

    def oof():
        return p8.latest_oof_dir(paths.models)

    def ctx8():
        return load_context(feat_dir, label_tif, block_tif, splits_csv, pos_csv, lab_cfg["buffer_m"])

    def features() -> None:
        build_features(clean_dir, proc, structure_shp, feat_dir)

    def feat_rep() -> None:
        feature_report(feat_dir, pos_csv, feat_report, feat_pairs)

    def labels() -> None:
        run_labels(mrds_csv, foot_shp, proc / "master_mask.tif", pos_csv, label_tif, label_report,
                   lab_cfg["buffer_m"])

    def splits() -> None:
        run_splits(label_tif, pos_csv, splits_csv, block_tif, splits_report, spl_cfg["block_m"],
                   spl_cfg["n_folds"], spl_cfg["n_repeats"], cfg["project"]["seed"], lab_cfg["buffer_m"])

    # Later phases append their stages here, in order.
    return [
        Stage(
            name="00_smoke",
            func=smoke,
            outputs=[smoke_out],
            params={"seed": cfg["project"]["seed"]},
        ),
        Stage("01_download_mrds", dl_mrds, outputs=[mrds_zip]),
        Stage("01_unzip_mrds", lambda: unzip_mrds(mrds_zip, mrds_csv),
              inputs=[mrds_zip], outputs=[mrds_csv]),
        Stage("01_positive_count", gate, inputs=[mrds_csv], outputs=[gate_report],
              params={"areas": cfg["candidate_areas"], "gate": cfg["gate"]}),
        Stage("02_register_south_pass", register_south_pass,
              inputs=[], outputs=[paths.raw / "MANIFEST.json"], params={"v": 1}),
        Stage("02_verify_south_pass_files", check_south_pass, outputs=[ready_flag]),
        Stage("03_grid_inventory", grid_inventory, inputs=all_layer_paths(sp), outputs=[grid_report]),
        Stage("03_signal_check", signal_check, inputs=[mrds_csv, foot_shp] + all_layer_paths(sp),
              outputs=[signal_report], params={"v": 1}),
        Stage("04_download_srtm", lambda: anc.download_srtm(paths.raw, manifest),
              outputs=[anc.srtm_gz_path(paths.raw, n) for n in anc.SRTM_TILES]),
        Stage("04_gunzip_srtm", lambda: anc.gunzip_srtm(paths.raw),
              inputs=[anc.srtm_gz_path(paths.raw, n) for n in anc.SRTM_TILES],
              outputs=[anc.srtm_hgt_path(paths.raw, n) for n in anc.SRTM_TILES]),
        Stage("04_download_sgmc", lambda: anc.download_sgmc(paths.raw, manifest), outputs=[sgmc_zip]),
        Stage("04_unzip_sgmc", lambda: anc.unzip_sgmc(sgmc_zip, sgmc_dir), inputs=[sgmc_zip],
              outputs=[sgmc_dir / "WY_geol_poly.shp", sgmc_dir / "WY_geol_poly.dbf",
                       sgmc_dir / "WY_geol_poly.shx", sgmc_dir / "WY_geol_poly.prj",
                       sgmc_dir / "WY_units.csv", sgmc_dir / "WY_lith.csv"]),
        Stage("03_clean", clean, inputs=[layer_path(sp, n) for n in CLEAN_LAYERS],
              outputs=[clean_dir / f"{n}.tif" for n in CLEAN_LAYERS] + [clean_report], params={"v": 1}),
        Stage("04_dem", lambda: mg.build_dem(paths.raw, clean_dir, proc / "dem.tif"),
              inputs=srtm_hgts + clean_tifs[:1], outputs=[proc / "dem.tif"], params={"resampling": "average"}),
        Stage("04_geology", lambda: mg.build_geology(sgmc_dir, clean_dir, proc / "geology_class.tif",
                                                     proc / "geology_unit.tif", proc / "geology_legend.csv"),
              inputs=sgmc_inputs + clean_tifs[:1],
              outputs=[proc / "geology_class.tif", proc / "geology_unit.tif", proc / "geology_legend.csv"],
              params={"v": 1}),
        Stage("04_master_mask", lambda: mg.build_master_mask(clean_dir, proc / "dem.tif", proc / "master_mask.tif"),
              inputs=clean_tifs + [proc / "dem.tif"], outputs=[proc / "master_mask.tif"]),
        Stage("04_validate_alignment", lambda: mg.validation_report(proc, clean_dir, val_report),
              inputs=clean_tifs + [proc / n for n in ("dem.tif", "geology_class.tif", "geology_unit.tif", "master_mask.tif")],
              outputs=[val_report]),
        Stage("05_labels", labels, inputs=[mrds_csv, foot_shp, proc / "master_mask.tif"],
              outputs=[pos_csv, label_tif, label_report], params={"labels": lab_cfg, "v": 1}),
        Stage("05_splits", splits, inputs=[label_tif, pos_csv],
              outputs=[splits_csv, block_tif, splits_report],
              params={"splits": spl_cfg, "seed": cfg["project"]["seed"], "buffer_m": lab_cfg["buffer_m"], "v": 1}),
        Stage("06_features", features, inputs=feat_inputs, outputs=feat_outputs, params={"v": 1}),
        Stage("06_feature_report", feat_rep, inputs=feat_outputs + [pos_csv],
              outputs=[feat_report, feat_pairs], params={"v": 1}),
        Stage("07_train", train, inputs=feat_outputs + [label_tif, block_tif, splits_csv],
              outputs=[cmp_csv, summ_csv],
              params={"training": t_cfg, "buffer_m": lab_cfg["buffer_m"], "v": 1}),
        Stage("08_eval_inclusive", lambda: p8.eval_inclusive(ctx8(), paths.models, t_cfg, e_cfg, r8["cv_inclusive_ci"],
                                                             r8["paired_vs_baselines"], r8["cv_inclusive_folds"]),
              inputs=p8_in + [summ_csv],
              outputs=[r8["cv_inclusive_ci"], r8["paired_vs_baselines"], r8["cv_inclusive_folds"]],
              params={"e": e_cfg, "t": t_cfg, "v": 1}),
        Stage("08_lodo", lambda: p8.lodo(ctx8(), e_cfg, r8["lodo"]), inputs=p8_in, outputs=[r8["lodo"]],
              params={"e": e_cfg, "v": 1}),
        Stage("08_shuffle_test", lambda: p8.shuffle_test(ctx8(), e_cfg, r8["shuffle_test"]), inputs=p8_in,
              outputs=[r8["shuffle_test"]], params={"e": e_cfg, "v": 1}),
        Stage("08_no_producers", lambda: p8.noproducer(ctx8(), e_cfg, r8["no_producers"]), inputs=p8_in,
              outputs=[r8["no_producers"]], params={"e": e_cfg, "v": 1}),
        Stage("08_learning_curve", lambda: p8.learning_curve(ctx8(), e_cfg, r8["learning_curve"]), inputs=p8_in,
              outputs=[r8["learning_curve"]], params={"e": e_cfg, "v": 1}),
        Stage("08_ablation", lambda: p8.ablation(ctx8(), e_cfg, r8["ablation"]), inputs=p8_in,
              outputs=[r8["ablation"]], params={"e": e_cfg, "v": 1}),
        Stage("08_tuning", lambda: p8.tuning(ctx8(), e_cfg, r8["tuning_inner"], r8["tuning_outer"]), inputs=p8_in,
              outputs=[r8["tuning_inner"], r8["tuning_outer"]], params={"e": e_cfg, "v": 1}),
        Stage("08_null_random_positives", lambda: p8.null_random_positives(ctx8(), e_cfg, r8["null_random_positives"]),
              inputs=p8_in, outputs=[r8["null_random_positives"]], params={"e": e_cfg, "v": 1}),
        Stage("08_g4_summary", lambda: p8.g4_summary(R, g4_json),
              inputs=[r8["paired_vs_baselines"], r8["shuffle_test"], r8["lodo"]], outputs=[g4_json]),
        Stage("09_importance", lambda: ip.importance(ctx8(), i_cfg["repeat"], seed0, i_cfg["n_perm"], i_cfg["n_unl_sample"],
                                                     r9["importance.csv"], r9["coefficients.csv"], r9["attribution.csv"]),
              inputs=p8_in, outputs=[r9["importance.csv"], r9["coefficients.csv"], r9["attribution.csv"]],
              params={"i": i_cfg, "v": 1}),
        Stage("09_calibration", lambda: ip.calibration(ctx8(), oof() / f"logreg_r{i_cfg['repeat']}.npy", i_cfg["repeat"], seed0,
                                                       i_cfg["calib_unl_sample"], e_cfg["n_boot"], r9["calibration_bins.csv"],
                                                       r9["calibration.json"]),
              inputs=p8_in + [summ_csv], outputs=[r9["calibration_bins.csv"], r9["calibration.json"]],
              params={"i": i_cfg, "n_boot": e_cfg["n_boot"], "v": 1}),
        Stage("09_maps_uncertainty", lambda: ip.maps_and_uncertainty(ctx8(), oof(), t_cfg["repeats"], mm_tif, map_dir,
                                                                     r9["uncertainty.json"], r9["uncertainty_terciles.csv"]),
              inputs=p8_in + [summ_csv, mm_tif], outputs=map_files + [r9["uncertainty.json"], r9["uncertainty_terciles.csv"]],
              params={"v": 1}),
        Stage("09_artifacts", lambda: ip.artifacts(ctx8(), i_cfg["repeat"], oof() / f"logreg_r{i_cfg['repeat']}.npy", mm_tif, oof(),
                                                   t_cfg["repeats"], r9["edge.csv"], r9["cover.csv"], r9["spectrum.json"],
                                                   r9["residuals.json"], r9["worst_positives.csv"], r9["districts.csv"],
                                                   e_cfg["district_link_m"], seed0),
              inputs=p8_in + [summ_csv, mm_tif],
              outputs=[r9[k] for k in ("edge.csv", "cover.csv", "spectrum.json", "residuals.json", "worst_positives.csv",
                                       "districts.csv")], params={"i": i_cfg, "link": e_cfg["district_link_m"], "v": 1}),
        Stage("09_summary", lambda: ip.g9_summary(R, r9["summary.json"]),
              inputs=[r9["importance.csv"], r9["calibration.json"], r9["uncertainty.json"], r9["spectrum.json"],
                      r9["residuals.json"]], outputs=[r9["summary.json"]]),
        Stage("10_final_model", lambda: fin.run_final(ctx8(), feat_dir, label_tif, mm_tif, map_files[1], pos_csv, R,
                                                      feat_outputs + [label_tif, splits_csv, pos_csv], final_dir, seed0,
                                                      t_cfg["background_sample"]),
              inputs=p8_in + [mm_tif, map_files[1], r9["calibration_bins.csv"], r8["cv_inclusive_ci"]],
              outputs=[final_dir / "logreg_final.joblib", final_dir / "serving.npz", final_dir / "metadata.json"],
              params={"n_bg": t_cfg["background_sample"], "seed": seed0, "v": 1}),
        Stage("10c_frontend_data", lambda: _frontend_data(feat_dir, proc, final_dir, pos_csv),
              inputs=[final_dir / "serving.npz", feat_dir / "features.npy", feat_dir / "cell_index.npy",
                      feat_dir / "feature_catalog.json", proc / "geology_unit.tif", proc / "geology_class.tif",
                      proc / "geology_legend.csv", pos_csv],
              outputs=[final_dir / "evidence.npz", final_dir / "hotspots.json"], params={"v": 1}),
    ]


def _frontend_data(feat_dir, proc, final_dir, pos_csv):
    import json
    import numpy as np
    names = [c["name"] for c in json.load(open(feat_dir / "feature_catalog.json", encoding="utf-8"))]
    z = np.load(final_dir / "serving.npz", allow_pickle=True)
    ci = np.load(feat_dir / "cell_index.npy")
    assert (ci[0] == z["rows"]).all() and (ci[1] == z["cols"]).all(), "serving store and features disagree on cell order"
    q = fd.build_evidence(feat_dir / "features.npy", names, z["rows"], z["cols"], proc / "geology_unit.tif",
                          proc / "geology_class.tif", final_dir / "evidence.npz")
    return fd.build_hotspots(final_dir / "serving.npz", final_dir / "evidence.npz", pos_csv, proc / "geology_legend.csv",
                             final_dir / "hotspots.json")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    setup_logging()
    cfg = load_config()
    set_seed(cfg["project"]["seed"])
    run_pipeline(build_stages(cfg), get_paths(cfg).state, force=args.force)


if __name__ == "__main__":
    main()
