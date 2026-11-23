"""Streamlit app: map layers, threshold slider, point lookup, performance and limitations.

Run:  streamlit run app/streamlit_app.py      (MPM_MODEL_DIR overrides models/final)
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from mpm.serve import DISCLAIMER, Store  # noqa: E402

MODEL_DIR = Path(os.environ.get("MPM_MODEL_DIR", ROOT / "models" / "final"))
DOWN = 8                                  # 8 x 8 cells = 400 m pixels in the overview map
LAYERS = {"Score percentile (higher = more like known occurrences)": "pct",
          "Model disagreement (descriptive only)": "unc",
          "Neighbourhood-uranium contribution": "nbr"}

st.set_page_config(page_title="Uranium prospectivity pilot", layout="wide")


@st.cache_resource
def get_store() -> Store:
    return Store(MODEL_DIR)


@st.cache_data
def pooled_layer(kind: str, mode: str) -> np.ndarray:
    """Dense map reduced to DOWN x DOWN blocks. mode 'max' keeps small hot spots visible, 'mean' is the average."""
    s = get_store()
    v = {"pct": s.pct, "unc": s.unc, "nbr": s.contrib[:, 0].astype("float32")}[kind]
    g = np.full(s.shape, np.nan, dtype="float32")
    g[s.rows, s.cols] = v
    h, w = (s.shape[0] // DOWN) * DOWN, (s.shape[1] // DOWN) * DOWN
    b = g[:h, :w].reshape(h // DOWN, DOWN, w // DOWN, DOWN).transpose(0, 2, 1, 3).reshape(h // DOWN, w // DOWN, -1)
    with np.errstate(all="ignore"):
        return (np.nanmax(b, axis=2) if mode == "max" else np.nanmean(b, axis=2)).astype("float32")


def draw_map(kind: str, top_pct: float, show_known: bool, hot_only: bool):
    s = get_store()
    img = pooled_layer(kind, "max" if kind == "pct" else "mean")
    if hot_only:
        img = np.where(pooled_layer("pct", "max") >= 1 - top_pct / 100.0, img, np.nan)
    x0, y1 = s.c, s.f
    ext = [x0 / 1000, (x0 + img.shape[1] * DOWN * s.a) / 1000, (y1 + img.shape[0] * DOWN * s.e) / 1000, y1 / 1000]
    fig, ax = plt.subplots(figsize=(11, 5))
    ax.set_facecolor("#e8e8e8")
    im = ax.imshow(img, extent=ext, cmap={"pct": "magma", "unc": "viridis", "nbr": "plasma"}[kind], interpolation="nearest")
    if show_known:
        px = (s.c + (s.pos_rc[:, 1] + 0.5) * s.a) / 1000
        py = (s.f + (s.pos_rc[:, 0] + 0.5) * s.e) / 1000
        ax.scatter(px, py, s=14, facecolors="none", edgecolors="cyan", linewidths=0.8, label="known occurrence cells")
        ax.legend(loc="lower left")
    ax.set_xlabel("UTM 13N easting (km)")
    ax.set_ylabel("northing (km)")
    fig.colorbar(im, ax=ax, shrink=0.8)
    fig.tight_layout()
    return fig


def page_map():
    st.subheader("Map")
    st.caption(DISCLAIMER)
    c1, c2, c3 = st.columns([2, 2, 2])
    layer = c1.selectbox("Layer", list(LAYERS))
    top = c2.slider("Show only the top X % of the study area", 0.1, 25.0, 5.0, 0.1)
    c3a, c3b = c3.columns(2)
    hot = c3a.checkbox("Apply threshold", value=True)
    known = c3b.checkbox("Known occurrences", value=True)
    st.pyplot(draw_map(LAYERS[layer], top, known, hot))
    s = get_store()
    k = s.pct >= 1 - top / 100.0
    inside = int(s.is_known[k].sum())
    st.markdown(f"**Top {top:.1f} % of cells** = {int(k.sum()):,} cells ({k.sum() * abs(s.a * s.e) / 1e6:,.0f} km2). "
                f"They contain {inside} of {int(s.is_known.sum())} known occurrence cells "
                f"({inside / max(int(s.is_known.sum()), 1):.0%}). **This count is in-sample** (the final model was trained on them). "
                "Out-of-fold, surveying the best 5 % finds about 61 % of occurrences (about 43 % of non-producers).")
    st.caption("Map pixels are 400 m blocks; for the score layer a pixel shows its highest cell, so isolated hot cells stay visible.")


def page_point():
    st.subheader("Point lookup")
    s = get_store()
    c1, c2 = st.columns(2)
    lon = c1.number_input("Longitude (WGS84)", value=-108.62, format="%.5f")
    lat = c2.number_input("Latitude (WGS84)", value=42.35, format="%.5f")
    out = s.point(lon, lat)
    if out is None:
        st.warning("Outside the surveyed footprint (or a no-data cell).")
        return
    a, b, c = st.columns(3)
    a.metric("Score percentile", f"{out['percentile']:.3f}")
    b.metric("Score bin", out["bin"])
    c.metric("Labelled-positive density", f"{out['labelled_positive_density']:.1e}",
             help="Observed out-of-fold rate of known occurrence cells per cell in this score bin. Not a deposit probability.")
    st.write(f"95 % interval of the bin rate: {out['interval_95'][0]:.1e} to {out['interval_95'][1]:.1e}; "
             f"{out['lift_vs_average_cell']:.1f}x the average cell. Model disagreement: **{out['uncertainty']['level']}** "
             f"({out['uncertainty']['disagreement']:.3f}).")
    st.dataframe(pd.DataFrame(out["top_drivers"]), hide_index=True)
    for w in out["warnings"]:
        st.warning(w)
    st.caption(out["disclaimer"])


def page_limits():
    st.subheader("Performance and limitations")
    s = get_store()
    m = s.meta
    st.warning("Gate G4 was NOT met: the model does not beat the raw uranium count with confidence. "
               "It is a ranking by the local radiometric uranium neighbourhood, with modest added value. It does not model geology.")
    ci = pd.DataFrame(m["out_of_fold_performance_inclusive_phase8"])
    cols = [c for c in ["model", "positives", "n_pos", "roc_auc", "roc_auc_lo", "roc_auc_hi", "recall_top5pct", "recall_top5pct_lo",
                        "recall_top5pct_hi"] if c in ci.columns]
    st.markdown("**Out-of-fold performance** (spatial block CV, 2 km ring counted as unlabeled, 95 % block-bootstrap intervals):")
    st.dataframe(ci[cols].round(3), hide_index=True)
    bins = pd.DataFrame(m["calibration_bins_out_of_fold_phase9"])
    st.markdown("**Observed rate of known occurrence cells by score bin** (out-of-fold, per cell, log scale):")
    fig, ax = plt.subplots(figsize=(7, 3))
    y = bins.observed_rate.values
    ax.bar(bins["bin"], y, yerr=[y - bins.obs_lo.values, bins.obs_hi.values - y], color="#7a3b9e")
    ax.set_yscale("log")
    ax.axhline(5.76e-5, color="grey", ls="--", label="average cell")
    ax.legend()
    ax.tick_params(axis="x", labelrotation=30)
    fig.tight_layout()
    st.pyplot(fig)
    st.markdown("**Known limitations**")
    for t in m["limitations"]:
        st.markdown(f"- {t}")
    st.caption(f"Model fitted {m['created_utc']} on {m['n_train_positives']} occurrence cells and "
               f"{m['n_train_background']:,} sampled background cells; {m['features_used']} features.")


def main():
    st.title("Uranium prospectivity pilot: South Pass - Granite Mountains, Wyoming")
    if not (MODEL_DIR / "serving.npz").exists():
        st.error(f"Model artefacts not found in {MODEL_DIR}. Run scripts/run_pipeline.py first.")
        return
    page = st.sidebar.radio("Page", ["Map", "Point lookup", "Performance and limitations"])
    {"Map": page_map, "Point lookup": page_point, "Performance and limitations": page_limits}[page]()


main()
