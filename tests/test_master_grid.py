import sys
from pathlib import Path

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from mpm.master_grid import validate_alignment  # noqa: E402


def _tif(path, origin_x=0.0, size=50.0, shape=(4, 6)):
    with rasterio.open(path, "w", driver="GTiff", height=shape[0], width=shape[1], count=1, dtype="float32",
                       crs="EPSG:32613", transform=from_origin(origin_x, 1000.0, size, size)) as d:
        d.write(np.zeros(shape, dtype="float32"), 1)
    return path


def test_aligned_layers_pass(tmp_path):
    validate_alignment([_tif(tmp_path / "a.tif"), _tif(tmp_path / "b.tif")])


def test_one_pixel_shift_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="transform"):
        validate_alignment([_tif(tmp_path / "a.tif"), _tif(tmp_path / "b.tif", origin_x=50.0)])


def test_different_cell_size_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="transform|shape"):
        validate_alignment([_tif(tmp_path / "a.tif"), _tif(tmp_path / "b.tif", size=30.0)])
