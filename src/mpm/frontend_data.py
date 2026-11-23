"""Phase 10c: build-time data for the web frontend (needs the feature file; serving does not).

Outputs in models/final/:
  evidence.npz     per-cell values the click panel shows (float16): eU, eTh, eK (cps), 5 km mean uranium, distance to
                   fault (km), elevation (m), plus the geology unit code, and 101-point survey quantiles for context
  hotspots.json    GeoJSON hot-spot polygons in three tiers (top 1 %, 5 %, 10 % of the study area), the ranked areas of
                   interest, and the known occurrence points. All lon/lat (WGS84), computed from the FINAL map.

Polygons are built on a 4 x 4 pooled grid (200 m) from the maximum percentile so isolated hot cells stay visible, then
reprojected exactly; an axis-aligned image on a lat/lon map would be shifted by kilometres (UTM grid convergence).
The map is in-sample at the known occurrences; `known_inside` tells the reader which areas are partly re-found.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

import numpy as np
import pandas as pd
import rasterio
from pyproj import Transformer
from rasterio import features as rfeat
from rasterio.transform import Affine
from scipy import ndimage as ndi
from shapely.geometry import shape, mapping
from shapely.ops import transform as shp_transform

log = logging.getLogger(__name__)
POOL = 4
TIERS = [("top10", 0.90, "top 10 %"), ("top5", 0.95, "top 5 %"), ("top1", 0.99, "top 1 %")]
EVIDENCE = [("rad_U", "eU"), ("rad_TH", "eTh"), ("rad_K", "eK"), ("nbr_U_mean_5km", "nbr_U_5km"),
            ("str_dist_fault_m", "fault_km"), ("ter_elev", "elev_m")]
MIN_AREA_KM2, MAX_AREAS, JOIN_CELLS = 1.0, 25, 3


def build_evidence(feat_npy: Path, feat_names: list[str], rows: np.ndarray, cols: np.ndarray, unit_tif: Path,
                   class_tif: Path, out_npz: Path) -> dict:
    X = np.load(feat_npy, mmap_mode="r")
    assert X.shape[0] == len(feat_names)
    arrs, q = {}, {}
    qs = np.linspace(0, 1, 101)
    for src, key in EVIDENCE:
        v = np.asarray(X[feat_names.index(src)], dtype="float64")
        if key == "fault_km":
            v = v / 1000.0
        arrs[key] = v.astype("float16")
        q[key] = np.nanquantile(v[::7], qs).tolist()
    u, th = np.asarray(X[feat_names.index("rad_U")], dtype="float64"), np.asarray(X[feat_names.index("rad_TH")], dtype="float64")
    q["u_over_th"] = np.nanquantile((u / np.maximum(th, 0.5))[::7], qs).tolist()
    with rasterio.open(unit_tif) as s:
        unit = s.read(1)[rows, cols].astype("uint16")
    with rasterio.open(class_tif) as s:
        gcls = s.read(1)[rows, cols].astype("uint8")
    np.savez_compressed(out_npz, unit=unit, gclass=gcls, quantiles=json.dumps(q), **arrs)
    return q


def _clusters(mask: np.ndarray):
    """Connected clusters of a boolean pooled grid after joining gaps of up to JOIN_CELLS pooled cells."""
    joined = ndi.binary_closing(mask, structure=np.ones((3, 3)), iterations=JOIN_CELLS) | mask
    lab, n = ndi.label(joined, structure=np.ones((3, 3)))
    return lab, n


def build_hotspots(serving_npz: Path, evidence_npz: Path, positives_csv: Path, legend_csv: Path, out_json: Path) -> dict:
    z = np.load(serving_npz, allow_pickle=True)
    ev = np.load(evidence_npz, allow_pickle=True)
    rows, cols, pct = z["rows"], z["cols"], z["pct"].astype("float32")
    shp = tuple(int(v) for v in z["shape"])
    a, c, e, f = (float(z["transform"][i]) for i in (0, 2, 4, 5))
    crs = str(z["crs"])
    to_ll = Transformer.from_crs(crs, "EPSG:4326", always_xy=True)
    G = np.full(shp, -1.0, dtype="float32")
    G[rows, cols] = pct
    h, w = (shp[0] // POOL) * POOL, (shp[1] // POOL) * POOL
    P = G[:h, :w].reshape(h // POOL, POOL, w // POOL, POOL).max(axis=(1, 3))
    pool_tf = Affine(a * POOL, 0, c, 0, e * POOL, f)
    cell_km2 = abs(a * POOL * e * POOL) / 1e6
    groups = [str(g) for g in z["group_order"]]
    legend = pd.read_csv(legend_csv)
    unit_names = {int(r.code): str(r.unit_name) for r in legend[legend.kind == "unit"].itertuples() if isinstance(r.unit_name, str)}
    class_names = {int(r.code): str(r.label) for r in legend[legend.kind == "class"].itertuples()}

    def to_lonlat(geom):
        return shp_transform(lambda x, y, zz=None: to_ll.transform(x, y), geom)

    out = {"tiers": {}, "areas": [], "known": [], "tier_defs": [{"id": t, "min_percentile": p, "label": l} for t, p, l in TIERS]}
    for tid, thr, label in TIERS:
        m = (P >= thr).astype("uint8")
        polys = []
        for geom, val in rfeat.shapes(m, mask=m.astype(bool), transform=pool_tf, connectivity=8):
            g = shape(geom)
            if g.area / 1e6 < cell_km2 * 1.5:             # drop single-pixel specks
                continue
            g = g.simplify(a * POOL * 0.6, preserve_topology=True)
            polys.append(to_lonlat(g))
        feats = [{"type": "Feature", "properties": {"tier": tid, "label": label},
                  "geometry": mapping(g)} for g in polys if not g.is_empty]
        out["tiers"][tid] = {"type": "FeatureCollection", "features": feats}
        log.info("tier %s: %d polygons", tid, len(feats))

    # ---- areas of interest: clusters of the top-5 % mask ----
    top5 = P >= 0.95
    lab, n = _clusters(top5)
    ci = np.full(shp, 0, dtype="int32")
    ci[:h, :w] = np.kron(lab, np.ones((POOL, POOL), dtype="int32"))
    cell_cluster = ci[rows, cols]
    pos = pd.read_csv(positives_csv)
    pos_cluster = ci[pos["row"].to_numpy(int), pos["col"].to_numpy(int)]
    unc = z["unc"].astype("float32")
    contrib = z["contrib"].astype("float32")
    gmean = z["group_mean"].astype("float32")
    cand = []
    for k in range(1, n + 1):
        sel = np.flatnonzero((cell_cluster == k) & (pct >= 0.95))
        area = sel.size * abs(a * e) / 1e6
        if area < MIN_AREA_KM2:
            continue
        n1 = int((pct[sel] >= 0.99).sum())
        cand.append((n1, area, k, sel))
    cand.sort(key=lambda t: (-t[0], -t[1]))
    for rank, (n1, area, k, sel) in enumerate(cand[:MAX_AREAS], start=1):
        r, cc = rows[sel], cols[sel]
        lon, lat = to_ll.transform(c + (cc + 0.5) * a, f + (r + 0.5) * e)
        lon, lat = np.asarray(lon), np.asarray(lat)
        best = sel[np.argmax(pct[sel])]
        blon, blat = to_ll.transform(c + (cols[best] + 0.5) * a, f + (rows[best] + 0.5) * e)
        drv = (contrib[sel] - gmean).mean(0)
        top = int(np.argmax(np.abs(drv)))
        in_area = pos[pos_cluster == k]
        gcl = np.bincount(ev["gclass"][sel].astype(int), minlength=14).argmax()
        unit = np.bincount(ev["unit"][sel].astype(int)).argmax()
        out["areas"].append({
            "rank": rank, "name": f"Area {rank}", "area_km2": round(float(area), 1),
            "cells_top1pct": n1, "share_top1pct": round(n1 / sel.size, 3),
            "max_percentile": round(float(pct[sel].max()), 4), "mean_percentile": round(float(pct[sel].mean()), 4),
            "centre": {"lon": float(np.median(lon)), "lat": float(np.median(lat))},
            "peak": {"lon": float(blon), "lat": float(blat)},
            "bbox": [float(lon.min()), float(lat.min()), float(lon.max()), float(lat.max())],
            "known_occurrences_inside": int(len(in_area)), "known_producers_inside": int(in_area["is_producer"].sum()),
            "known_names": [str(s) for s in in_area["site_name"].astype(str).tolist() if s not in ("Unknown", "nan")][:5],
            "mean_uncertainty": round(float(unc[sel].mean()), 4),
            "main_driver_group": groups[top], "main_driver_effect": round(float(drv[top]), 2),
            "mean_edge_km": round(float(z["edge_km"][sel].mean()), 1),
            "mean_eU": round(float(np.nanmean(ev["eU"][sel].astype("float32"))), 1),
            "mean_eTh": round(float(np.nanmean(ev["eTh"][sel].astype("float32"))), 1),
            "mean_eK": round(float(np.nanmean(ev["eK"][sel].astype("float32"))), 1),
            "main_rock_class": class_names.get(int(gcl), "unknown"),
            "main_rock_unit": unit_names.get(int(unit), "unknown"),
            "cover_share": round(float(z["cover"][sel].mean()), 2),
        })
    # ---- known occurrences ----
    plon, plat = to_ll.transform(pos["x"].to_numpy(), pos["y"].to_numpy())
    for lo, la, r in zip(plon, plat, pos.itertuples()):
        out["known"].append({"lon": round(float(lo), 5), "lat": round(float(la), 5), "name": str(r.site_name),
                             "status": str(r.dev_stat), "producer": bool(r.is_producer)})
    out["unit_names"] = {str(k): v for k, v in unit_names.items()}
    out["class_names"] = {str(k): v for k, v in class_names.items()}
    tmp = Path(str(out_json) + ".tmp")
    tmp.write_text(json.dumps(out, separators=(",", ":")), encoding="utf-8")
    tmp.replace(out_json)
    return {"areas": len(out["areas"]), "known": len(out["known"]),
            "polygons": {t: len(v["features"]) for t, v in out["tiers"].items()}, "bytes": out_json.stat().st_size}
