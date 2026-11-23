"""Phase 1: uranium occurrence points from MRDS and the positive-count gate."""
from __future__ import annotations

import zipfile
from pathlib import Path

import pandas as pd

from .runner import atomic_write

COLS = ["dep_id", "site_name", "latitude", "longitude", "state", "country",
        "commod1", "commod2", "commod3", "dev_stat", "dep_type"]


def unzip_mrds(zip_path: Path, out_csv: Path) -> None:
    with zipfile.ZipFile(zip_path) as z:
        data = z.read("mrds.csv")
    with atomic_write(out_csv, "wb") as fh:
        fh.write(data)


def load_uranium(csv: Path) -> pd.DataFrame:
    df = pd.read_csv(csv, low_memory=False, usecols=COLS)
    is_u = (
        df[["commod1", "commod2", "commod3"]]
        .fillna("")
        .apply(lambda s: s.str.contains("uranium", case=False))
        .any(axis=1)
    )
    u = df[is_u & (df.country == "United States")].dropna(subset=["latitude", "longitude"])
    return u


def count_positives(u: pd.DataFrame, areas: dict, min_total: int) -> pd.DataFrame:
    rows = []
    for name, (x0, y0, x1, y1) in areas.items():
        b = u[u.longitude.between(x0, x1) & u.latitude.between(y0, y1)]
        uniq = b.drop_duplicates(["latitude", "longitude"])
        rows.append({
            "area": name,
            "bbox": [x0, y0, x1, y1],
            "records": len(b),
            "unique_locations": len(uniq),
            "producers_past_or_present": int(b.dev_stat.isin(["Producer", "Past Producer"]).sum()),
            "passes_total_gate": len(uniq) >= min_total,
        })
    return pd.DataFrame(rows)


def write_report(df: pd.DataFrame, out: Path) -> None:
    with atomic_write(out, "w") as fh:
        df.to_csv(fh, index=False)
