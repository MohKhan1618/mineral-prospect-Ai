"""Phase 4: terrain (SRTM 1 arc-second tiles) and state geology (SGMC) downloads and unpacking."""
from __future__ import annotations

import gzip
import shutil
import zipfile
from pathlib import Path

from .download import download, register
from .runner import atomic_write

# Skadi tiles are named by their south-west corner. The survey spans lon -109.16..-106.70, lat 42.01..42.84.
SRTM_TILES = ["N42W110", "N42W109", "N42W108", "N42W107"]
SRTM_URL = "https://s3.amazonaws.com/elevation-tiles-prod/skadi/N{lat}/{name}.hgt.gz"
SGMC_WY_URL = "https://mrdata.usgs.gov/geology/state/shp/WY.zip"


def srtm_gz_path(raw: Path, name: str) -> Path:
    return raw / "terrain" / f"{name}.hgt.gz"


def srtm_hgt_path(raw: Path, name: str) -> Path:
    return raw / "terrain" / f"{name}.hgt"


def download_srtm(raw: Path, manifest: Path) -> None:
    for n in SRTM_TILES:
        p = download(SRTM_URL.format(lat=n[1:3], name=n), srtm_gz_path(raw, n))
        register(manifest, f"srtm_{n}", SRTM_URL.format(lat=n[1:3], name=n), p,
                 "public domain (NASA SRTM, hosted as AWS Open Data terrain tiles; verify)", "SRTM 1 arc-second, about 30 m")


def gunzip_srtm(raw: Path) -> None:
    for n in SRTM_TILES:
        with gzip.open(srtm_gz_path(raw, n), "rb") as src, atomic_write(srtm_hgt_path(raw, n), "wb") as dst:
            shutil.copyfileobj(src, dst)


def download_sgmc(raw: Path, manifest: Path) -> Path:
    p = download(SGMC_WY_URL, raw / "geology" / "WY.zip")
    register(manifest, "sgmc_wy_zip", SGMC_WY_URL, p, "CC0 1.0 (USGS SGMC; verify on source page)",
             "Wyoming state geologic map, shapefile + CSV")
    return p


def unzip_sgmc(zip_path: Path, out_dir: Path) -> None:
    """Extract into out_dir; every member is written atomically (crash-safe)."""
    with zipfile.ZipFile(zip_path) as z:
        for info in z.infolist():
            if info.is_dir():
                continue
            dest = Path(out_dir) / info.filename
            if dest.exists() and dest.stat().st_size == info.file_size:
                continue
            with z.open(info) as src, atomic_write(dest, "wb") as fh:
                shutil.copyfileobj(src, fh)
