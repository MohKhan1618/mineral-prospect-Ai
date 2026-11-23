"""Single source of truth for settings and paths."""
from __future__ import annotations

import logging
import random
from dataclasses import dataclass
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Paths:
    root: Path
    raw: Path
    interim: Path
    processed: Path
    features: Path
    splits: Path
    models: Path
    reports: Path
    state: Path


def load_config(path: Path | None = None) -> dict:
    path = path or ROOT / "config" / "config.yaml"
    with open(path, "r", encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh)
    return cfg


def get_paths(cfg: dict | None = None) -> Paths:
    cfg = cfg or load_config()
    d = cfg["paths"]
    return Paths(root=ROOT, **{k: ROOT / v for k, v in d.items()})


def set_seed(seed: int) -> None:
    random.seed(seed)
    try:
        import numpy as np

        np.random.seed(seed)
    except ImportError:
        pass


def setup_logging(level: int = logging.INFO) -> None:
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-5s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
