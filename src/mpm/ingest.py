"""Phase 2: confirm the manually extracted survey files are present and complete.

The USGS zips use Deflate64 compression, which Python's zipfile cannot read, so the
user extracted them with Windows Explorer. This module therefore does not extract; it
checks the result and records sizes so later stages can detect a damaged copy.
"""
from __future__ import annotations

import json
from pathlib import Path

from .runner import atomic_write

SURVEY = "AirborneMagneticAndRadiometricSurveySouthPassGraniteMtnsWY2023"

# Paths relative to the "ContractorsDeliverables_<SURVEY>" folder.
RADIOMETRIC_GRIDS = ["U_FIN", "TH_FIN", "K_FIN", "TC_FIN", "U_FIN_s", "TH_FIN_s", "K_FIN_s", "TC_FIN_s"]
MAGNETIC_GRIDS = ["RTP", "Mag_IGRF", "VD"]


def required_files() -> list[str]:
    """Files the pipeline depends on: real-valued grids with their .xml metadata, plus the survey JSON."""
    files = [f"radiometrics/GRIDS/{n}.grd" for n in RADIOMETRIC_GRIDS]
    files += [f"radiometrics/GRIDS/{n}.grd.xml" for n in RADIOMETRIC_GRIDS]
    files += [f"magnetics/GRIDS/{n}.grd" for n in MAGNETIC_GRIDS]
    files += [f"magnetics/GRIDS/{n}.grd.xml" for n in MAGNETIC_GRIDS]
    files.append("metadata/140G0223F0013-WY2-SouthPassGraniteMountains-METADATA.json")
    return files


def required_footprint_files() -> list[str]:
    stem = f"Footprint_{SURVEY}"
    return [f"{stem}.{ext}" for ext in ("shp", "shx", "dbf", "prj")]


def verify_extracted(survey_dir: Path, flag: Path) -> None:
    """Raise if any required file is missing or empty; otherwise write a size manifest."""
    survey_dir = Path(survey_dir)
    deliv = survey_dir / f"ContractorsDeliverables_{SURVEY}"
    foot = survey_dir / f"Footprint_{SURVEY}"
    sizes: dict[str, int] = {}
    missing: list[str] = []
    for base, rels in ((deliv, required_files()), (foot, required_footprint_files())):
        for rel in rels:
            p = base / rel
            if p.is_file() and p.stat().st_size > 0:
                sizes[f"{base.name}/{rel}"] = p.stat().st_size
            else:
                missing.append(str(p))
    if missing:
        raise FileNotFoundError("Missing or empty survey files:\n  " + "\n  ".join(missing))
    with atomic_write(flag, "w") as fh:
        json.dump(sizes, fh, indent=2)
