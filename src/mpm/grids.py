"""Phase 3: verify the converted survey grids and describe them in a table.

All 11 layers must share one grid (same shape, cell size, origin, CRS) so they can be stacked
cell for cell. Units are taken from the contractor report (counts/sec, nT, nT/m), not guessed.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import rasterio

from .ingest import SURVEY
from .runner import atomic_write

# name -> (subfolder, units per contractor report, note)
LAYERS: dict[str, tuple[str, str, str]] = {
    "U_FIN": ("radiometrics", "counts/sec", "corrected uranium counts (NOT ppm; ppm = counts / 10.4)"),
    "TH_FIN": ("radiometrics", "counts/sec", "corrected thorium counts (ppm = counts / 6.2)"),
    "K_FIN": ("radiometrics", "counts/sec", "corrected potassium counts (% = counts / 99.5)"),
    "TC_FIN": ("radiometrics", "counts/sec", "corrected total counts"),
    "U_FIN_s": ("radiometrics", "UNDOCUMENTED", "values about -0.7..1.0; not in report; do not use until explained"),
    "TH_FIN_s": ("radiometrics", "UNDOCUMENTED", "as above"),
    "K_FIN_s": ("radiometrics", "UNDOCUMENTED", "as above"),
    "TC_FIN_s": ("radiometrics", "UNDOCUMENTED", "as above"),
    "RTP": ("magnetics", "nT", "total field reduced to pole; still contains regional field (~52,400 nT)"),
    "Mag_IGRF": ("magnetics", "nT", "total field after IGRF date/height correction; regional field NOT removed"),
    "VD": ("magnetics", "nT/m", "vertical derivative of total field; centred on zero"),
}


def layer_path(survey_dir: Path, name: str) -> Path:
    sub = LAYERS[name][0]
    return Path(survey_dir) / f"ContractorsDeliverables_{SURVEY}" / sub / "CONVERTED" / f"{name}.tif"


def all_layer_paths(survey_dir: Path) -> list[Path]:
    return [layer_path(survey_dir, n) for n in LAYERS]


def describe_layer(path: Path) -> dict:
    with rasterio.open(path) as r:
        a = r.read(1, masked=True)
        v = a.compressed().astype("float64")
        row = {
            "bands": r.count, "dtype": r.dtypes[0], "rows": r.height, "cols": r.width,
            "cell_x_m": r.res[0], "cell_y_m": r.res[1], "epsg": r.crs.to_epsg() if r.crs else None,
            "nodata": r.nodata, "left": r.bounds.left, "bottom": r.bounds.bottom,
            "n_valid": int(v.size), "pct_valid": round(100 * v.size / a.size, 2),
        }
    q = np.percentile(v, [1, 50, 99])
    row.update(min=float(v.min()), p01=float(q[0]), median=float(q[1]), p99=float(q[2]),
               max=float(v.max()), mean=float(v.mean()), std=float(v.std()),
               pct_negative=round(100 * float((v < 0).mean()), 3))
    return row


def build_inventory(survey_dir: Path) -> pd.DataFrame:
    rows = []
    for name, (_, units, note) in LAYERS.items():
        p = layer_path(survey_dir, name)
        if not p.is_file():
            raise FileNotFoundError(f"Missing converted grid: {p}")
        rows.append({"layer": name, "units": units, "note": note, **describe_layer(p)})
    df = pd.DataFrame(rows)
    check_alignment(df)
    bad = df[(df.bands != 1) | (df.dtype != "float32")]
    if len(bad):
        raise ValueError(f"Grids must be 1-band float32 (colour pictures?): {bad.layer.tolist()}")
    return df


def check_alignment(df: pd.DataFrame) -> None:
    """Every layer must share shape, cell size, origin and CRS, or stacking would silently misalign."""
    keys = ["rows", "cols", "cell_x_m", "cell_y_m", "epsg", "left", "bottom"]
    for k in keys:
        if df[k].nunique() != 1:
            raise ValueError(f"Grids are not aligned: column '{k}' differs: {df.groupby(k).layer.apply(list).to_dict()}")


def write_inventory(df: pd.DataFrame, out: Path) -> None:
    with atomic_write(out, "w") as fh:
        df.to_csv(fh, index=False)
