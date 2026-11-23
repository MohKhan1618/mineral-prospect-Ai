"""Phase 10: query layer over models/final/serving.npz. Used by the API and by the Streamlit app.

No feature file and no model object are needed at serving time: scores, percentiles, uncertainty and per-group
contributions were precomputed for every cell by `final.build_serving` with the same code path used in training.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from pyproj import Transformer

BIN_EDGES = [0.999, 0.99, 0.95, 0.90, 0.75, 0.50, 0.0]     # same bins as Phase 9 calibration
DISCLAIMER = ("Relative ranking from local radiometric uranium context. 'labelled_positive_density' is the out-of-fold rate of "
              "known occurrence cells per cell in that score bin: a lower bound on prospectivity, NOT the probability of a deposit.")


GROUP_PLAIN = {
    "neighbourhood": "the average uranium, thorium and potassium in the 1-5 km around the cell",
    "radiometric": "the radiometric values measured in the cell itself",
    "magnetic": "the magnetic field values",
    "terrain": "elevation and slope",
    "structure": "distance to mapped faults and fault density",
    "geology": "the mapped rock type",
}
MODEL_CAUTION = ("The model has learned one thing: that the surroundings look like the surroundings of known occurrence cells. "
                 "It has no geological understanding and cannot tell you why a deposit would be there.")


def _survey_pct(q: list, v: float) -> float:
    return float(np.searchsorted(np.asarray(q), v, side="right") / (len(q) - 1))


class Store:
    def __init__(self, model_dir: Path):
        model_dir = Path(model_dir)
        z = np.load(model_dir / "serving.npz")
        self.meta = json.load(open(model_dir / "metadata.json", encoding="utf-8"))
        self.rows, self.cols = z["rows"], z["cols"]
        self.logit, self.pct, self.unc = z["logit"], z["pct"], z["unc"]
        self.contrib, self.edge_km, self.cover = z["contrib"], z["edge_km"], z["cover"]
        self.shape = tuple(int(v) for v in z["shape"])
        self.a, self.b, self.c, self.d, self.e, self.f = (float(v) for v in z["transform"])
        self.groups = [str(g) for g in z["group_order"]]
        self.group_mean = z["group_mean"]
        self.pos_rc = np.column_stack([z["pos_cell_row"], z["pos_cell_col"]])
        self.pos_is_producer = z["pos_is_producer"]
        self.to_grid = Transformer.from_crs("EPSG:4326", str(z["crs"]), always_xy=True)
        self.to_ll = Transformer.from_crs(str(z["crs"]), "EPSG:4326", always_xy=True)
        self.index = np.full(self.shape, -1, dtype="int32")
        self.index[self.rows, self.cols] = np.arange(self.rows.size, dtype="int32")
        self.is_known = np.zeros(self.rows.size, bool)
        known = self.index[self.pos_rc[:, 0], self.pos_rc[:, 1]]
        self.is_known[known[known >= 0]] = True
        self.unc_cut = np.quantile(self.unc[::37], [1 / 3, 2 / 3])
        self.bins = self.meta["calibration_bins_out_of_fold_phase9"]
        self.ev, self.q, self.hot = None, None, None
        if (model_dir / "evidence.npz").exists():
            e = np.load(model_dir / "evidence.npz", allow_pickle=True)
            self.ev = {k: e[k] for k in ("eU", "eTh", "eK", "nbr_U_5km", "fault_km", "elev_m", "unit", "gclass")}
            self.q = json.loads(str(e["quantiles"]))
        if (model_dir / "hotspots.json").exists():
            self.hot = json.load(open(model_dir / "hotspots.json", encoding="utf-8"))

    # ---- geometry ----
    def lonlat_to_rc(self, lon, lat):
        x, y = self.to_grid.transform(lon, lat)
        return (y - self.f) / self.e, (x - self.c) / self.a      # row, col (fractional)

    def rc_to_lonlat(self, row, col):
        x, y = self.c + (np.asarray(col) + 0.5) * self.a, self.f + (np.asarray(row) + 0.5) * self.e
        lon, lat = self.to_ll.transform(x, y)
        return np.asarray(lon), np.asarray(lat)

    # ---- helpers ----
    def bin_index(self, pct: float) -> int:
        return int(sum(pct < e for e in BIN_EDGES[:-1]))

    def bin_info(self, pct: float) -> dict:
        r = self.bins[self.bin_index(pct)]
        return {"bin": r["bin"], "labelled_positive_density": r["observed_rate"], "interval_95": [r["obs_lo"], r["obs_hi"]],
                "lift_vs_average_cell": r["lift_vs_prevalence"]}

    def uncertainty_level(self, u: float) -> str:
        return "low" if u < self.unc_cut[0] else "medium" if u < self.unc_cut[1] else "high"

    def cell_report(self, i: int) -> dict:
        pct = float(self.pct[i])
        drivers = sorted(({"group": g, "contribution_vs_typical_cell": float(self.contrib[i, k]) - float(self.group_mean[k])}
                          for k, g in enumerate(self.groups)), key=lambda d: -abs(d["contribution_vs_typical_cell"]))
        warn = []
        if bool(self.is_known[i]):
            warn.append("this cell is one of the known occurrences used for training: its score is in-sample and optimistic")
        if float(self.edge_km[i]) < 1.0:
            warn.append("within 1 km of the survey edge: edge cells were over-represented among occurrences, treat with care")
        if bool(self.cover[i]):
            warn.append("unconsolidated cover: radiometrics may not reflect the bedrock below")
        if self.uncertainty_level(float(self.unc[i])) == "high":
            warn.append("high model disagreement (descriptive only, not a validated error bar)")
        return {"score_logit": float(self.logit[i]), "percentile": pct, **self.bin_info(pct),
                "uncertainty": {"disagreement": float(self.unc[i]), "level": self.uncertainty_level(float(self.unc[i])),
                                "note": "spread of percentile across four model families and three training splits; ignores data and label error"},
                "top_drivers": drivers[:3], "distance_to_survey_edge_km": float(self.edge_km[i]),
                "on_unconsolidated_cover": bool(self.cover[i]), "is_training_occurrence": bool(self.is_known[i]), "warnings": warn}

    # ---- evidence and reading ----
    def evidence(self, i: int) -> dict | None:
        if self.ev is None:
            return None
        g = lambda k: float(self.ev[k][i])
        eu, eth = g("eU"), g("eTh")
        ratio = eu / max(eth, 0.5)
        hot = self.hot or {}
        return {
            "eU_cps": round(eu, 1), "eTh_cps": round(eth, 1), "eK_cps": round(g("eK"), 1),
            "mean_eU_5km_cps": round(g("nbr_U_5km"), 1), "u_over_th": round(ratio, 2),
            "distance_to_fault_km": round(g("fault_km"), 2), "elevation_m": round(g("elev_m")),
            "rock_class": hot.get("class_names", {}).get(str(int(self.ev["gclass"][i])), "unknown"),
            "rock_unit": hot.get("unit_names", {}).get(str(int(self.ev["unit"][i])), "unknown"),
            "survey_percentile": {"eU": _survey_pct(self.q["eU"], eu), "eTh": _survey_pct(self.q["eTh"], eth),
                                  "eK": _survey_pct(self.q["eK"], g("eK")),
                                  "mean_eU_5km": _survey_pct(self.q["nbr_U_5km"], g("nbr_U_5km")),
                                  "u_over_th": _survey_pct(self.q["u_over_th"], ratio)},
            "survey_median": {"eU": self.q["eU"][50], "eTh": self.q["eTh"][50], "eK": self.q["eK"][50],
                              "u_over_th": self.q["u_over_th"][50]},
        }

    def nearest_known(self, i: int) -> dict | None:
        if self.pos_rc.size == 0:
            return None
        d = np.hypot(self.pos_rc[:, 0] - self.rows[i], self.pos_rc[:, 1] - self.cols[i]) * abs(self.a) / 1000.0
        j = int(np.argmin(d))
        out = {"distance_km": round(float(d[j]), 2), "is_producer": bool(self.pos_is_producer[j])}
        if self.hot and j < len(self.hot["known"]):
            out["name"] = self.hot["known"][j]["name"]
            out["status"] = self.hot["known"][j]["status"]
        return out

    def reading(self, report: dict, ev: dict | None, nearest: dict | None) -> list[dict]:
        """Three kinds of statement, kept apart on purpose: measured (data), model (what drove the score) and guide
        (textbook radiometric interpretation, NOT a model output), plus cautions."""
        out: list[dict] = []
        if ev:
            sp = ev["survey_percentile"]
            out.append({"kind": "measured", "title": "Uranium",
                        "text": f"eU is {ev['eU_cps']} cps here, higher than {sp['eU']:.0%} of the survey "
                                f"(median {ev['survey_median']['eU']:.1f}). The 5 km average is {ev['mean_eU_5km_cps']} cps "
                                f"({sp['mean_eU_5km']:.0%} of the survey)."})
            out.append({"kind": "measured", "title": "Thorium, potassium and ratio",
                        "text": f"eTh {ev['eTh_cps']} cps ({sp['eTh']:.0%}), eK {ev['eK_cps']} cps ({sp['eK']:.0%}); "
                                f"U/Th ratio {ev['u_over_th']} (survey median {ev['survey_median']['u_over_th']:.2f}; "
                                f"above {sp['u_over_th']:.0%} of cells)."})
            out.append({"kind": "measured", "title": "Setting",
                        "text": f"{ev['rock_class']}; unit: {ev['rock_unit']}. Nearest mapped fault {ev['distance_to_fault_km']} km away; "
                                f"elevation {ev['elevation_m']} m."})
        if nearest:
            nm = f" ({nearest['name']}, {nearest.get('status', 'unknown status')})" if nearest.get("name") else ""
            out.append({"kind": "measured", "title": "Nearest known occurrence",
                        "text": f"{nearest['distance_km']} km away{nm}. Known occurrences are the training labels."})
        for d in report["top_drivers"]:
            eff = d["contribution_vs_typical_cell"]
            out.append({"kind": "model", "title": f"Model driver: {d['group']}",
                        "text": f"{'Raises' if eff > 0 else 'Lowers'} the score by {abs(eff):.1f} (logit units) relative to a typical cell. "
                                f"This group is {GROUP_PLAIN.get(d['group'], d['group'])}."})
        if ev:
            sp, cls = ev["survey_percentile"], ev["rock_class"]
            if sp["eU"] >= 0.9 and sp["u_over_th"] >= 0.75:
                out.append({"kind": "guide", "title": "High uranium relative to thorium",
                            "text": "In gamma-ray surveys, uranium that is high compared with thorium can mean uranium has been concentrated by "
                                    "geological processes, not just inherited from thorium-rich source rock. That is why such areas get a "
                                    "second look. It is a pointer, not proof."})
            elif sp["eU"] >= 0.9 and sp["eTh"] >= 0.9:
                out.append({"kind": "guide", "title": "Uranium, thorium and potassium all high",
                            "text": "All three radioelements being high is typical of radioelement-rich felsic rock such as granite. This "
                                    "explains the signal but does not by itself point to economic mineralisation."})
            elif sp["mean_eU_5km"] >= 0.9 and sp["eU"] < 0.75:
                out.append({"kind": "guide", "title": "High surroundings, ordinary cell",
                            "text": "The cell itself is not unusual but the area around it is. Occurrence points are often a little off their "
                                    "true position, so the model rewards high surroundings."})
            if "clastic" in cls.lower():
                out.append({"kind": "guide", "title": "Sandstone setting",
                            "text": "Sandstone-hosted uranium is a classic deposit type in Wyoming's basins. It depends on groundwater "
                                    "chemistry and rock layering that this model cannot see."})
            if "intrusive" in cls.lower() or "gneiss" in cls.lower():
                out.append({"kind": "guide", "title": "Granitic or metamorphic basement",
                            "text": "Uranium-rich granites and pegmatites are common source rocks for uranium. A source rock is not a deposit."})
            if ev["distance_to_fault_km"] < 1.0:
                out.append({"kind": "guide", "title": "Close to a mapped fault",
                            "text": "Faults can channel fluids that move uranium. In this model the structure features added almost "
                                    "nothing measurable."})
        out.append({"kind": "caution", "title": "What the model cannot tell you", "text": MODEL_CAUTION})
        for w in report["warnings"]:
            out.append({"kind": "caution", "title": "Warning", "text": w})
        return out

    # ---- queries ----
    def point(self, lon: float, lat: float) -> dict | None:
        r, c = self.lonlat_to_rc(lon, lat)
        ri, ci = int(np.floor(r)), int(np.floor(c))
        if not (0 <= ri < self.shape[0] and 0 <= ci < self.shape[1]) or self.index[ri, ci] < 0:
            return None
        i = int(self.index[ri, ci])
        clon, clat = self.rc_to_lonlat(ri, ci)
        rep = self.cell_report(i)
        ev, near = self.evidence(i), self.nearest_known(i)
        return {"query": {"lon": lon, "lat": lat}, "cell_centre": {"lon": float(clon), "lat": float(clat)},
                **rep, "evidence": ev, "nearest_known_occurrence": near, "reading": self.reading(rep, ev, near),
                "disclaimer": DISCLAIMER}

    def bbox(self, min_lon: float, min_lat: float, max_lon: float, max_lat: float, top_n: int = 10) -> dict | None:
        corners = [self.lonlat_to_rc(lo, la) for lo in (min_lon, max_lon) for la in (min_lat, max_lat)]
        r0, r1 = int(np.floor(min(c[0] for c in corners))), int(np.ceil(max(c[0] for c in corners)))
        c0, c1 = int(np.floor(min(c[1] for c in corners))), int(np.ceil(max(c[1] for c in corners)))
        r0, c0, r1, c1 = max(r0, 0), max(c0, 0), min(r1, self.shape[0]), min(c1, self.shape[1])
        if r0 >= r1 or c0 >= c1:
            return None
        ids = self.index[r0:r1, c0:c1].ravel()
        ids = ids[ids >= 0]
        if ids.size == 0:
            return None
        p = self.pct[ids]
        k = min(top_n, ids.size)
        best = ids[np.argsort(-p, kind="stable")[:k]]
        lon, lat = self.rc_to_lonlat(self.rows[best], self.cols[best])
        n_known = int(((self.pos_rc[:, 0] >= r0) & (self.pos_rc[:, 0] < r1) & (self.pos_rc[:, 1] >= c0) & (self.pos_rc[:, 1] < c1)).sum())
        return {"n_cells": int(ids.size), "area_km2": float(ids.size * abs(self.a * self.e) / 1e6),
                "mean_percentile": float(p.mean()), "max_percentile": float(p.max()),
                "share_in_top_5pct_of_study_area": float((p >= 0.95).mean()),
                "share_in_top_1pct_of_study_area": float((p >= 0.99).mean()),
                "mean_uncertainty": float(self.unc[ids].mean()),
                "known_occurrence_cells_inside": n_known,
                "top_cells": [{"lon": float(lon[j]), "lat": float(lat[j]), "percentile": float(self.pct[i]),
                               "uncertainty_level": self.uncertainty_level(float(self.unc[i]))} for j, i in enumerate(best)],
                "disclaimer": DISCLAIMER}
